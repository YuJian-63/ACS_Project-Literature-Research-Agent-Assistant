import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.agent_bridge.bundles import export_bundle, manifest_digest, read_result
from app.agent_bridge.policy import build_manifest, build_research_manifest
from app.agent_bridge.results import present_result, validate_delivery
from app.agent_bridge.tacc import TaccTransport
from app.agent_bridge.transport import LocalTransport
from app.config import Settings

REPOSITORY = Path(__file__).resolve().parents[2]
AGENT_PYTHON = Path(
    os.environ.get(
        "AGENT_TEST_PYTHON",
        str(
            REPOSITORY
            / "agent"
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ),
    )
)


@unittest.skipUnless(
    AGENT_PYTHON.is_file(),
    "Install the separate Agent environment for offline process integration",
)
class AgentProcessRoundtripTests(unittest.TestCase):
    def test_search_only_backend_bundle_crosses_actual_agent_process_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            settings = Settings(_env_file=None, database_url="postgresql://unused@127.0.0.1/literature_v3_test_unused",
                storage_root=root)
            manifest = build_research_manifest(uuid4(), uuid4(), "Explain attention", [], settings, allow_search=True)
            bundle = export_bundle(manifest, root, settings.resolved_agent_exchange_root)
            script = """import sys, socket
from pathlib import Path
from agent_io.job import run_dispatch
from schemas import Evidence, TaskResult, Usage
def no_network(*args, **kwargs):
    raise AssertionError('offline contract test must not access the network')
socket.socket.connect = no_network
def runner(task, **kwargs):
    assert task.allow_search and not task.sources
    source = {'source_id': 'arxiv:1706.03762v7', 'paper_id': 'arxiv:1706.03762',
        'title': 'External evidence', 'url': 'https://arxiv.org/abs/1706.03762v7'}
    evidence = Evidence(**source, chunk_id='arxiv:1706.03762v7:p1:c1', page=1,
        source_text='Original evidence.')
    return TaskResult(task_id=task.task_id, question=task.question, answer='Answer [' + evidence.chunk_id + ']',
        citations=[evidence], sources=[source], stop_reason='completed', usage=Usage())
run_dispatch(Path(sys.argv[1]), work_root=Path(sys.argv[2]), output_dir=Path(sys.argv[3]),
    dispatch_id=sys.argv[4], input_sha256=sys.argv[5], runner=runner)
"""
            completed = subprocess.run([str(AGENT_PYTHON), "-B", "-c", script,
                str(bundle), str(root / "work"), str(root / "output"), str(manifest.dispatch_id),
                manifest_digest(manifest)], cwd=REPOSITORY / "agent", capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
            envelope = read_result(root / "output" / "result.json", settings.agent_result_max_bytes)
            validate_delivery(manifest, envelope)
            self.assertEqual(envelope.result.citations[0].paper_id, "arxiv:1706.03762")
            self.assertEqual(present_result(manifest, envelope.result).citations, [])

    def test_real_pdf_and_scripted_agent_cross_separate_processes_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            uploads = root / "uploads"
            uploads.mkdir()
            paper_id = uuid4()
            pdf = uploads / f"{paper_id}.pdf"
            subprocess.run(
                [
                    str(AGENT_PYTHON),
                    "-B",
                    "-c",
                    "import pymupdf,sys; d=pymupdf.open(); d.new_page().insert_text((40,40),'Original method and results.'); d.new_page(); d.new_page().insert_text((40,40),'Limitations on physical page three.'); d.save(sys.argv[1]); d.close()",
                    str(pdf),
                ],
                check=True,
                timeout=30,
                capture_output=True,
            )
            agent_root = root / "agent offline bootstrap"
            agent_root.mkdir()
            bootstrap = "import sys, socket\n"
            bootstrap += (
                "sys.path[:0] = "
                + repr([str(REPOSITORY / "agent"), str(REPOSITORY / "agent" / "tests")])
                + "\n"
            )
            bootstrap += """from baseline import run_task
from test_baseline import ScriptedModel, call, final, message
from agent_io import job
def no_network(*args, **kwargs):
    raise AssertionError('offline integration must not access the network')
socket.socket.connect = no_network
original = job.run_dispatch
def runner(task, **kwargs):
    source = task.sources[0]
    model = ScriptedModel([message(calls=[call(source=source, page_start=3, page_end=3)]), final(source + ':p3:c1')])
    return run_task(task, model_factory=model.factory, **kwargs)
def dispatch(*args, **kwargs):
    return original(*args, runner=runner, **kwargs)
job.run_dispatch = dispatch
raise SystemExit(job.main())
"""
            (agent_root / "run_dispatch.py").write_text(bootstrap, encoding="utf-8")
            settings = Settings(
                _env_file=None,
                database_url="postgresql://unused:unused@127.0.0.1/literature_v3_test_unused",
                storage_root=root,
                agent_transport="local",
                agent_local_root=agent_root,
                agent_local_python=AGENT_PYTHON,
                agent_poll_seconds=0.1,
            )
            content = pdf.read_bytes()
            manifest = build_manifest(
                uuid4(),
                uuid4(),
                "qa",
                "论文的局限是什么？",
                [
                    {
                        "paper_id": str(paper_id),
                        "title": "Authorized original PDF",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "page_count": 3,
                    }
                ],
                settings,
            )
            bundle = export_bundle(
                manifest, root, settings.resolved_agent_exchange_root
            )
            transport = LocalTransport(settings)
            transport.upload(manifest, bundle)
            launch_process = subprocess.Popen
            with patch(
                "app.agent_bridge.transport.subprocess.Popen", wraps=launch_process
            ) as launch:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    job_ids = list(
                        executor.map(lambda _: transport.submit(manifest), range(2))
                    )
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(job_ids[0], job_ids[1])
                job_id = job_ids[0]
            directory = (
                settings.resolved_agent_exchange_root
                / "jobs"
                / str(manifest.dispatch_id)
            )
            deadline = time.monotonic() + 40
            try:
                while (
                    not (directory / "exit.json").exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                self.assertTrue(
                    (directory / "exit.json").exists(),
                    "local supervisor did not finish",
                )
                self.assertEqual(
                    json.loads((directory / "exit.json").read_bytes())["returncode"], 0
                )
                self.assertEqual(transport.poll(manifest, job_id).state, "succeeded")
                incoming = transport.download(manifest, job_id)
                envelope = read_result(incoming, settings.agent_result_max_bytes)
                validate_delivery(manifest, envelope)
                presentation = present_result(manifest, envelope.result)
                self.assertEqual(presentation.citations[0].paper_id, paper_id)
                self.assertEqual(presentation.citations[0].page_number, 3)
                self.assertIn("[C1]", presentation.content_markdown)
                self.assertTrue(envelope.result.trace)
                self.assertEqual(
                    LocalTransport(settings).submit(manifest, job_id), job_id
                )
                self.assertFalse(list(directory.glob("*.part")))
                self.verify_tacc_rpc(root, settings, manifest, bundle, agent_root)
            finally:
                transport.cancel(manifest, job_id)
                while (
                    not (directory / "exit.json").exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)

    def verify_tacc_rpc(self, root, settings, manifest, bundle, agent_root):
        manifest = manifest.model_copy(
            update={
                "dispatch_id": uuid4(),
                "task": manifest.task.model_copy(update={"task_id": str(uuid4())}),
            }
        )
        bundle = export_bundle(manifest, root, settings.resolved_agent_exchange_root)
        config = root / "tacc-config.json"
        config.write_text(
            json.dumps(
                {
                    "workspace_root": str(root / "remote-jobs"),
                    "agent_root": str(agent_root),
                    "python": str(AGENT_PYTHON),
                    "retention_seconds": 86400,
                }
            ),
            encoding="utf-8",
        )
        login = root / "offline-login.py"
        login.write_text(
            "import sys\nsys.path.insert(0,"
            + repr(str(REPOSITORY / "agent"))
            + ")\n"
            + """import shlex, subprocess
from pathlib import Path
import tacc_bridge
def scheduler(arguments, **kwargs):
    if arguments[0] == 'sbatch':
        with (Path(arguments[-1]).parent / 'launches').open('a') as output:
            output.write('submitted' + chr(10))
        script = Path(arguments[-1]).read_text(encoding='utf-8')
        execution = next(line for line in script.splitlines() if line.startswith('exec '))
        command = shlex.split(execution)[1:]
        command[-1] = '8123'
        response = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if response.returncode:
            raise AssertionError('scripted remote Agent failed')
        return '8123;offline'
    if arguments[0] == 'squeue':
        return ''
    if arguments[0] == 'sacct':
        return '8123|COMPLETED'
    if arguments[0] == 'scancel':
        return ''
    raise AssertionError('unapproved command')
tacc_bridge.command = scheduler
raise SystemExit(tacc_bridge.main())
""",
            encoding="utf-8",
        )
        remote = TaccTransport(
            settings.model_copy(
                update={
                    "agent_transport": "tacc",
                    "agent_tacc_host": "offline-test",
                    "agent_tacc_helper": "/trusted/tacc_bridge.py",
                    "agent_tacc_config": "/trusted/config.json",
                }
            )
        )
        run_process = subprocess.run

        def ssh(arguments, **kwargs):
            self.assertEqual(arguments[0], "ssh")
            return run_process(
                [str(AGENT_PYTHON), "-B", str(login), "--config", str(config)], **kwargs
            )

        with patch("app.agent_bridge.tacc.subprocess.run", side_effect=ssh):
            remote.upload(manifest, bundle)
            with ThreadPoolExecutor(max_workers=2) as executor:
                job_ids = list(
                    executor.map(lambda _: remote.submit(manifest), range(2))
                )
            self.assertEqual(job_ids[0], job_ids[1])
            job_id = job_ids[0]
            launches = root / "remote-jobs" / str(manifest.dispatch_id) / "launches"
            self.assertEqual(launches.read_text().splitlines(), ["submitted"])
            self.assertEqual(job_id, "8123")
            self.assertEqual(remote.poll(manifest, job_id).state, "succeeded")
            incoming = remote.download(manifest, job_id)
            envelope = read_result(incoming, settings.agent_result_max_bytes)
            self.assertEqual(envelope.remote_job_id, "8123")
            self.assertEqual(envelope.result.citations[0].page, 3)
            self.assertEqual(remote.submit(manifest, job_id), job_id)
            self.assertTrue(remote.cancel(manifest, job_id))


if __name__ == "__main__":
    unittest.main()
