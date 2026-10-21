import source_quality as sq


def test_domain_tiers():
    assert sq.tier("https://www.qualcomm.com/automotive/x") == "official"
    assert sq.tier("https://www.idc.com/resource-center/blog/x") == "official"
    assert sq.tier("https://www.eet-china.com/mp/a496467.html") == "media"
    assert sq.tier("https://www.sohu.com/a/123") == "blog"
    assert sq.tier("https://example.org/a") == "unknown"
    assert sq.tier("not a url") == "unknown"


def test_published_year_prefers_latest():
    assert sq.published_year("发布于2024年3月，更新于2025-06") == 2025
    assert sq.published_year("没有日期") is None


def test_corroboration_requires_independent_domain_and_distinctive_token():
    notes = [
        {"fact": "寒武纪 MLU370-S 的算力为 256 TOPS", "url": "https://a.com/x"},
        {"fact": "寒武纪 MLU370-S 已量产", "url": "https://b.com/y"},
        {"fact": "另一款芯片算力为 45 TOPS", "url": "https://c.com/z"},
    ]
    corr = sq.corroboration(notes)
    assert corr[0] is True and corr[1] is True
    assert corr[2] is False


def test_same_domain_is_not_corroboration():
    notes = [
        {"fact": "寒武纪 MLU370-S 的算力为 256 TOPS", "url": "https://a.com/1"},
        {"fact": "寒武纪 MLU370-S 已量产", "url": "https://a.com/2"},
    ]
    assert sq.corroboration(notes) == [False, False]


def test_annotate_and_summarize():
    notes = [
        {"fact": "MLU370-S 算力 256 TOPS", "url": "https://a.com/x"},
        {"fact": "MLU370-S 已量产", "url": "https://b.com/y"},
        {"fact": "一款芯片算力 45 TOPS", "url": "https://sohu.com/z"},
    ]
    annotated = sq.annotate(notes)
    assert annotated[0]["tier"] == "unknown"
    assert annotated[2]["tier"] == "blog"
    summary = sq.summarize(annotated)
    assert summary["total_sources"] == 3
    assert summary["corroborated"] == 2
    assert summary["tiers"]["blog"] == 1
