import json

import fact_checker


class Msg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, prompt):
        return Msg(self.content)


NOTES = [
    {"fact": "寒武纪 MLU370-S 算力为 256 TOPS", "url": "https://a.com/1", "source_title": "A"},
    {"fact": "寒武纪 MLU370-S 算力为 180 TOPS", "url": "https://b.com/2", "source_title": "B"},
    {"fact": "另一款 MLU590 算力为 256 TOPS", "url": "https://c.com/3", "source_title": "C"},
]


def test_conflict_candidates_find_same_entity_different_numbers():
    cands = fact_checker.conflict_candidates(NOTES)
    assert cands
    assert "mlu370s" in cands[0]["issue"]
    assert {cands[0]["a"], cands[0]["b"]} == {NOTES[0]["fact"], NOTES[1]["fact"]}


def test_conflict_candidates_ignore_same_url_and_different_entities():
    same_url = [dict(NOTES[0], url="https://a.com/x"), dict(NOTES[1], url="https://a.com/y")]
    assert fact_checker.conflict_candidates(same_url) == []
    # MLU370-S vs MLU590 没有共享型号 token
    assert fact_checker.conflict_candidates([NOTES[0], NOTES[2]]) == []


def test_solitary_candidates_only_uncorroborated_numeric_notes():
    notes = [
        {"fact": "甲芯片型号 MLU370-S 算力 100 TOPS", "url": "https://a.com/1"},
        {"fact": "甲芯片型号 MLU370-S 算力 100 TOPS", "url": "https://b.com/2"},
        {"fact": "乙芯片算力 88 TOPS", "url": "https://c.com/3"},
    ]
    out = fact_checker.solitary_candidates(notes)
    assert out == ["乙芯片算力 88 TOPS"]


def test_check_all_parses_confirmed_candidates(monkeypatch):
    verdict = {
        "conflicts": [{"a": NOTES[0]["fact"], "b": NOTES[1]["fact"], "issue": "算力不一致"}],
        "additional_conflicts": [{"a": "甲", "b": "乙", "issue": "模型补充"}],
        "solitary": [],
        "rejected": [{"index": 1, "kind": "solitary", "reason": "非关键数字"}],
    }
    monkeypatch.setattr(fact_checker, "llm", FakeLLM(json.dumps(verdict, ensure_ascii=False)))
    out = fact_checker.check_all("测试", [{"notes": NOTES}])
    assert len(out["conflicts"]) == 2
    by_source = {c["discovered_by"] for c in out["conflicts"]}
    assert by_source == {"code_candidate", "model"}
    assert out["candidate_review"]["confirmed_conflicts"] == 1
    assert out["candidate_review"]["model_additional"] == 1
    assert out["candidate_review"]["rejected"] == 1


def test_entity_normalization_matches_model_name_variants():
    notes = [
        {"fact": "Snapdragon 8 Gen 4 的 NPU 算力为 45 TOPS", "url": "https://a.com/1"},
        {"fact": "骁龙8 Gen4 的 NPU 算力为 60 TOPS", "url": "https://b.com/2"},
    ]
    cands = fact_checker.conflict_candidates(notes)
    assert cands
    assert "gen4" in cands[0]["issue"].lower()


def test_entity_normalization_matches_hyphen_variants():
    notes = [
        {"fact": "MLU370-S 的算力为 256 TOPS", "url": "https://a.com/1"},
        {"fact": "MLU370S 的算力为 180 TOPS", "url": "https://b.com/2"},
    ]
    assert fact_checker.conflict_candidates(notes)


def test_check_all_degrades_to_code_candidates_on_bad_json(monkeypatch):
    monkeypatch.setattr(fact_checker, "llm", FakeLLM("模型没给 JSON"))
    out = fact_checker.check_all("测试", [{"notes": NOTES}])
    assert out["conflicts"] == []
    assert out["candidate_review"]["degraded"] is True
    # 孤证候选仍然保留，不因模型失败而丢
    assert all(isinstance(s, str) for s in out["solitary"])