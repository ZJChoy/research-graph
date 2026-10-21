"""参考来源表：由代码生成，不交给模型。

模型负责写正文和标注 [n]，代码负责把 [n] 映射回真实 URL。
好处：引用编号一定可溯源，来源列表不会漏 URL、不会编造。
"""
import re


def _strip_existing(draft: str) -> str:
    return re.sub(r"\n#{1,6}\s*参考来源[\s\S]*$", "", draft).rstrip()


def cited_indices(draft: str) -> list:
    return sorted({int(m) for m in re.findall(r"\[(\d{1,2})\]", draft)})


def attach_sources(draft: str, notes: list) -> str:
    """在报告末尾追加只含被引用条目的来源表。"""
    body = _strip_existing(draft)
    if not notes:
        return body
    idxs = [i for i in cited_indices(body) if 1 <= i <= len(notes)]
    if not idxs:
        return body
    lines = [body, "", "## 参考来源", ""]
    for i in idxs:
        n = notes[i - 1]
        lines.append("[%d] %s - %s" % (i, n.get("source_title", "来源"), n.get("url", "")))
    return "\n".join(lines)
