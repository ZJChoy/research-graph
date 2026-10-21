import sources


NOTES = [
    {"fact": "甲芯片算力 100 TOPS", "source_title": "A", "url": "https://a.com/1"},
    {"fact": "乙芯片算力 85 TOPS", "source_title": "B", "url": "https://b.com/2"},
]


def test_strips_all_bibliography_headings():
    for head in ["## 参考来源", "## 参考文献", "**参考来源**", "参考来源：", "### 参考资料", "## References"]:
        body = sources._strip_existing(f"正文内容。\n\n{head}\n[1] 假来源 - http://x")
        assert "假来源" not in body, head
        assert "正文内容" in body


def test_strips_trailing_bib_lines_without_heading():
    body = sources._strip_existing("正文。\n\n[1] 假来源 - https://x.com/a\n[2] 假来源2 - https://x.com/b")
    assert body == "正文。"


def test_finalize_drops_out_of_range_and_stage_citations():
    text, meta = sources.finalize_report("甲 100 TOPS[1]。乙 85 TOPS[9]。丙[S1]。", NOTES)
    assert "100 TOPS[1]" in text
    assert "[9]" not in text
    assert "[S1]" not in text
    assert meta["cited"] == [1]
    assert meta["dropped"] == [9]


def test_finalize_generates_exactly_one_source_table():
    draft = "甲 100 TOPS[1]。\n\n## 参考文献\n[1] 模型编的 - http://fake"
    text, meta = sources.finalize_report(draft, NOTES)
    assert text.count("## 参考来源") == 1
    assert "模型编的" not in text
    assert "[1] A - https://a.com/1" in text
    assert meta["model_bib_lines"] >= 1


def test_finalize_without_notes_returns_body_only():
    text, meta = sources.finalize_report("正文[1]。\n\n## 参考来源\n[1] x - http://x", [])
    assert text == "正文[1]。"
    assert meta["cited"] == []


def test_strips_revise_preamble():
    draft = (
        "根据审稿意见修订如下：\n"
        "✅ 删除虚假引用\n"
        "✅ 合并重复引用\n\n"
        "**端侧AI芯片报告**\n"
        "甲 100 TOPS[1]。"
    )
    text, _ = sources.finalize_report(draft, NOTES)
    assert text.startswith("**端侧AI芯片报告**")
    assert "审稿意见" not in text
    assert "✅" not in text


def test_conflict_appendix_lists_every_conflict():
    import eval_run
    conflicts = [{"a": "甲芯片 100 TOPS", "b": "乙芯片 58 TOPS", "issue": "算力不一致"}]
    draft = "正文[1]。\n" + sources.conflict_appendix(conflicts)
    text, _ = sources.finalize_report(draft, NOTES)
    assert "数据分歧说明" in text
    assert eval_run.conflict_handled_rate(text, conflicts) == 1.0


def test_cited_indices_ignores_bibliography():
    text = "正文[1]。\n\n## 参考来源\n\n[1] A - https://a.com/1"
    assert sources.cited_indices(text) == [1]
    assert sources.bibliography_indices(text) == [1]
