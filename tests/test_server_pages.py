from fastapi.testclient import TestClient

import run_store
import server


def _run(rid="20260101-000000-web-test"):
    return {
        "thread_id": "web-test",
        "topic": "测试主题",
        "report": "甲芯片算力达到 128 TOPS[1]。",
        "quality_ok": True,
        "metrics": {"citation_coverage": 1.0, "source_diversity": 1,
                    "source_pages": 1, "conflict_total": 0,
                    "conflict_handled": None, "dangling_citations": [],
                    "fact_statements": 1},
        "final_notes": [{
            "url": "https://example.com/a", "source_title": "示例来源",
            "fact": "甲芯片算力达到 128 TOPS", "tier": "official",
            "published": 2026, "corroborated": True,
        }],
        "source_quality": {"total_sources": 1, "corroborated": 1,
                           "tiers": {"official": 1}},
        "conflicts": [],
        "claim_verification": [
            {"sentence": "甲芯片算力达到 128 TOPS[1]。",
             "verdict": "supported", "reason": "一致"},
        ],
        "claim_verify_summary": {"total": 1, "supported": 1, "partial": 0,
                                 "unsupported": 0, "unverified": 0},
        "llm_usage": {"total": {"calls": 3, "input_tokens": 100,
                                "output_tokens": 50, "seconds": 1.0}},
        "review_report": {"pass": True},
    }


def test_runs_index_and_detail(monkeypatch, workdir):
    monkeypatch.setattr(run_store, "RUNS_DIR", workdir / "runs")
    rid = run_store.save(_run())
    client = TestClient(server.app)

    index = client.get("/runs")
    assert index.status_code == 200
    assert "测试主题" in index.text
    assert rid in index.text

    detail = client.get(f"/runs/{rid}")
    assert detail.status_code == 200
    assert "来源与引用" in detail.text
    assert "官方/机构" in detail.text
    assert "多源印证" in detail.text
    assert "supported" in detail.text

    assert client.get("/runs/does-not-exist").status_code == 404


def test_empty_runs_page(monkeypatch, workdir):
    monkeypatch.setattr(run_store, "RUNS_DIR", workdir / "empty")
    assert "还没有运行记录" in TestClient(server.app).get("/runs").text


def test_cancel_when_idle():
    r = TestClient(server.app).post("/cancel")
    assert r.json()["ok"] is False