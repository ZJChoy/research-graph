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


def test_strip_unsupported_removes_only_bad_sentence():
    notes = [{"fact": "甲芯片算力 100 TOPS"}]
    cleaned, removed = grounding.strip_unsupported("甲芯片算力 100 TOPS[1]。乙芯片算力 999 TOPS[1]。", notes)
    assert "100 TOPS" in cleaned
    assert "999" not in cleaned
    assert removed == 1
