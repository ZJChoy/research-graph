import critic


class Msg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, prompt):
        return Msg(self.content)


def test_parse_plain_fenced_and_noisy_json():
    assert critic._parse('{"pass": true, "problems": []}')["pass"] is True
    assert critic._parse('```json\n{"pass": true}\n```')["pass"] is True
    assert critic._parse('以下是结果：{"pass": false, "problems": ["x"]} 完毕')["pass"] is False


def test_parse_failure_is_not_a_pass():
    verdict = critic._parse("模型没给 JSON")
    assert verdict["pass"] is False


def test_hard_problems_require_citation_when_notes_exist():
    state = {"draft": "很长的正文" * 100, "research_notes": [{"notes": [{"fact": "x"}]}]}
    problems = critic._hard_problems(state)
    assert any("引用" in p for p in problems)


def test_hard_problems_surface_citation_errors():
    state = {
        "draft": "正文[1]" * 100,
        "research_notes": [{"notes": [{"fact": "x"}]}],
        "citation_errors": [
            {"type": "dropped", "index": 9},
            {"type": "unsupported", "sentence": "算力 100 TOPS", "citations": [1], "tokens": ["100"]},
        ],
    }
    problems = critic._hard_problems(state)
    assert any("[9]" in p for p in problems)
    assert any("100" in p for p in problems)


def test_model_pass_is_overridden_by_hard_problems(monkeypatch):
    monkeypatch.setattr(critic, "llm", FakeLLM('{"pass": true, "problems": []}'))
    state = {
        "topic": "t",
        "draft": "正文[1]" * 100,
        "research_notes": [{"notes": [{"fact": "x"}]}],
        "citation_errors": [{"type": "dropped", "index": 9}],
        "revision_count": 0,
    }
    out = critic.critic(state)
    assert out["review_report"]["pass"] is False
