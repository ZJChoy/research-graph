import eval_run


REPORT = """## 标题
某芯片算力达到 100 TOPS[1]；另一款达到 85 TOPS[2]；第三款算力为 60 TOPS 却没有引用。
[1] A - https://a.com/1
[2] B - https://b.com/2
"""


def test_semicolon_counts_as_sentence_boundary():
    sents = eval_run.factual_sentences(REPORT)
    assert len(sents) == 3
    assert eval_run.citation_coverage(REPORT) == round(2 / 3, 3)


def test_conflict_unverified_when_no_conflicts():
    assert eval_run.conflict_handled_rate(REPORT, []) is None
    result = eval_run.evaluate(REPORT, [], 0)
    assert result["conflict_verified"] is False
    assert result["targets_met"] is False


def test_conflict_rate_counts_matched_pairs():
    conflicts = [{"a": "100 TOPS", "b": "85 TOPS", "issue": "算力不一致"}]
    assert eval_run.conflict_handled_rate(REPORT, conflicts) == 1.0


def test_dangling_citations_detected():
    text = "正文[1][3]。\n\n## 参考来源\n\n[1] A - https://a.com/1"
    assert eval_run.dangling_citations(text) == [3]


def test_quality_rejects_tiny_denominator_even_at_full_coverage():
    one_long_sentence = "芯片算力达到 100 TOPS[1]，" + "并且表现稳定，" * 40 + "值得关注。"
    text = one_long_sentence + "\n\n## 参考来源\n\n[1] A - https://a.com/1"
    result = eval_run.evaluate(text, [], 0)
    assert result["citation_coverage"] == 1.0
    assert result["fact_statements"] < eval_run.MIN_FACT_STATEMENTS
    assert result["quality_ok"] is False


def test_source_diversity_uses_bibliography_only():
    text = "正文提到 https://noise.com/x 但没引用。\n\n## 参考来源\n\n[1] A - https://a.com/1\n[2] B - https://b.com/2"
    assert eval_run.source_domains(text) == ["a.com", "b.com"]
    assert eval_run.source_pages(text) == 2
