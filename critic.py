"""critic 审稿 + 条件边返工循环。

模型判质量，代码判硬指标（有无引用、长度）。两者都不过就返工，最多 2 轮。
"""
import json
import re

from langgraph.graph import END

from llm import get_llm

llm = get_llm()

REVIEW_PROMPT = """你是审稿人。以下是调研报告《{topic}》：

{draft}

按三项检查审稿：
1. 引用覆盖率：事实性陈述是否大量缺失 [n] 编号引用
2. 冲突处理：是否存在明显相互矛盾却未说明的陈述
3. 结构完整性：是否覆盖大纲各节、有无未完成的占位符

输出 JSON：
{{"pass": true/false, "problems": ["问题1", "问题2"]}}
pass=false 时 problems 必须给出具体可执行的修改意见。只输出 JSON。"""


def _hard_problems(state: dict) -> list:
    """代码级硬检查：引用、长度这些可数的东西不交给模型判断。"""
    draft = state.get("draft", "")
    problems = []
    if state.get("research_notes") and not re.search(r"\[\d{1,2}\]", draft):
        problems.append("正文没有任何 [n] 引用编号，无法溯源")
    if len(draft) < 300:
        problems.append("报告过短（不足 300 字）")
    return problems


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"pass": True, "problems": ["审稿解析失败，默认放行"]}


def critic(state: dict) -> dict:
    resp = llm.invoke(REVIEW_PROMPT.format(topic=state["topic"], draft=state["draft"]))
    verdict = _parse(resp.content)
    problems = _hard_problems(state)
    if problems:
        verdict = {
            "pass": False,
            "problems": problems + list(verdict.get("problems") or []),
        }

    revision = state.get("revision_count", 0)
    if verdict.get("pass") or revision >= 2:
        return {"review_report": verdict, "revision_count": revision}
    return {"review_report": verdict, "revision_count": revision + 1}


def route_after_critic(state: dict) -> str:
    """不通过且返工预算未尽 → revise；否则结束。"""
    report = state.get("review_report", {})
    if not report.get("pass") and state.get("revision_count", 0) < 2:
        return "revise"
    return END
