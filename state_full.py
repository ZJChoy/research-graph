"""全图状态：dict 形态 + research_notes 并行合并 reducer。

research_notes 被 Send 并行节点同时写入，必须挂 reducer，否则 LangGraph 抛并发冲突。
"""
from typing import Annotated, TypedDict


def merge_list(old, new):
    """并行写入的合并策略：追加。"""
    return list(old or []) + list(new or [])


class GraphState(TypedDict, total=False):
    topic: str
    outline: str
    research_notes: Annotated[list, merge_list]
    conflicts: list
    solitary: list
    draft: str
    review_report: dict
    revision_count: int
    citation_errors: list       # 越界编号 / 引用与来源不符，critic 硬判不通过
    citation_meta: dict         # finalize_report 的统计（cited/dropped/model_bib_lines）
    grounding_warnings: list    # 二元词重合度偏低等软警告，只记录不返工
    final_notes: list           # 报告 [n] 实际对应的笔记（截断后的编号口径）
