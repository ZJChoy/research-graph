"""M2 模块 4：结构化调研笔记。

一路 researcher 的产物：针对一个子问题的笔记列表。
每条笔记 = 事实句 + 来源 URL，供 fact_checker 交叉验证、writer 引用。
"""
from pydantic import BaseModel, Field

class Note(BaseModel):
    """一条调研笔记：一个事实 + 它的出处。"""
    fact: str = Field(description="用一句话陈述一个事实，不含评价")
    url: str = Field(description="该事实的来源网页 URL")
    source_title: str = Field(description="来源网页标题")
    confidence: str = Field(default="medium", description="high/medium/low：来源可信度初判")

class ResearchNotes(BaseModel):
    """一个子问题的完整调研产物。"""
    subquestion: str
    notes: list[Note] = Field(default_factory=list)
    def facts(self) -> list[str]:
        return [n.fact for n in self.notes]

