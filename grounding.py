"""引用接地检查：句子里的数字/型号是否真的出现在被引来源里。

设计取舍：
- 数字和英文型号做成硬检查（可精确比对，误杀少）；
- 中文措辞的二元词重合度只做软警告（模型会改写，硬判会误杀）；
- 引用编号本身不算事实 token，先剥掉再比对。
"""
import re

from sources import split_bibliography

_CITE = re.compile(r"\[(?:\d{1,2}|[Ss]\d+)\]")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}")
_STOP = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "has", "have"}


def _norm_num(s: str) -> str:
    return s.replace(",", "")


def numeric_tokens(text: str) -> set:
    """独立出现的两位以上数字（含小数、千分位）。

    嵌在字母里的数字（FP16 的 16、MLU370 的 370）属于型号的一部分，
    交给 key_tokens 的型号 token 整体比对，不单独算一次断言。
    """
    t = _CITE.sub(" ", text or "")
    out = set()
    for m in re.finditer(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*(?![A-Za-z0-9])", t):
        v = _norm_num(m.group(0))
        if len(v.replace(".", "")) >= 2:
            out.add(v)
    return out


def key_tokens(text: str) -> set:
    """数字 + 英文/型号 token（TOPS、Gen4、MLU370、QCT-TP-...）。"""
    t = _CITE.sub(" ", text or "")
    out = numeric_tokens(text)
    for m in _TOKEN.findall(t):
        if any(c.isalpha() for c in m) and m.lower() not in _STOP:
            out.add(m.lower())
    return out


def _support_index(supports: list) -> tuple:
    toks = set()
    for s in supports:
        toks |= key_tokens(s)
    # 去掉所有空白后的全文：让「128 TOPS」和「128TOPS」这类排版差异不算错误
    blob = re.sub(r"\s+", "", " ".join(str(s) for s in supports)).lower()
    return toks, blob


def unsupported_tokens(claim: str, supports: list) -> list:
    """claim 里出现、但所有 support 文本里都没有的 token。"""
    claim_tokens = key_tokens(claim)
    if not claim_tokens:
        return []
    support_tokens, blob = _support_index(supports)
    return sorted(t for t in claim_tokens - support_tokens if t not in blob)


_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def critical_tokens(claim: str, supports: list) -> list:
    """只保留「数字 / 型号」这类硬证据：普通英文缩写（NPU、IDC）会误杀改写句。

    年份（2025、2026）单独排除：报告标题、时间状语里到处都是，
    而被引笔记通常只写「2025 年量产」中的一处，逐token比对会把正常句子判死。
    """
    out = []
    for t in unsupported_tokens(claim, supports):
        if not re.search(r"\d", t):
            continue
        if _YEAR.match(t) or "/" in t:  # 年份与 TOPS/W、INT4/FP16 这类复合单位不算断言
            continue
        out.append(t)
    return out


def unsupported_numbers(claim: str, supports: list) -> list:
    """抽取层用：只查数字，避免中英文译名（骁龙/Snapdragon）造成误杀。"""
    claim_nums = numeric_tokens(claim)
    if not claim_nums:
        return []
    support_nums = set()
    for s in supports:
        support_nums |= numeric_tokens(s)
    return sorted(claim_nums - support_nums)


def _bigrams(text: str) -> set:
    clean = re.sub(r"[^一-龥a-zA-Z0-9]", "", _CITE.sub("", text or ""))
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def bigram_recall(claim: str, supports: list) -> float:
    """句子里的中文二元词有多大比例出现在来源里（改写容忍度指标）。"""
    q = _bigrams(claim)
    if len(q) < 4:
        return 1.0
    s = set()
    for x in supports:
        s |= _bigrams(x)
    return len(q & s) / len(q)


def split_sentences(text: str) -> list:
    """正文切句：句号/问号/叹号/分号/换行都算边界，跳过标题、表格、来源行。"""
    body, _ = split_bibliography(text)
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or re.match(r"^\[\d+\]", s):
            continue
        lines.append(s)
    out = []
    for part in re.split(r"(?<=[。！？；])|\n", "\n".join(lines)):
        part = part.strip().lstrip("-*").strip()
        if part:
            out.append(part)
    return out


def cited_in(sentence: str) -> list:
    return sorted({int(m) for m in re.findall(r"\[(\d{1,2})\]", sentence)})


def strip_unsupported(draft: str, notes: list) -> tuple[str, int]:
    """删掉「数字/型号在被引笔记里找不到」的句子。

    返工预算用尽后的最后一道闸：宁可少一句，也不交付无出处的数字。
    返回 (清理后的正文, 删除句数)。
    """
    body, _ = split_bibliography(draft)
    # 代码生成的冲突附录不是正文断言，原样保留
    appendix = ""
    cut = body.find("\n## 数据分歧说明")
    if cut >= 0:
        body, appendix = body[:cut], body[cut:]
    all_supports = [str(n.get("fact", "")) for n in notes]
    out_lines, removed = [], 0
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or re.match(r"^\[\d+\]", s):
            out_lines.append(line)
            continue
        kept = []
        for part in re.split(r"(?<=[。！？；])", line):
            cites = [i for i in cited_in(part) if 1 <= i <= len(notes)]
            supports = [str(notes[i - 1].get("fact", "")) for i in cites] if cites else all_supports
            if critical_tokens(part, supports):
                removed += 1
                continue
            kept.append(part)
        if kept:
            out_lines.append("".join(kept))
    return ("\n".join(out_lines).strip() + appendix), removed


def audit_draft(draft: str, notes: list, bigram_min: float = 0.2) -> tuple[list, list]:
    """成稿层审计：返回 (硬错误, 软警告)。

    硬错误 = 带引用的句子里出现了被引笔记里没有的数字/型号；
    软警告 = 句子与被引笔记的二元词重合度过低（可能是改写，也可能是跑题）。
    """
    errors, warnings = [], []
    for sent in split_sentences(draft):
        cites = [i for i in cited_in(sent) if 1 <= i <= len(notes)]
        if not cites:
            continue
        supports = [str(notes[i - 1].get("fact", "")) for i in cites]
        bad = critical_tokens(sent, supports)
        if bad:
            errors.append({
                "sentence": sent[:120],
                "citations": cites,
                "tokens": bad,
            })
            continue
        other = [t for t in unsupported_tokens(sent, supports) if t not in bad]
        if len(sent) >= 12:
            recall = bigram_recall(sent, supports)
            if recall < bigram_min or other:
                warnings.append({
                    "sentence": sent[:120],
                    "citations": cites,
                    "bigram_recall": round(recall, 2),
                    "tokens": other,
                })
    return errors, warnings
