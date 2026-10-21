"""评测：四个口径的分数表。

口径（PRD §6）：
- citation_coverage：含事实特征（数字/英文专名）的句子里带 [n] 的比例，目标 >=90%
- source_diversity：来源表里的唯一域名数，目标 >=3
- conflict_handled：冲突在终稿被裁决或标注的比例；没有检出冲突时记为「未验证」
- revisions：critic 返工次数（观察项）
- dangling_citations：正文引用编号在来源表里找不到的个数，目标 0
"""
import json
import re

from sources import bibliography_indices, split_bibliography


def extract_citations(text: str) -> list:
    body, _ = split_bibliography(_split_appendix(text))
    return [int(m) for m in re.findall(r"\[(\d{1,2})\]", body)]


def _split_appendix(text: str) -> str:
    """去掉代码生成的「数据分歧说明」附录：它是并列引用，不是正文断言。"""
    cut = text.find("\n## 数据分歧说明")
    return text[:cut] if cut >= 0 else text


def factual_sentences(text: str) -> list:
    """挑事实性句子：排除标题、表格与来源行，保留含数字或英文专名的句子。

    分号也是句子边界。之前只认句号，模型用分号把整段串成一句，
    5224 字的报告只切出 5 个「事实句」，覆盖率被虚高到 100%。
    """
    body, _ = split_bibliography(_split_appendix(text))
    out = []
    for line in body.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("|") or re.match(r"^\[\d+\]", raw):
            continue
        # 标题行：没有句末标点且很短，不是事实陈述
        if len(raw) < 40 and not re.search(r"[。！？；]", raw):
            continue
        for sent in re.split(r"(?<=[。！？；])", raw):
            sent = sent.strip().lstrip("-*").strip()
            if len(sent) < 12 or "推断" in sent:
                continue
            # 「资料没披露 X」是空缺声明，不是需要引用的事实断言
            if "未披露" in sent or "待补充" in sent or "公开资料有限" in sent:
                continue
            if re.search(r"\d", sent) or re.search(r"[A-Za-z]{3,}", sent):
                out.append(sent)
    return out


def citation_coverage(text: str) -> float:
    sentences = factual_sentences(text)
    if not sentences:
        return 0.0
    cited = sum(1 for s in sentences if re.search(r"\[\d{1,2}\]", s))
    return round(cited / len(sentences), 3)


def source_domains(text: str) -> list:
    """来源表里的唯一域名（没有来源表时退回全文 URL）。"""
    _, bib = split_bibliography(text)
    scope = bib or text
    domains = []
    for m in re.findall(r"https?://([^/\s)]+)", scope):
        d = m.removeprefix("www.").split("/")[0]
        if d and d not in domains:
            domains.append(d)
    return domains


def source_pages(text: str) -> int:
    """来源表里的唯一 URL 数（比域名更接近「用了几个页面」）。"""
    _, bib = split_bibliography(text)
    return len(set(re.findall(r"https?://[^\s)]+", bib or text)))


def conflict_handled_rate(text: str, conflicts: list):
    """冲突处理率；没有检出冲突时返回 None（未验证），不再空集给 1.0。"""
    if not conflicts:
        return None
    hit = 0
    for c in conflicts:
        # 按冲突双方内容 + 矛盾点各取前 8 字做匹配。
        # 收紧后偏保守（报告换措辞描述冲突可能漏计），评测宁可低估不虚高。
        keys = [str(c.get(k, ""))[:8] for k in ("a", "b", "issue")]
        if any(w and w in text for w in keys):
            hit += 1
    return round(hit / len(conflicts), 3)


def dangling_citations(text: str) -> list:
    """正文引用了、但来源表里没有的编号。"""
    cited = set(extract_citations(text))
    listed = set(bibliography_indices(text))
    return sorted(cited - listed)


def duplicate_url_indices(text: str) -> dict:
    """指向同一 URL 的多个编号：{url: [编号...]}，只保留重复的。"""
    from sources import split_bibliography
    _, bib = split_bibliography(text)
    by_url = {}
    for i, _, url in re.findall(r"(?m)^\s*\[(\d+)\]\s*(.*?)\s+-\s+(https?://\S+)", bib):
        by_url.setdefault(url, []).append(int(i))
    return {u: ids for u, ids in by_url.items() if len(ids) > 1}


# 报告至少要有这么多事实句，覆盖率才被当作有效证据
MIN_FACT_STATEMENTS = 12


def evaluate(report_text: str, conflicts: list, revisions: int) -> dict:
    conflict_rate = conflict_handled_rate(report_text, conflicts)
    dangling = dangling_citations(report_text)
    result = {
        "citation_coverage": citation_coverage(report_text),
        "source_diversity": len(source_domains(report_text)),
        "source_pages": source_pages(report_text),
        "conflict_handled": conflict_rate,
        "conflict_total": len(conflicts),
        "conflict_verified": bool(conflicts),
        "revisions": revisions,
        "total_citations": len(extract_citations(report_text)),
        "fact_statements": len(factual_sentences(report_text)),
        "dangling_citations": dangling,
    }
    # 严格目标：冲突必须被真实检出并处理
    result["targets_met"] = (
        result["citation_coverage"] >= 0.9
        and result["source_diversity"] >= 3
        and result["conflict_verified"]
        and result["conflict_handled"] >= 1.0
        and not dangling
    )
    # 交付判定：代码可数的硬指标；冲突未检出时如实标「未验证」，不阻塞交付。
    # 分母下限：事实句太少时，1.0 的覆盖率没有统计意义，不能算交付达标。
    result["quality_ok"] = (
        len(report_text) >= 300
        and result["fact_statements"] >= MIN_FACT_STATEMENTS
        and result["citation_coverage"] >= 0.9
        and not dangling
        and (not result["conflict_verified"] or result["conflict_handled"] >= 1.0)
    )
    return result


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "demo_report.md"
    text = open(path, encoding="utf-8").read()
    conflicts = []
    if len(sys.argv) > 2:
        conflicts = json.load(open(sys.argv[2], encoding="utf-8")).get("conflicts", [])
    print(json.dumps(evaluate(text, conflicts, 0), ensure_ascii=False, indent=2))
