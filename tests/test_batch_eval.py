import batch_eval


def _row(topic, coverage, dangling=(), conflicts=0, ok=True):
    return {
        "topic": topic,
        "ok": ok,
        "chars": 1000,
        "elapsed_s": 10.0,
        "metrics": {
            "citation_coverage": coverage,
            "source_diversity": 4,
            "source_pages": 5,
            "conflict_total": conflicts,
            "dangling_citations": list(dangling),
            "targets_met": True,
            "quality_ok": True,
        },
        "blocking": False,
        "source_quality": {"corroborated": 2, "total_sources": 5},
    }


def test_summary_aggregates_and_ignores_failures():
    rows = [
        _row("a", 0.9),
        _row("b", 1.0, dangling=[3]),
        {"topic": "c", "ok": False, "error": "boom", "elapsed_s": 5.0},
    ]
    s = batch_eval.summarize(rows)
    assert s["n"] == 3 and s["ok"] == 2
    assert s["coverage_mean"] == 0.95
    assert s["coverage_min"] == 0.9
    assert s["dangling_total"] == 1


def test_render_marks_failed_topic():
    rows = [_row("a", 0.9), {"topic": "b", "ok": False, "error": "timeout", "elapsed_s": 1.0}]
    text = batch_eval.render(rows, batch_eval.summarize(rows))
    assert "| a |" in text
    assert "失败：timeout" in text
    assert "完成 1/2" in text
