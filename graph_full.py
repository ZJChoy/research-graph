"""全图装配：planner → interrupt → Send 并行调研 → 核查 → 写作 → critic 环。

修复点（2026-10-22）：
1. StateGraph 用 GraphState（带 research_notes reducer），并行写入才不冲突；
2. SqliteSaver 用 sqlite3 连接构造（from_conn_string 返回的是上下文管理器）；
3. 去掉占位节点，human_review 直接条件边返回 Send 列表做 Map-Reduce。
"""
import json
import re
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Send, interrupt

from critic import critic, route_after_critic
from fact_checker import check_all
import source_quality
from grounding import audit_draft, autocite, mark_inferences, strip_unsupported
from llm import get_llm
from researcher import research_one
from sources import cited_indices, conflict_appendix, finalize_report
from state_full import GraphState

llm = get_llm()


def planner(state: dict) -> dict:
    resp = llm.invoke(
        f"你是调研规划专家。主题：{state['topic']}。\n"
        "请输出一份 4-6 节的调研大纲（Markdown 二级标题列表），"
        "每节一句话说明要查什么。只输出大纲本身。"
    )
    return {"outline": resp.content}


def human_review(state: dict) -> dict:
    feedback = interrupt({
        "question": "请确认调研大纲",
        "outline": state["outline"],
        "hint": "直接回车=通过；输入文字=按你的意见修改大纲",
    })
    if isinstance(feedback, dict) and feedback.get("type") == "continue":
        return {}
    if not isinstance(feedback, str) or not feedback.strip():
        return {}
    resp = llm.invoke(
        f"主题：{state['topic']}\n原大纲：\n{state['outline']}\n\n"
        f"人工修改意见：{feedback}\n\n请输出修改后的完整大纲（Markdown），只输出大纲本身。"
    )
    return {"outline": resp.content}


def parse_subtasks(outline: str) -> list:
    """从大纲提取子问题，去掉「一、」这类中文序号——序号进搜索词会显著降低命中。"""
    subs = []
    for line in outline.splitlines():
        line = line.strip()
        if not line.startswith("##"):
            continue
        text = line.lstrip("#").strip()
        text = re.sub(r"^[一二三四五六七八九十0-9]+[、.．)）]\s*", "", text)
        if text:
            subs.append(text)
    return subs


def fan_out_researchers(state: dict):
    """Map 阶段：每个子问题一路 Send，并行调研。"""
    subs = parse_subtasks(state.get("outline", "")) or [state.get("topic", "")]
    topic = state.get("topic", "")
    return [Send("research_one_node", {"subquestion": s, "topic": topic}) for s in subs]


def research_one_node(state: dict) -> dict:
    """Reduce 单元：一路调研，笔记并入总状态（由 reducer 合并）。"""
    return {"research_notes": [research_one(state["subquestion"], state.get("topic"))]}


def fact_checker_node(state: dict) -> dict:
    verdict = check_all(state["topic"], state.get("research_notes", []))
    return {
        "conflicts": verdict.get("conflicts", []),
        "solitary": verdict.get("solitary", []),
    }


def collect_notes(state: dict) -> list:
    """把笔记按来源页面归并：一个 URL 一个编号，笔记事实串在一起。

    按「笔记」编号会让同一篇文章出现 [5][6][12] 三个编号，
    来源表重复、读者也无法判断到底有几个独立信源。
    """
    flat = []
    for group in state.get("research_notes", []):
        for n in group.get("notes", []):
            if (n.get("url") or "") and (n.get("fact") or "").strip():
                flat.append(n)
    corroborated = source_quality.corroboration(flat)

    grouped = {}
    for n, is_corroborated in zip(flat, corroborated):
        url = n.get("url", "")
        fact = (n.get("fact") or "").strip()
        g = grouped.setdefault(url, {
            "url": url,
            "source_title": n.get("source_title", "来源"),
            "tier": n.get("tier") or source_quality.tier(url),
            "published": n.get("published"),
            "corroborated": False,
            "facts": [],
        })
        if is_corroborated:
            g["corroborated"] = True
        # 一个来源最多列 6 条事实：给得太少，writer 会把外部分析补进报告
        if fact not in g["facts"] and len(g["facts"]) < 6:
            g["facts"].append(fact)
    out = []
    for g in grouped.values():
        if not g["facts"]:
            continue
        out.append({
            "url": g["url"],
            "source_title": g["source_title"],
            "fact": "；".join(g["facts"]),
            "tier": g["tier"],
            "published": g["published"],
            "corroborated": g["corroborated"],
        })
    return out


def _note_tag(n: dict) -> str:
    tier = source_quality.LABEL.get(n.get("tier") or "unknown", "未知")
    cross = "多源印证" if n.get("corroborated") else "单一来源"
    year = f" | {n['published']}" if n.get("published") else ""
    return f"{tier}/{cross}{year}"


def _numbered_notes(flat: list) -> str:
    return "\n".join(
        f"[{i + 1}] {n['fact']}（来源: {n['source_title']} | {n['url']} | {_note_tag(n)}）"
        for i, n in enumerate(flat)
    )


def _finalize_only(draft: str, notes: list, conflicts: list | None = None) -> dict:
    """收口报告：剥模型来源表、剔除越界编号、生成唯一来源表与冲突附录。

    这里不做删句：删句会改变正文，会让 critic 之后的 revise 拿到被删过的稿。
    删句只放在最后的 code_clean 里。
    """
    draft = draft or ""
    cut = draft.find("\n## 数据分歧说明")
    if cut >= 0:
        draft = draft[:cut]  # 重写稿可能把上一版附录抄回来，先剥掉再统一生成
    if conflicts:
        # 冲突说明由代码生成：模型只被要求「说明或回避」，但经常两边都抄却不说矛盾
        draft = draft + "\n" + conflict_appendix(conflicts)
    text, meta = finalize_report(draft, notes)
    return {
        "draft": text,
        "citation_meta": meta,
        # 报告里的 [n] 按这个列表编号，审计脚本必须用同一份
        "final_notes": list(notes),
    }


def audit_node(state: dict) -> dict:
    """成稿层接地检查：放在 critic 之后，保证参与审稿的就是被检查的那一版。"""
    errors, warnings = audit_draft(state.get("draft", ""), state.get("final_notes") or [])
    meta = state.get("citation_meta") or {}
    errors = [{"type": "dropped", "index": i} for i in meta.get("dropped", [])] + errors
    return {"citation_errors": errors, "grounding_warnings": warnings}


def code_clean(state: dict) -> dict:
    """最终兜底（END 前）：删掉仍无出处的句子——宁可少一句，也不交付编造数字。

    删除后重新审计一次，用清理后的结果覆盖 citation_errors，
    这样交付判定看到的就是真正交付的那一版。
    """
    draft = state.get("draft", "")
    notes = state.get("final_notes") or []
    meta = state.get("citation_meta") or {}
    # 1) 补引用：漏标但只有一条笔记能覆盖的句子，由代码补编号
    cited, added = autocite(draft, notes)
    if added:
        draft, meta = finalize_report(cited, notes)
    # 2) 删句：仍无确定出处的数字/型号，宁可少一句也不交付
    cleaned, removed = strip_unsupported(draft, notes)
    if removed:
        draft, meta = finalize_report(cleaned, notes)
    # 3) 标推断：无引用也无硬数字的分析句，补上 writer 本该写的「（推断）」
    marked_text, marked = mark_inferences(draft)
    if marked:
        draft, meta = finalize_report(marked_text, notes)
    errors, warnings = audit_draft(draft, notes)
    out = {"draft": draft, "citation_errors": errors, "citation_meta": meta,
           "grounding_warnings": warnings}
    if added:
        out["grounding_warnings"] += [{"autocited_sentences": added}]
    if removed:
        out["grounding_warnings"] += [{"stripped_unsupported_sentences": removed}]
    if marked:
        out["grounding_warnings"] += [{"marked_inferences": marked}]
    return out


def writer(state: dict) -> dict:
    flat = collect_notes(state)
    numbered = _numbered_notes(flat) or "（本次没有检索到可用资料）"
    if flat:
        limit = f"可用编号只有 [1]..[{len(flat)}]，禁止使用范围外的编号。"
    else:
        limit = "没有可用资料，每节只能写「公开资料有限，待补充」，不要编造任何事实。"
    solitary = state.get("solitary") or []
    solitary_text = "\n".join(f"- {s}" for s in solitary[:8]) or "（无）"
    # 篇幅跟着资料量走：笔记少就别硬凑，凑出来的都是没出处的句子
    target = max(600, min(1600, 120 * len(flat)))
    resp = llm.invoke(
        f"主题：{state['topic']}\n大纲：\n{state['outline']}\n\n"
        f"资料笔记：\n{numbered}\n\n"
        f"已发现的矛盾（必须在报告里说明或回避）：\n"
        f"{json.dumps(state.get('conflicts', []), ensure_ascii=False)}\n\n"
        f"孤证（只有单一来源，句末标注「（孤证）」）：\n{solitary_text}\n\n"
        f"任务：按大纲写约 {target} 字中文调研报告。硬性要求：\n"
        "1. 每个含事实的句子末尾标一个编号，如 [3]；一句只讲一个事实，用句号结尾，"
        "不要用分号把多个事实串成一句\n"
        f"2. {limit}数字和型号必须与笔记原文一致，不得改写或补充\n"
        "3. 无资料支撑的判断标注「（推断）」；资料覆盖不到的章节只写「公开资料有限，待补充」\n"
        "4. 不要自己写来源表，代码会按引用编号生成\n"
        "5. 不要写「建议」「下一步」「责任主体」「时间节点」这类规划性内容，只陈述资料里的事实\n"
        "6. 优先采用「官方/机构」与「多源印证」的资料；「自媒体/单一来源」的数字只能作补充，"
        "不要作为整节唯一依据，关键数字句末标注「（孤证）」"
    )
    out = _finalize_only(resp.content, flat, state.get("conflicts"))
    out["revision_count"] = state.get("revision_count", 0)
    return out


def revise(state: dict) -> dict:
    """重写报告。若重写把引用洗没了，保留原稿并结束返工（代码兜底，不信任模型）。"""
    problems = state.get("review_report", {}).get("problems", [])
    citation_errors = state.get("citation_errors") or []
    flat = collect_notes(state)
    old = state.get("draft", "")
    resp = llm.invoke(
        f"以下报告未通过审稿：\n{old}\n\n"
        f"审稿意见：{json.dumps(problems, ensure_ascii=False)}\n\n"
        f"可用资料笔记（编号只能用到 [{len(flat)}]）：\n{_numbered_notes(flat)}\n\n"
        f"上一版的引用问题（必须逐条修正）：\n"
        f"{json.dumps(citation_errors, ensure_ascii=False)}\n\n"
        "请只输出修改后的报告正文：不要写修改说明、不要列改动清单、不要以「✅」开头；"
        "不要写「建议」「下一步」「责任主体」「时间节点」这类规划性内容。"
        "只使用上面列出的编号；数字和型号必须与笔记一致；不要自己写来源表。"
        "没有把握的地方宁可删掉该陈述，也不要保留无出处的数字。"
    )
    new = resp.content
    old_cites = len(cited_indices(old))
    new_cites = len(cited_indices(new))
    if old_cites and new_cites < max(1, old_cites // 2):
        # 重写导致引用大幅丢失：弃用新稿，保留原稿并把返工预算判满，避免来回空转
        out = _finalize_only(old, flat, state.get("conflicts"))
        out["revision_count"] = 2
        return out
    return _finalize_only(new, flat, state.get("conflicts"))


def build(db_path: str = "checkpoints.sqlite"):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    saver = SqliteSaver(conn)

    g = StateGraph(GraphState)
    g.add_node("planner", planner)
    g.add_node("human_review", human_review)
    g.add_node("research_one_node", research_one_node)
    g.add_node("fact_checker_node", fact_checker_node)
    g.add_node("writer", writer)
    g.add_node("audit", audit_node)
    g.add_node("critic", critic)
    g.add_node("revise", revise)
    g.add_node("code_clean", code_clean)

    g.set_entry_point("planner")
    g.add_edge("planner", "human_review")
    g.add_conditional_edges("human_review", fan_out_researchers, ["research_one_node"])
    g.add_edge("research_one_node", "fact_checker_node")
    g.add_edge("fact_checker_node", "writer")
    g.add_edge("writer", "audit")
    g.add_edge("audit", "critic")
    g.add_conditional_edges("critic", route_after_critic, {"revise": "revise", "clean": "code_clean"})
    g.add_edge("revise", "audit")
    g.add_edge("code_clean", END)

    app = g.compile(checkpointer=saver)
    # 把连接挂到 app 上，调用方（server/run_cli）跑完可以 close，避免连接泄漏
    app._sqlite_conn = conn
    return app
