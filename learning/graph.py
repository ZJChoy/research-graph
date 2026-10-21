"""M1 最小图：planner -> writer。验收：demo 主题出 500 字草稿。

带人工确认大纲（interrupt）的版本拆到了 graph_interrupt.py，
避免同文件两版互相覆盖模块级名字。
"""
from langgraph.graph import StateGraph, END
from learning.state import ResearchState
from llm import get_llm

llm = get_llm()

def planner(state: ResearchState) -> dict:
    """节点 1：把主题拆成大纲。"""
    resp = llm.invoke(
        f"你是调研规划专家。主题：{state['topic']}。\n"
        "请输出一份 4-6 节的调研大纲（Markdown 二级标题列表），"
        "每节一句话说明要查什么。只输出大纲本身。"
    )
    return {"outline": resp.content}

def writer(state: ResearchState) -> dict:
    """节点 2：按大纲写草稿。"""
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
