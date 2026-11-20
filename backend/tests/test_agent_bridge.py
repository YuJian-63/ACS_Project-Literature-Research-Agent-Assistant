import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.agent_bridge.bundles import export_bundle, manifest_digest, read_result
from app.agent_bridge.contracts import AgentTask, DispatchManifest, ResultEnvelope
from app.agent_bridge.policy import build_manifest
from app.agent_bridge.results import present_result, validate_delivery
from app.config import Settings
from pydantic import ValidationError


class AgentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.settings = Settings(_env_file=None, database_url="postgresql://unused:unused@127.0.0.1/unused",
            storage_root=self.root, task_runner="agent", agent_dispatch_enabled=True)
        self.paper_id = uuid4()
        self.pdf = b"%PDF-1.7\nfixture for transport only"
        uploads = self.root / "uploads"
        uploads.mkdir()
        (uploads / f"{self.paper_id}.pdf").write_bytes(self.pdf)
        self.source = {"paper_id": str(self.paper_id), "title": "Selected paper",
            "sha256": hashlib.sha256(self.pdf).hexdigest(), "size_bytes": len(self.pdf), "page_count": 3}
        self.manifest = build_manifest(uuid4(), uuid4(), "qa", "作者提出了什么方法？", [self.source], self.settings)

    def delivery(self, reason="completed"):
        source = self.manifest.sources[0]
        chunk = f"{source.source_id}:p2:c1"
        return {"schema_version": "agent-result-v1", "dispatch_id": str(self.manifest.dispatch_id),
            "input_sha256": manifest_digest(self.manifest), "remote_job_id": "remote-job-fixture",
            "result": {"task_id": self.manifest.task.task_id, "question": self.manifest.task.question,
                "answer": f"A supported answer [{chunk}]", "comparison_table": f"| Method | Evidence |\n|---|---|\n| A | [{chunk}] |",
                "citations": [{"chunk_id": chunk, "source_id": source.source_id, "paper_id": source.source_id,
                    "page": 2, "source_text": "Verbatim evidence.", "title": source.title, "url": ""}],
                "stop_reason": reason, "unresolved": ["One aspect remains"] if reason == "partial" else [],
                "usage": {"agent_steps": 2, "model_calls": 3, "tool_calls": 4, "input_tokens": 100,
                    "output_tokens": 30, "total_tokens": 130, "token_usage_complete": True, "elapsed_seconds": 1.2}}}

    def test_task_matches_agent_strict_input_and_preserves_chinese_question(self):
        task = self.manifest.task.model_dump(mode="json")
        self.assertNotIn("task_type", task)
        self.assertNotIn("budget", task)
        self.assertIn("作者提出了什么方法", task["question"])
        self.assertFalse(task["allow_search"])
        self.assertEqual(task["max_papers"], 1)
        self.assertEqual(task["sources"], [f"local:{self.paper_id}@{self.source["sha256"]}"])
        with self.assertRaises(ValidationError):
            AgentTask.model_validate(task | {"budget": {}})

    def test_wire_models_are_accepted_by_the_actual_agent_contract(self):
        path = Path(__file__).resolve().parents[2] / "agent" / "schemas.py"
        spec = importlib.util.spec_from_file_location("standalone_agent_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        task = module.Task.model_validate(self.manifest.task.model_dump(mode="json"))
        result = module.TaskResult.model_validate(self.delivery()["result"])
        self.assertEqual(task.sources, self.manifest.task.sources)
        self.assertEqual(result.citations[0].page, 2)

    def test_larger_review_gets_server_limits_and_never_exceeds_caps(self):
        papers = [self.source | {"paper_id": str(uuid4())} for _ in range(20)]
        review = build_manifest(uuid4(), uuid4(), "review", "比较论文", papers, self.settings)
        self.assertGreater(review.task.max_steps, self.manifest.task.max_steps)
        self.assertGreater(review.task.max_output_tokens, self.manifest.task.max_output_tokens)
        self.assertLessEqual(review.task.max_steps, 100)
        self.assertLessEqual(review.task.timeout_seconds, 1800)
        self.assertLessEqual(review.task.max_output_tokens, self.settings.agent_output_tokens)

    def test_bundle_only_contains_authorized_inputs_and_is_idempotent(self):
        (self.root / ".env").write_text("PRIVATE_KEY=must-not-leak", encoding="utf-8")
        spool = self.root / "exchange"
        path = export_bundle(self.manifest, self.root, spool)
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(set(bundle.namelist()), {"manifest.json", "task.json", "sources.json", f"papers/{self.paper_id}.pdf"})
            self.assertEqual(bundle.read(f"papers/{self.paper_id}.pdf"), self.pdf)
            self.assertEqual(json.loads(bundle.read("task.json")), self.manifest.task.model_dump(mode="json"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(export_bundle(self.manifest, self.root, spool), path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_changed_pdf_cannot_be_published(self):
        (self.root / "uploads" / f"{self.paper_id}.pdf").write_bytes(b"%PDF-modified")
        with self.assertRaises(ValueError):
            export_bundle(self.manifest, self.root, self.root / "exchange")
        self.assertFalse(list((self.root / "exchange").rglob("input.zip")))

    def test_rebuilt_bundle_bytes_are_stable_for_restart_recovery(self):
        with patch("zipfile.time.localtime", return_value=(2024, 1, 1, 0, 0, 0, 0, 1, -1)):
            path = export_bundle(self.manifest, self.root, self.root / "exchange")
        original = path.read_bytes()
        path.unlink()
        with patch("zipfile.time.localtime", return_value=(2025, 1, 1, 0, 0, 0, 0, 1, -1)):
            rebuilt = export_bundle(self.manifest, self.root, self.root / "exchange")
        self.assertEqual(rebuilt.read_bytes(), original)

    def test_recovery_does_not_reuse_a_corrupted_existing_input_bundle(self):
        spool = self.root / "exchange"
        path = export_bundle(self.manifest, self.root, spool)
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps(self.manifest.model_dump(mode="json")))
            bundle.writestr("unexpected-secret.txt", "must not submit")
        with self.assertRaises(ValueError):
            export_bundle(self.manifest, self.root, spool)

    def test_result_reader_rejects_nul_but_accepts_escaped_source_code(self):
        path = self.root / "result.json"
        payload = self.delivery()
        payload["result"]["answer"] = "Code example: \\u0000"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(read_result(path, 100000).result.answer, "Code example: \\u0000")
        payload["result"]["answer"] = "NUL: \x00"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            read_result(path, 100000)

    def test_manifest_rejects_traversal_and_duplicate_source_identity(self):
        value = self.manifest.model_dump(mode="json")
        value["sources"][0]["path"] = "../private.pdf"
        with self.assertRaises(ValidationError):
            DispatchManifest.model_validate(value)
        value = self.manifest.model_dump(mode="json")
        value["sources"].append(value["sources"][0])
        with self.assertRaises(ValidationError):
            DispatchManifest.model_validate(value)

    def test_replays_cannot_cross_dispatch_task_or_input_identity(self):
        for key, replacement in (("dispatch_id", str(uuid4())), ("input_sha256", "0" * 64)):
            with self.subTest(key=key):
                value = self.delivery() | {key: replacement}
                with self.assertRaises(ValueError):
                    validate_delivery(self.manifest, ResultEnvelope.model_validate(value))
        for key in ("task_id", "question"):
            value = self.delivery()
            value["result"][key] = "different"
            with self.assertRaises(ValueError):
                validate_delivery(self.manifest, ResultEnvelope.model_validate(value))

    def test_foreign_sources_and_invalid_page_are_rejected(self):
        for update in ({"source_id": "local:foreign"}, {"paper_id": "arxiv:foreign"}, {"page": 4}):
            value = self.delivery()
            value["result"]["citations"][0].update(update)
            with self.assertRaises(ValueError):
                validate_delivery(self.manifest, ResultEnvelope.model_validate(value))

    def test_presentation_maps_to_original_pdf_and_keeps_raw_result(self):
        envelope = ResultEnvelope.model_validate(self.delivery("partial"))
        original = copy.deepcopy(envelope.result.model_dump())
        validate_delivery(self.manifest, envelope)
        presentation = present_result(self.manifest, envelope.result)
        self.assertIn("[C1]", presentation.content_markdown)
        self.assertIn("| Method | Evidence |", presentation.content_markdown)
        self.assertEqual(presentation.citations[0].paper_id, self.paper_id)
        self.assertEqual(presentation.citations[0].page_number, 2)
        self.assertEqual(presentation.citations[0].agent_chunk_id, envelope.result.citations[0].chunk_id)
        self.assertEqual(envelope.result.model_dump(), original)

    def test_comparison_projection_uses_the_same_citation_keys(self):
        from app.agent_bridge.results import normalize_citation_references

        envelope = ResultEnvelope.model_validate(self.delivery())
        chunk = envelope.result.citations[0].chunk_id
        rendered = normalize_citation_references(envelope.result.comparison_table, {chunk: "C1"})
        self.assertIn("[C1]", rendered)
        self.assertNotIn(chunk, rendered)
        self.assertIn(chunk, envelope.result.comparison_table)
        text = f"[{chunk}, chunk_id: second] [unknown] [Reference](https://example.org)"
        rendered = normalize_citation_references(text, {chunk: "C1", "second": "C2"})
        self.assertEqual(rendered, "[C1] [C2] [unknown] [Reference](https://example.org)")

    def test_answer_language_follows_the_actual_question_instead_of_the_wrapper(self):
        for question in ("作者提出了什么方法？", "What method does the paper propose?",
                         "请比较 English benchmark 和 Rust agents 的实验结果。"):
            with self.subTest(question=question):
                manifest = build_manifest(uuid4(), uuid4(), "qa", question, [self.source], self.settings)
                self.assertIn("same language as the user question", manifest.task.question)
                self.assertIn("not the language of these instructions", manifest.task.question)
                self.assertTrue(manifest.task.question.endswith(question))
                self.assertNotIn("answer in Chinese", manifest.task.question)
        summary = build_manifest(uuid4(), uuid4(), "summary", None, [self.source], self.settings)
        self.assertIn("answer in Chinese", summary.task.question)

    def test_unknown_stop_reason_negative_usage_and_boolean_counts_are_rejected(self):
        with self.assertRaises(ValidationError):
            ResultEnvelope.model_validate(self.delivery("arbitrary-success"))
        for number in (-1, True):
            value = self.delivery()
            value["result"]["usage"]["tool_calls"] = number
            with self.assertRaises(ValidationError):
                ResultEnvelope.model_validate(value)

    def test_result_reader_enforces_limit_and_rejects_duplicate_json_keys(self):
        path = self.root / "result.json"
        path.write_text(json.dumps(self.delivery()), encoding="utf-8")
        self.assertEqual(read_result(path, 100000).result.stop_reason, "completed")
        with self.assertRaises(ValueError):
            read_result(path, 10)
        path.write_text('{"schema_version":"agent-result-v1","schema_version":"other"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            read_result(path, 100000)


if __name__ == "__main__":
    unittest.main()
