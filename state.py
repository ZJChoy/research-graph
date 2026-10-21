"""全图共享的 State 定义：所有节点读写这一张状态表。"""
from typing import TypedDict

class ResearchState(TypedDict):
    topic: str                      # 用户给的主题
    outline: str                    # planner 产出的大纲（Markdown）
    draft: str                      # writer 产出的草稿
    revision_count: int             # writer 重写次数（M3 用）

