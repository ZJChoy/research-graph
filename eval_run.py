"""评测：四个口径的分数表。

口径（PRD §6）：
- citation_coverage：含事实特征（数字/英文专名）的句子里带 [n] 的比例，目标 >=90%
- source_diversity：来源表里的唯一域名数，目标 >=3
- conflict_handled：冲突在终稿被裁决或标注的比例，目标 100%
- revisions：critic 返工次数（观察项）
"""
import json
import re


def extract_citations(text: str) -> list:
    return [int(m) for m in re.findall(r"\[(\d{1,2})\]", text)]


def factual_sentences(text: str) -> list:
    """挑事实性句子：排除标题与来源行，保留含数字或英文专名的长句。"""
    body_lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("["):
            continue
        body_lines.append(s)
    body = "\n".join(body_lines)
    out = []
    for sent in re.split(r"(?<=[。！？])", body):
        sent = sent.strip()
        if len(sent) < 12 or "推断" in sent:
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
    domains = []
    for m in re.findall(r"https?://([^/\s)]+)", text):
        d = m.removeprefix("www.").split("/")[0]
        if d and d not in domains:
            domains.append(d)
    return domains


def conflict_handled_rate(text: str, conflicts: list) -> float:
    if not conflicts:
        return 1.0
    hit = 0
    for c in conflicts:
        a = str(c.get("a", ""))[:8]
        b = str(c.get("b", ""))[:8]
        if any(w and w in text for w in (a, b)) or "矛盾" in text or "不一致" in text:
            hit += 1
    return round(hit / len(conflicts), 3)


def evaluate(report_text: str, conflicts: list, revisions: int) -> dict:
    result = {
        "citation_coverage": citation_coverage(report_text),
        "source_diversity": len(source_domains(report_text)),
        "conflict_handled": conflict_handled_rate(report_text, conflicts),
        "revisions": revisions,
        "total_citations": len(extract_citations(report_text)),
        "fact_statements": len(factual_sentences(report_text)),
    }
    result["targets_met"] = (
        result["citation_coverage"] >= 0.9
        and result["source_diversity"] >= 3
        and result["conflict_handled"] >= 1.0
    )
    return result


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "demo_report.md"
    text = open(path, encoding="utf-8").read()
    print(json.dumps(evaluate(text, [], 0), ensure_ascii=False, indent=2))
