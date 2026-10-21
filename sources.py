"""参考来源表：由代码生成，不交给模型。

模型负责写正文和标注 [n]，代码负责把 [n] 映射回真实 URL。
好处：引用编号一定可溯源，来源列表不会漏 URL、不会编造。
"""
import re

# 模型自带的来源小节标题：中文三种写法 + 英文两种，容忍 # / ** / 冒号混排
_BIB_HEAD = re.compile(
    r"(?im)^[\s>*#]*"
    r"(?:参考来源|参考文献|参考资料|引用来源|引用文献|sources?|references?)"
    r"[\s*:：]*$"
)
# 没有标题、直接以 `[n] 标题 - URL` 结尾的模型来源行
_BIB_LINE = re.compile(r"(?m)^\s*\[\d+\]\s+.+https?://")
# 抽取阶段残留的来源编号（[S1]），不是最终引用
_STAGE_CITE = re.compile(r"\[[Ss]\d+\]")
# 模型在正文前写的「修改说明」：✅ 开头的清单、按审稿意见修订……
_META_LINE = re.compile(r"(修改说明|修订说明|根据审稿意见|按审稿意见|本报告已|✅|变更说明)")
_REPORT_HEAD = re.compile(r"(?m)^\s*(?:#{1,6}\s|\*\*[一二三四五六七八九十0-9]+[、.．]|\*\*[^*\n]{2,40}报告\*\*)")


def _strip_preamble(text: str) -> str:
    """剥掉 revise 模型写在报告前的「我改了什么」说明，只留报告正文。"""
    lines = (text or "").splitlines()
    if not _META_LINE.search("\n".join(lines[:10])):
        return text or ""
    for i, line in enumerate(lines):
        if _REPORT_HEAD.match(line) and i > 0:
            return "\n".join(lines[i:]).lstrip()
    return text or ""


def split_bibliography(text: str) -> tuple[str, str]:
    """在最后一个来源标题处切开，返回 (正文, 来源小节)。

    取最后一个标题：模型有时在正文里提到「参考来源」四个字，
    但那行不会是独立标题；多份来源表时以最后一份为准，前面的一并剥掉。
    """
    last = None
    for m in _BIB_HEAD.finditer(text or ""):
        last = m
    if last is None:
        return (text or "").rstrip(), ""
    return (text[: last.start()]).rstrip(), text[last.start():]


def _strip_existing(draft: str) -> str:
    """剥掉模型自带的参考来源小节，避免与代码生成的来源表重复。"""
    body, _ = split_bibliography(draft)
    # 没有标题但结尾堆了一串 `[n] 标题 - URL` 的，也一并剥掉
    lines = body.splitlines()
    while lines and (_BIB_LINE.match(lines[-1]) or not lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).rstrip()


def cited_indices(draft: str) -> list:
    """正文里出现过的引用编号（已剥掉来源小节）。"""
    body, _ = split_bibliography(draft)
    return sorted({int(m) for m in re.findall(r"\[(\d{1,2})\]", _STAGE_CITE.sub("", body))})


def bibliography_indices(text: str) -> list:
    """来源小节里列出的编号。"""
    _, bib = split_bibliography(text)
    return sorted({int(m) for m in re.findall(r"(?m)^\s*\[(\d{1,2})\]", bib)})


def conflict_appendix(conflicts: list) -> str:
    """把核查出的冲突整理成正文附录：由代码生成，不交给模型转述。"""
    if not conflicts:
        return ""
    lines = ["", "## 数据分歧说明", "",
             "以下资料之间存在不一致，本报告如实并列，未做取舍：", ""]
    for i, c in enumerate(conflicts, 1):
        a = str(c.get("a", "")).strip()
        b = str(c.get("b", "")).strip()
        issue = str(c.get("issue", "")).strip()
        lines.append(f"{i}. {a}")
        lines.append(f"   与之不一致：{b}")
        if issue:
            lines.append(f"   分歧点：{issue}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def finalize_report(draft: str, notes: list) -> tuple[str, dict]:
    """把模型稿收口成可交付报告：清理残留编号、剔除越界引用、生成唯一来源表。

    返回 (报告正文, meta)。meta 里的 dropped 是正文出现过但笔记里不存在的编号，
    调用方应把它当作审稿硬问题——静默丢弃会让读者看到无出处的 [34]。
    """
    body = _strip_existing(_STAGE_CITE.sub("", _strip_preamble(draft or "")))
    if not notes:
        return body, {"cited": [], "dropped": [], "model_bib_lines": 0}

    idxs = sorted({int(m) for m in re.findall(r"\[(\d{1,2})\]", body)})
    valid = [i for i in idxs if 1 <= i <= len(notes)]
    dropped = [i for i in idxs if not (1 <= i <= len(notes))]

    # 越界编号从正文里删掉：留着就是一条指向不存在来源的引用
    for i in dropped:
        body = body.replace(f"[{i}]", "")

    if not valid:
        return body, {"cited": [], "dropped": dropped, "model_bib_lines": 0}

    lines = [body, "", "## 参考来源", ""]
    for i in valid:
        n = notes[i - 1]
        lines.append("[%d] %s - %s" % (i, n.get("source_title", "来源"), n.get("url", "")))
    text = "\n".join(lines)
    return text, {
        "cited": valid,
        "dropped": dropped,
        "model_bib_lines": len(_BIB_LINE.findall(draft or "")),
    }


def attach_sources(draft: str, notes: list) -> str:
    """兼容旧调用：只要正文，不要 meta。"""
    return finalize_report(draft, notes)[0]
