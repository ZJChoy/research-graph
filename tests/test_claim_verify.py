import json

import claim_verify


class Msg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, prompt):
        return Msg(json.dumps(self.payload, ensure_ascii=False))


def test_classify_pairs_maps_results_by_id(monkeypatch):
    payload = {"results": [
        {"id": 1, "verdict": "supported", "reason": "一致"},
        {"id": 2, "verdict": "unsupported", "reason": "数字矛盾"},
    ]}
    monkeypatch.setattr(claim_verify, "llm", FakeLLM(payload))
    out = claim_verify.classify_pairs([
        {"claim": "a", "sources": ["a"]},
        {"claim": "b", "sources": ["b"]},
        {"claim": "c", "sources": ["c"]},
    ])
    assert [x["verdict"] for x in out] == ["supported", "unsupported", "unverified"]


def test_verify_claims_only_checks_cited_high_risk_sentences():
    notes = [{"fact": "甲芯片算力达到 128 TOPS"}]
    draft = (
        "甲芯片算力达到 128 TOPS[1]。"
        "行业正在快速演进。"
        "另一款芯片算力达到 512 TOPS[1]。"
    )
    # 直接测过滤逻辑：只有带引用且高风险的句子会进 items
    import grounding
    selected = [
        s for s in grounding.split_sentences(draft)
        if grounding.cited_in(s) and claim_verify._high_risk(s)
    ]
    assert selected == ["甲芯片算力达到 128 TOPS[1]。", "另一款芯片算力达到 512 TOPS[1]。"]


def test_verify_claims_summary(monkeypatch):
    payload = {"results": [
        {"id": 1, "verdict": "supported", "reason": "ok"},
        {"id": 2, "verdict": "partial", "reason": "范围扩大"},
    ]}
    monkeypatch.setattr(claim_verify, "llm", FakeLLM(payload))
    notes = [{"fact": "甲芯片算力 128 TOPS，2025 年首次量产"}]
    draft = "甲芯片算力 128 TOPS[1]。甲芯片于 2025 年首次量产[1]。"
    detail, summary = claim_verify.verify_claims(draft, notes)
    assert len(detail) == 2
    assert summary["supported"] == 1 and summary["partial"] == 1
    assert summary["unsupported"] == 0