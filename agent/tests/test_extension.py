"""Offline retrieval through the Extension's normal model and tool loop."""

import httpx
import pytest
from test_baseline import CHUNK, ScriptedModel, call, final, message, observations, paper

from apis import database, embeddings
from extension import run_task
from schemas import Task

SOURCE = "1706.03762v7"
SECOND_CHUNK = "arxiv:1706.03762v7:p2:c1"


def retrieve(query="method", *, source=SOURCE, top_k=1):
    return message(calls=[call("retrieve", source=source, query=query, top_k=top_k)])


def embed_texts(texts, *, model, timeout, purpose):
    # Page 1 is closest to "method", page 2 to "results".
    vectors = [
        [0, 1] if text in {"results", "Original evidence on page 2."} else [1, 0] for text in texts
    ]
    return vectors, len(texts) * 11


def run(
    replies,
    index_dir,
    *,
    embed=embed_texts,
    reader=paper,
    embedding_model="test-model",
    sources=(SOURCE,),
):
    return run_task(
        Task(question="Which page supports the answer?", sources=list(sources), timeout_seconds=45),
        model_factory=ScriptedModel(replies).factory,
        embed=embed,
        reader=reader,
        embedding_model=embedding_model,
        index_dir=index_dir,
    )


def test_open_and_read_never_request_embeddings(tmp_path):
    calls = []
    result = run(
        [message(calls=[call("open_paper", source=SOURCE)]), message(calls=[call()]), final()],
        tmp_path,
        embed=lambda *args, **kwargs: calls.append(args),
    )
    assert result.stop_reason == "completed"
    assert not calls


def test_retrieval_keeps_hit_order_and_shows_each_original_once(tmp_path):
    result = run(
        [message(calls=[call()]), retrieve(top_k=2), retrieve("results", top_k=2),
         message(calls=[call(source=SOURCE, page_start=2, page_end=2)]), final(SECOND_CHUNK)],
        tmp_path,
        reader=lambda source, **kwargs: paper(source, page_count=2),
    )
    _, mixed, repeated, reread = observations(result)
    first, second = mixed["chunks"]
    assert first == {"source_id": f"arxiv:{SOURCE}", "page": 1, "chunk_id": CHUNK,
                     "status": "already_read"}
    assert second["chunk_id"] == SECOND_CHUNK
    assert second["source_text"] == "Original evidence on page 2."
    assert mixed.get("status") != "already_read"
    assert repeated["status"] == reread["status"] == "already_read"
    assert [hit["chunk_id"] for hit in repeated["chunks"]] == [SECOND_CHUNK, CHUNK]
    assert all("source_text" not in hit for hit in repeated["chunks"])
    assert result.stop_reason == "completed"
    assert result.citations[0].source_text == second["source_text"]


def test_embedding_adapter_matches_vectors_to_inputs_using_provider_indices(monkeypatch):
    def post(url, *, json, **kwargs):
        assert json["input"] == ["page one", "page two"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
                "usage": {"prompt_tokens": 4},
            },
        )

    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "2")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(embeddings, "require_env", lambda name: "test-key")
    monkeypatch.setattr(embeddings.httpx, "post", post)
    assert embeddings.embed_texts(
        ["page one", "page two"], model="test-model", timeout=1, purpose="document"
    ) == ([[1, 0], [0, 1]], 4)


def test_persist_extension_result_separately_for_same_task_id(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(database, "save_paper", lambda paper: None)

    def save_run(payload, *, storage_key):
        saved[storage_key] = payload["task_id"]

    monkeypatch.setattr(database, "save_run", save_run)
    task = Task(task_id="qa", question="Which page?", sources=[SOURCE])
    result = run_task(
        task,
        model_factory=ScriptedModel([message(calls=[call()]), final()]).factory,
        reader=paper,
        index_dir=tmp_path,
        persist=True,
    )
    assert result.stop_reason == "completed"
    assert not result.errors
    assert saved == {"extension/qa": "qa"}


def test_retrieval_reuses_opened_paper_and_only_embeds_queries_after_indexing(tmp_path):
    downloads = []
    requests = []

    def reader(source, **kwargs):
        downloads.append(source)
        return paper(source, page_count=2)

    def embed(texts, *, model, purpose, timeout):
        requests.append((purpose, list(texts), timeout))
        return embed_texts(texts, model=model, purpose=purpose, timeout=timeout)

    result = run(
        [
            message(calls=[call("open_paper", source="1706.03762")]),
            retrieve("results", source=SOURCE),
            retrieve("method", source="1706.03762"),
            final(),
        ],
        tmp_path,
        reader=reader,
        embed=embed,
        sources=["1706.03762"],
    )
    assert result.stop_reason == "completed"
    assert downloads == ["1706.03762"]
    assert [text for purpose, texts, _ in requests if purpose == "document" for text in texts] == [
        "Original evidence on page 1.",
        "Original evidence on page 2.",
    ]
    assert [texts for purpose, texts, _ in requests if purpose == "query"] == [
        ["results"],
        ["method"],
    ]
    assert all(0 < timeout <= 45 for _, _, timeout in requests)
    _, first, second = observations(result)
    assert [chunk["chunk_id"] for chunk in first["chunks"]] == [SECOND_CHUNK]
    assert [chunk["chunk_id"] for chunk in second["chunks"]] == [CHUNK]
    assert result.citations[0].source_text == "Original evidence on page 1."
    assert result.usage.total_tokens == 4 * 120  # Chat usage is separate from embedding usage.
    embeddings = [entry for entry in result.trace if entry["kind"] == "embedding"]
    assert sum(entry["input_tokens"] for entry in embeddings) == 4 * 11
    assert [entry["action"] for entry in result.trace if entry["kind"] == "retrieval_index"] == [
        "build",
        "reuse",
    ]


def test_direct_retrieval_reuses_compatible_index_and_validates_returned_evidence(tmp_path):
    requests = []
    downloads = []

    def reader(source, **kwargs):
        downloads.append(source)
        return paper(source, page_count=2)

    def embed(texts, *, model, purpose, timeout):
        requests.append((model, purpose))
        return embed_texts(texts, model=model, purpose=purpose, timeout=timeout)

    # Ranks page one; building the full index must not register page two as cited evidence.
    result = run([retrieve(), final(SECOND_CHUNK)], tmp_path, reader=reader, embed=embed)
    assert result.stop_reason == "invalid_citations"
    assert not result.citations
    assert downloads == [SOURCE]
    assert ("test-model", "document") in requests
    requests.clear()

    result = run([retrieve("results"), final(SECOND_CHUNK)], tmp_path, reader=reader, embed=embed)
    assert result.stop_reason == "completed"
    assert requests == [("test-model", "query")]

    requests.clear()
    result = run(
        [retrieve(), final()], tmp_path, reader=reader, embed=embed, embedding_model="new-model"
    )
    assert result.stop_reason == "completed"
    assert ("new-model", "document") in requests

    requests.clear()

    def reparsed(source, **kwargs):
        updated = reader(source, **kwargs)
        updated["chunks"][0]["source_text"] = "A corrected passage."
        updated["pages"][0]["text"] = "A corrected passage."
        return updated

    result = run([retrieve(), final()], tmp_path, reader=reparsed, embed=embed)
    assert result.stop_reason == "completed"
    assert result.citations[0].source_text == "A corrected passage."
    assert ("test-model", "document") in requests


def test_joint_ranking_uses_only_selected_papers_and_reuses_their_indexes(tmp_path):
    a, b, c = SOURCE, "2106.09685v1", "2305.14314v1"
    ids = {source: f"arxiv:{source}" for source in (a, b, c)}
    vectors = {
        "Training cost": [1, 0],
        "Inference cost": [0, 1],
        f"{a} page 1": [1, 0],
        f"{a} page 2": [4, 1],
        f"{b} page 1": [1, 1],
        f"{b} page 2": [0, 1],
        f"{c} page 1": [1, 0],
        f"{c} page 2": [1, 4],
    }
    loads = []
    queries = []

    def reader(source, **kwargs):
        loads.append(source)
        parsed = paper(source, page_count=2)
        paper_id, version = ids[source].rsplit("v", 1)
        metadata = {"paper_id": paper_id, "source_id": ids[source], "version": f"v{version}"}
        parsed.update(metadata, title=source, url=f"https://arxiv.org/abs/{source}")
        for chunk, page in zip(parsed["chunks"], parsed["pages"], strict=True):
            number = chunk["page"]
            page["text"] = f"{source} page {number}"
            chunk.update(metadata, chunk_id=f"{ids[source]}:p{number}:c1", source_text=page["text"])
        return parsed

    def embed(texts, *, purpose, **kwargs):
        if purpose == "query":
            queries.append(texts)
        return [vectors[text] for text in texts], len(texts)

    # A's two chunks beat all of B's for training. C is only selected in the second call.
    b_hit = f"{ids[b]}:p2:c1"
    c_hit = f"{ids[c]}:p2:c1"
    b_miss = f"{ids[b]}:p1:c1"
    result = run(
        [
            retrieve("Training cost", source=[b, a, ids[a]], top_k=2),
            retrieve("Inference cost", source=[c, b], top_k=2),
            final(answer=f"[{b_hit}] [{c_hit}] [{b_miss}]"),
        ],
        tmp_path,
        reader=reader,
        embed=embed,
        sources=[a, b, c],
    )
    first, second = observations(result)
    assert first["source_ids"] == [ids[b], ids[a]]
    assert [chunk["chunk_id"] for chunk in first["chunks"]] == [CHUNK, SECOND_CHUNK]
    assert second["source_ids"] == [ids[c], ids[b]]
    assert [chunk["chunk_id"] for chunk in second["chunks"]] == [b_hit, c_hit]
    assert loads == [b, a, c]
    assert queries == [["Training cost"], ["Inference cost"]]
    indexes = [entry for entry in result.trace if entry["kind"] == "retrieval_index"]
    assert [(entry["source_id"], entry["action"]) for entry in indexes] == [
        (ids[b], "build"),
        (ids[a], "build"),
        (ids[c], "build"),
        (ids[b], "reuse"),
    ]
    assert result.stop_reason == "invalid_citations"
    assert [(ref.chunk_id, ref.title) for ref in result.citations] == [(b_hit, b), (c_hit, c)]


def test_retrieval_with_an_out_of_scope_paper_publishes_no_partial_evidence(tmp_path):
    result = run([retrieve(source=[SOURCE, "2106.09685v1"]), final(CHUNK)], tmp_path)
    assert "error" in observations(result)[0]
    assert result.stop_reason == "invalid_citations"
    assert not result.citations
    assert not any(entry["kind"] == "embedding" for entry in result.trace)


@pytest.mark.parametrize("as_list", [False, True])
def test_retrieve_accepts_opened_unversioned_papers_content_id(tmp_path, as_list):
    source_id = "arxiv:1706.03762@0123456789ab"
    chunk_id = f"{source_id}:p1:c1"
    downloads = []

    def reader(source, **kwargs):
        downloads.append(source)
        parsed = paper(source)
        parsed.update(source_id=source_id, version=None)
        parsed["chunks"][0].update(source_id=source_id, version=None, chunk_id=chunk_id)
        return parsed

    result = run(
        [
            message(calls=[call("open_paper", source="1706.03762")]),
            retrieve(source=[source_id] if as_list else source_id),
            final(chunk_id),
        ],
        tmp_path,
        reader=reader,
        sources=["1706.03762"],
    )
    assert downloads == ["1706.03762"]
    assert result.stop_reason == "completed"
    assert result.citations[0].chunk_id == chunk_id


@pytest.mark.parametrize("source,top_k", [("1706.03762v6", 1), ([], 1), (SOURCE, 0), (SOURCE, 6)])
def test_rejected_retrieval_never_loads_or_embeds_papers(tmp_path, source, top_k):
    calls = []

    def unexpected(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Unexpected paper or embedding request")

    result = run(
        [retrieve(source=source, top_k=top_k), final()],
        tmp_path,
        reader=unexpected,
        embed=unexpected,
    )
    assert "error" in observations(result)[0]
    assert not calls
    assert result.stop_reason == "invalid_citations"


def test_failed_index_can_be_retried_with_same_parsed_paper(tmp_path):
    requests = []
    downloads = []

    def reader(source, **kwargs):
        downloads.append(source)
        return paper(source)

    def flaky_embed(texts, *, purpose, **kwargs):
        if purpose == "document":
            requests.append(list(texts))
            if len(requests) == 1:
                raise RuntimeError("fake-private-credential")
        return embed_texts(texts, purpose=purpose, **kwargs)

    result = run([retrieve(), retrieve(), final()], tmp_path, reader=reader, embed=flaky_embed)
    first, second = observations(result)
    assert "error" in first
    assert result.stop_reason == "completed"
    assert second["chunks"][0]["chunk_id"] == CHUNK
    assert downloads == [SOURCE]
    assert requests == [["Original evidence on page 1."]] * 2
    assert "fake-private-credential" not in result.model_dump_json()
