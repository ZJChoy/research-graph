import grounding


NOTES = [{"fact": "地平线征程6芯片算力达到128 TOPS，2025年量产"}]


def test_numeric_tokens_ignore_single_digits_and_citation_numbers():
    toks = grounding.numeric_tokens("[1] 2025年 8 Gen4 41.2 TOPS")
    assert "2025" in toks
    assert "41.2" in toks
    assert "8" not in toks
    assert "1" not in toks


def test_key_tokens_include_model_names():
    toks = grounding.key_tokens("高通骁龙8 Gen4 与 MLU370-S")
    assert "gen4" in toks
    assert "mlu370-s" in toks


def test_unsupported_tokens_match_and_mismatch():
    assert grounding.unsupported_tokens("算力达到128 TOPS[1]", [NOTES[0]["fact"]]) == []
    bad = grounding.unsupported_tokens("算力达到100 TOPS[1]", [NOTES[0]["fact"]])
    assert "100" in bad


def test_years_and_composite_units_are_not_hard_failures():
    facts = [NOTES[0]["fact"]]
    assert grounding.critical_tokens("2025–2026年算力达到 128 TOPS[1]", facts) == []
    assert grounding.critical_tokens("能效比以 TOPS/W、INT4/FP16 衡量[1]", facts) == []


def test_only_number_and_model_tokens_are_hard_failures():
    facts = [NOTES[0]["fact"]]
    # 普通缩写不算硬错误，避免改写句被误杀
    assert grounding.critical_tokens("该芯片的 NPU 算力达到 128 TOPS[1]", facts) == []
    # 型号里的数字算硬错误（作为型号 token 整体比对）
    assert grounding.critical_tokens("该芯片为 MLU370-S[1]", facts) == ["mlu370-s"]


def test_split_sentences_treats_semicolon_as_boundary():
    sents = grounding.split_sentences("甲；乙。丙\n丁")
    assert sents == ["甲；", "乙。", "丙", "丁"]


def test_audit_draft_flags_unsupported_sentence():
    draft = "地平线征程6芯片算力达到128 TOPS[1]。它还有512 TOPS的版本[1]。"
    errors, warnings = grounding.audit_draft(draft, NOTES)
    assert len(errors) == 1
    assert "512" in errors[0]["tokens"]


def test_audit_draft_passes_supported_sentence():
    draft = "地平线征程6芯片算力达到128 TOPS[1]。"
    errors, warnings = grounding.audit_draft(draft, NOTES)
    assert errors == []


def test_autocite_adds_citation_when_exactly_one_note_matches():
    notes = [{"fact": "地平线征程6芯片算力达到128 TOPS"}]
    text, added = grounding.autocite("地平线征程6芯片算力达到128 TOPS。", notes)
    assert added == 1
    assert "[1]" in text


def test_autocite_skips_ambiguous_and_uncitable_sentences():
    notes = [
        {"fact": "甲芯片算力达到128 TOPS"},
        {"fact": "乙芯片算力达到128 TOPS"},
    ]
    text, added = grounding.autocite("某芯片算力达到128 TOPS。", notes)
    assert added == 0 and "[1]" not in text
    text, added = grounding.autocite("行业正在快速演进。", notes)
    assert added == 0


def test_autocite_leaves_appendix_alone():
    notes = [{"fact": "甲芯片算力达到128 TOPS"}]
    draft = "正文[1]。\n\n## 数据分歧说明\n\n1. 甲称128 TOPS。"
    text, added = grounding.autocite(draft, notes)
    assert added == 0
    assert text.endswith("1. 甲称128 TOPS。")


def test_strip_unsupported_removes_only_bad_sentence():
    notes = [{"fact": "甲芯片算力 100 TOPS"}]
    cleaned, removed = grounding.strip_unsupported("甲芯片算力 100 TOPS[1]。乙芯片算力 999 TOPS[1]。", notes)
    assert "100 TOPS" in cleaned
    assert "999" not in cleaned
    assert removed == 1


def test_strip_removes_uncited_sentence_with_numbers():
    notes = [{"fact": "甲芯片算力 100 TOPS"}]
    cleaned, removed = grounding.strip_unsupported("行业规模达到 500 亿元。", notes)
    assert cleaned == "" and removed == 1


def test_mark_inferences_only_marks_uncited_analysis():
    draft = "行业正在从功能增强走向架构重构。芯片算力达到 100 TOPS。这是个已经标注（推断）的判断。"
    text, marked = grounding.mark_inferences(draft)
    assert text.startswith("行业正在从功能增强走向架构重构（推断）。")
    assert "100 TOPS（推断）" not in text
    assert marked == 1
