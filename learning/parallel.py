"""M2 模块 4：把 planner 的每个子问题交给并行 researcher（Map-Reduce）。

新增概念：LangGraph 用『一个节点返回 Send 列表』实现动态并行——
子问题数量运行时才知道，所以用 Send 而不是写死的边。
"""
import time
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from learning.state import ResearchState
from learning.notes import ResearchNotes
from researcher import research_one


def spawn_researchers(state: ResearchState):
    """Map 阶段：把大纲的每一节变成一路 Send（每路拿到独立的小状态）。"""
    subs = parse_subtasks(state["outline"])
    return [Send("research_one", {"subquestion": s}) for s in subs]


def parse_subtasks(outline: str) -> list[str]:
    """从大纲 Markdown 里提取子问题（每个 ## 标题一行）。"""
    subs = []
    for line in outline.splitlines():
        line = line.strip()
        if line.startswith("##"):
            subs.append(line.lstrip("# ").strip())
    return subs or [state_topic_fallback(outline)]


def state_topic_fallback(outline: str) -> str:
    return outline[:50]


def research_one_node(state: dict) -> dict:
    """Reduce 阶段的单路：跑一路调研，把笔记并入总状态。

    注意：不能叫 research_one——会覆盖上面 from researcher import 的同名函数，
    导致函数体内自调用、无限递归。
    """
    r = research_one(state["subquestion"])
    return {"research_notes": [r]}


def merge_notes(a: list, b: list | None) -> list:
    """research_notes 的合并策略：各路笔记追加（Send 并行的标准 reducer）。"""
    return list(a) + (b or [])


if __name__ == "__main__":
    # 冒烟：串行跑两个子问题对比并行（真实并行在 graph 里由 Send 触发）
    # research_one 现在返回 dict（{"subquestion", "notes"}），用下标访问
    from researcher import research_one as run_research
    subs = ["地平线征程6 的算力与量产", "高通骁龙 Ride 平台的量产车型"]
    t0 = time.time()
    results = [run_research(s) for s in subs]
    serial = time.time() - t0
    total = sum(len(r["notes"]) for r in results)
    print(f"串行跑 {len(subs)} 路：{serial:.1f}s，共 {total} 条笔记")
    for r in results:
        print(f"== {r['subquestion']} ({len(r['notes'])} 条)")
        for n in r["notes"][:3]:
            print(f"  - {n['fact'][:60]}  [{n['source_title'][:30]}]")

