"""整图离线测试：假 LLM + 假检索，不联网、不花钱。"""
import json

import pytest
from langgraph.types import Command

import critic
import fact_checker
import graph_full
import researcher


PAGE = "地平线征程6芯片算力达到128 TOPS，并于2025年实现量产。"
NOTE_JSON = json.dumps(
    {"notes": [{"fact": "地平线征程6芯片算力达到128 TOPS，2025年量产", "citation": "S1"}]},
    ensure_ascii=False,
)
GOOD_DRAFT = "地平线征程6芯片算力达到128 TOPS，2025年实现量产[1]。" * 12
BAD_DRAFT = GOOD_DRAFT + "另外还有一款未公开的芯片算力达到 999 TOPS[9]。"


class Msg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, router):
        self.router = router

    def invoke(self, prompt):
        return Msg(self.router(prompt))


@pytest.fixture
def wired(monkeypatch):
    def router(prompt):
        if "调研规划专家" in prompt:
            return "## 算力\n## 量产"
        if "任务：按大纲写" in prompt:
            return GOOD_DRAFT
        if "未通过审稿" in prompt:
            return GOOD_DRAFT
        return "{}"

    monkeypatch.setattr(graph_full, "llm", FakeLLM(router))
    monkeypatch.setattr(critic, "llm", FakeLLM(lambda p: '{"pass": true, "problems": []}'))
    monkeypatch.setattr(fact_checker, "llm", FakeLLM(lambda p: '{"conflicts": [], "solitary": []}'))
    monkeypatch.setattr(researcher, "llm", FakeLLM(lambda p: NOTE_JSON))
    monkeypatch.setattr(
        researcher, "retrieve",
        lambda q, topic=None: [{"source_title": "测试来源", "url": "https://example.com/a", "content": PAGE}],
    )


def _run(app, cfg):
    chunks = list(app.stream({"topic": "测试主题"}, config=cfg, stream_mode="updates"))
    assert any("__interrupt__" in c for c in chunks), "应在大纲确认处暂停"
    list(app.stream(Command(resume={"type": "continue"}), config=cfg, stream_mode="updates"))
    return app.get_state(cfg).values


def test_full_graph_offline(wired, workdir):
    app = graph_full.build(str(workdir / "cp.sqlite"))
    try:
        state = _run(app, {"configurable": {"thread_id": "t1"}})
        assert "## 参考来源" in state["draft"]
        assert "[1] 测试来源 - https://example.com/a" in state["draft"]
        assert state["citation_errors"] == []
        assert state["review_report"]["pass"] is True
        assert state["raw_metrics"]["fact_statements"] > 0
        assert state["final_metrics"]["quality_ok"] is True
    finally:
        app._sqlite_conn.close()


def test_out_of_range_citation_triggers_revise(wired, monkeypatch, workdir):
    def router(prompt):
        if "调研规划专家" in prompt:
            return "## 算力\n## 量产"
        if "任务：按大纲写" in prompt:
            return BAD_DRAFT
        if "未通过审稿" in prompt:
            return GOOD_DRAFT
        return "{}"

    monkeypatch.setattr(graph_full, "llm", FakeLLM(router))
    app = graph_full.build(str(workdir / "cp2.sqlite"))
    try:
        state = _run(app, {"configurable": {"thread_id": "t2"}})
        assert "[9]" not in state["draft"]
        assert state["citation_errors"] == []
        assert state["revision_count"] == 1
        assert state["review_report"]["pass"] is True
    finally:
        app._sqlite_conn.close()
