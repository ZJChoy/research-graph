"""M1 最小图：planner -> writer。验收：demo 主题出 500 字草稿。"""
from langgraph.graph import StateGraph, END
from state import ResearchState
from llm import get_llm

llm = get_llm()

def planner(state: ResearchState) -> dict:
    """节点 1：把主题拆成大纲（M3 会加 interrupt 人工确认）。"""
    resp = llm.invoke(
        f"你是调研规划专家。主题：{state['topic']}。\n"
        "请输出一份 4-6 节的调研大纲（Markdown 二级标题列表），"
        "每节一句话说明要查什么。只输出大纲本身。"
    )
    return {"outline": resp.content}

def writer(state: ResearchState) -> dict:
    """节点 2：按大纲写草稿。M2 会升级为带引用的成稿。"""
    resp = llm.invoke(
        f"主题：{state['topic']}\n大纲：\n{state['outline']}\n\n"
        "请按大纲写一篇 500 字左右的中文调研草稿（背景知识写作，无需检索）。"
    )
    return {"draft": resp.content, "revision_count": 0}

def build():
    g = StateGraph(ResearchState)
    g.add_node("planner", planner)
    g.add_node("writer", writer)
    g.set_entry_point("planner")
    g.add_edge("planner", "writer")
    g.add_edge("writer", END)
    return g.compile()

if __name__ == "__main__":
    app = build()
    result = app.invoke({"topic": "端侧 AI 芯片格局（2025-2026）"})
    print("===== 大纲 =====")
    print(result["outline"])
    print("===== 草稿 =====")
    print(result["draft"])

"""M1 模块 3：planner -> [interrupt 人工确认大纲] -> writer。

新增概念：interrupt（人机协同）+ Command(resume) + MemorySaver。
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from state import ResearchState
from llm import get_llm

llm = get_llm()
checkpointer = MemorySaver()


def planner(state: ResearchState) -> dict:
    resp = llm.invoke(
        f"你是调研规划专家。主题：{state['topic']}。\n"
        "请输出一份 4-6 节的调研大纲（Markdown 二级标题列表），"
        "每节一句话说明要查什么。只输出大纲本身。"
    )
    return {"outline": resp.content}


def human_review(state: ResearchState) -> dict:
    """人机协同节点：暂停等人工确认；输入修改意见则让模型改大纲。"""
    feedback = interrupt(
        {"question": "请确认调研大纲", "outline": state["outline"],
         "hint": "直接回车=通过；输入文字=按你的意见修改大纲"}
    )
    if isinstance(feedback, dict) and feedback.get("type") == "continue":
        return {}                       # 人工放行，大纲不动
    # 否则 feedback 是修改意见字符串，让模型按意见重写大纲
    resp = llm.invoke(
        f"主题：{state['topic']}\n原大纲：\n{state['outline']}\n\n"
        f"人工修改意见：{feedback}\n\n请输出修改后的完整大纲（Markdown），只输出大纲本身。"
    )
    return {"outline": resp.content}


def writer(state: ResearchState) -> dict:
    resp = llm.invoke(
        f"主题：{state['topic']}\n大纲：\n{state['outline']}\n\n"
        "请按大纲写一篇 500 字左右的中文调研草稿。"
    )
    return {"draft": resp.content, "revision_count": 0}


def build():
    g = StateGraph(ResearchState)
    g.add_node("planner", planner)
    g.add_node("human_review", human_review)
    g.add_node("writer", writer)
    g.set_entry_point("planner")
    g.add_edge("planner", "human_review")
    g.add_edge("human_review", "writer")
    g.add_edge("writer", END)
    return g.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    app = build()
    cfg = {"configurable": {"thread_id": "demo-1"}}
    topic = "端侧 AI 芯片格局（2025-2026）"

    # 第一次 invoke：跑到 interrupt 暂停
    result = app.invoke({"topic": topic}, config=cfg)
    task = result.get("__interrupt__")
    if task:
        payload = task[0].value if isinstance(task, list) else task.value
        print("===== 等你确认大纲 =====")
        print(payload["outline"])
        answer = input("\n直接回车=通过；输入修改意见=改大纲：> ").strip()
        if answer == "":
            resume = Command(resume={"type": "continue"})
        else:
            resume = Command(resume=answer)
        result = app.invoke(resume, config=cfg)

    print("===== 最终大纲 =====")
    print(result["outline"])
    print("\n===== 草稿 =====")
    print(result["draft"])

