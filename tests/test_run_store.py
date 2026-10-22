import json

import run_store


def test_save_list_get(monkeypatch, workdir):
    monkeypatch.setattr(run_store, "RUNS_DIR", workdir / "runs")
    rid = run_store.save({
        "thread_id": "web-abc12345",
        "topic": "测试主题",
        "report": "正文[1]。",
        "quality_ok": True,
        "metrics": {"citation_coverage": 1.0, "fact_statements": 10},
        "source_quality": {"total_sources": 3},
    })
    assert rid.startswith("20")
    runs = run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["topic"] == "测试主题"
    assert runs[0]["coverage"] == 1.0
    detail = run_store.get(rid)
    assert detail["report"] == "正文[1]。"


def test_get_rejects_path_traversal(monkeypatch, workdir):
    monkeypatch.setattr(run_store, "RUNS_DIR", workdir / "runs2")
    assert run_store.get("../secret") is None
    assert run_store.get("a/b") is None


def test_list_empty_when_no_dir(monkeypatch, workdir):
    monkeypatch.setattr(run_store, "RUNS_DIR", workdir / "missing")
    assert run_store.list_runs() == []