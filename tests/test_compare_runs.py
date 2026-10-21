import compare_runs


def _state(urls, coverage=0.9, dangling=(), blocking=False):
    return {
        "final_notes": [{"url": u} for u in urls],
        "metrics": {
            "citation_coverage": coverage,
            "source_diversity": len(urls),
            "conflict_total": 2,
            "conflict_handled": 1.0,
            "revisions": 1,
            "fact_statements": 20,
            "dangling_citations": list(dangling),
        },
        "review_report": {"blocking": blocking},
    }


def test_compare_reports_source_drift_and_deltas():
    prev = _state(["https://a.com", "https://b.com"], coverage=0.8)
    cur = _state(["https://b.com", "https://c.com"], coverage=0.95)
    r = compare_runs.compare(prev, cur)
    assert r["sources_added"] == ["https://c.com"]
    assert r["sources_removed"] == ["https://a.com"]
    assert r["sources_kept"] == 1
    assert r["deltas"]["citation_coverage"] == 0.15
    assert "覆盖" not in r  # sanity: no stray keys


def test_render_mentions_blocking_and_dangling():
    prev = _state(["https://a.com"], dangling=[9], blocking=True)
    cur = _state(["https://a.com"])
    text = compare_runs.render(compare_runs.compare(prev, cur))
    assert "悬空引用：1 → 0" in text
    assert "有 → 无" in text
