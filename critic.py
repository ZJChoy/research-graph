"""critic 审稿 + 条件边返工循环。

模型判质量，代码判硬指标（有无引用、长度）。两者都不过就返工，最多 2 轮。
"""
import json
import re

from eval_run import citation_coverage, factual_sentences
from llm import get_llm, invoke

llm = get_llm()

REVIEW_PROMPT = """你是审稿人。以下是调研报告《{topic}》：

{draft}

按三项检查审稿：
1. 引用覆盖率：事实性陈述是否大量缺失 [n] 编号引用
2. 冲突处理：是否存在明显相互矛盾却未说明的陈述
3. 结构完整性：是否覆盖大纲各节、有无未完成的占位符
判分口径（重要）：
- 某节确实没有可用资料时，写「公开资料有限，待补充」是可接受的，不算占位符缺陷；
- 信源数量有限时，如实标注即可，不要要求增加无法获得的来源；
- 不要要求报告给出「建议/责任主体/时间节点」这类规划性内容；
- 只判断报告内部是否自洽、引用是否支撑对应陈述。不要用你自己的外部知识
  判断来源内容是否真实——来源可能滞后或有误，那是来源的问题，不是本报告的问题。

输出 JSON：
{{"pass": true/false, "problems": ["问题1", "问题2"]}}
pass=false 时 problems 必须给出具体可执行的修改意见。只输出 JSON。"""


def _hard_problems(state: dict) -> list:
    """代码级硬检查：引用、长度这些可数的东西不交给模型判断。"""
    draft = state.get("draft", "")
    notes = state.get("research_notes") or []
    total_notes = sum(
        len(g.get("notes", [])) for g in notes if isinstance(g, dict)
    )
    problems = []
    # 只有真的拿到过笔记才要求 [n] 引用；全部调研降级为空时，
    # 报告必然无引用，不该触发返工（返工也补不出引用）
    if total_notes and not re.search(r"\[\d{1,2}\]", draft):
        problems.append("正文没有任何 [n] 引用编号，无法溯源")
    if len(draft) < 300:
        problems.append("报告过短（不足 300 字）")
    # 覆盖率低于目标时，把具体缺引用的句子交给 revise，而不是只说「覆盖率不足」
    if total_notes:
        coverage = citation_coverage(draft)
        if coverage < 0.9:
            missing = [
                s for s in factual_sentences(draft)
                if not re.search(r"\[\d{1,2}\]", s)
            ][:5]
            detail = "；".join(s[:60] for s in missing)
            problems.append(
                f"引用覆盖率 {coverage:.0%} 低于 90%，以下事实句缺少 [n] 引用：{detail}"
            )
    for err in state.get("citation_errors") or []:
        if err.get("type") == "dropped":
            problems.append(
                f"正文引用了不存在的编号 [{err.get('index')}]（可用笔记只有 {total_notes} 条）"
            )
        elif err.get("type") == "unsupported":
            toks = "、".join(err.get("tokens") or [])
            problems.append(
                f"引用与来源不符：句子「{err.get('sentence', '')}」里的 {toks} "
                f"在被引笔记中找不到"
            )
    return problems


def _parse(text: str) -> dict:
    """解析审稿 JSON：先原样解析，剥围栏再试，最后截取最外层大括号兜底。"""
    t = text.strip()
    t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    # 解析失败按不通过处理（带说明），避免格式劣化被「默认放行」掩盖；
    # 返工预算最多 2 轮，不会无限循环
    return {"pass": False, "problems": ["审稿模型输出无法解析为 JSON"]}


def critic(state: dict) -> dict:
    resp = invoke(llm, "critic", REVIEW_PROMPT.format(topic=state["topic"], draft=state["draft"]))
    verdict = _parse(resp.content)
    problems = _hard_problems(state)
    # 交付判定只认代码能数的东西；模型意见单独留档，作为建议而非门槛
    verdict["hard_problems"] = problems
    verdict["blocking"] = bool(problems)
    if problems:
        verdict = {
            "pass": False,
            "problems": problems + list(verdict.get("problems") or []),
            "hard_problems": problems,
            "blocking": True,
        }

    revision = state.get("revision_count", 0)
    if verdict.get("pass") or revision >= 2:
        return {"review_report": verdict, "revision_count": revision}
    return {"review_report": verdict, "revision_count": revision + 1}


def route_after_critic(state: dict) -> str:
    """硬问题（代码可判）返工到预算用尽；模型意见最多触发一轮返工。

    结束时进 code_clean 而不是直接 END：最后一版若仍有无出处句子，
    由代码删掉再交付。
    """
    report = state.get("review_report", {})
    revision = state.get("revision_count", 0)
    if revision >= 2:
        return "clean"
    if report.get("blocking"):
        return "revise"
    if not report.get("pass") and revision <= 1:
        return "revise"
    return "clean"
