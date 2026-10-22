"""M2 模块 5：fact_checker——交叉验证笔记，标记冲突与孤证。

检测分两步：
1. 代码先找候选：同一型号/实体出现不同数字 → 冲突候选；同一组硬数字
   只出现在一个域名 → 孤证候选。候选可解释、可复现，不依赖模型当天状态。
2. 模型逐条确认或否定候选，也可以补充候选之外的冲突——但默认不新增
   无法解释的「凭感觉」冲突。
"""
import json
import re

import source_quality
from grounding import key_tokens, numeric_tokens
from llm import get_llm, invoke

llm = get_llm()

_YEAR = re.compile(r"^(?:19|20)\d{2}$")

CHECK_PROMPT = """你是事实核查员。以下是围绕主题「{topic}」从多个来源抽取的笔记：

{notes}

代码已经生成以下候选，必须逐条判定：

[冲突候选]
{conflict_candidates}

[孤证候选]（同一组数字只出现在一个独立域名）
{solitary_candidates}

任务：
1. 对每条冲突候选，判断它是否真的是「同一对象、同一属性」的矛盾；
   如果只是同一型号的不同属性（算力 vs 功耗），应否定。
2. 对每条孤证候选，判断它是否属于关键数字/关键结论。
3. 你可以在候选之外补充你确信的冲突，但必须给出双方原文。
4. 输出 JSON：
{{"conflicts": [{{"a": "笔记1原文", "b": "笔记2原文", "issue": "矛盾点一句话"}}],
 "additional_conflicts": [{{"a": "笔记1原文", "b": "笔记2原文", "issue": "..."}}],
 "solitary": ["孤证原文", ...],
 "rejected": [{{"index": 1, "kind": "conflict|solitary", "reason": "..."}}]}}
conflicts 只放你确认的代码候选；候选之外自己发现的放 additional_conflicts。
只输出 JSON，没有就输出空数组。"""


def _notes_flat(notes: list) -> list:
    flat = []
    for r in notes:
        if not isinstance(r, dict):
            continue
        for n in (r.get("notes") or []):
            if not isinstance(n, dict):
                continue
            fact = (n.get("fact") or "").strip()
            if fact:
                flat.append({
                    "fact": fact,
                    "source_title": n.get("source_title", ""),
                    "url": n.get("url", ""),
                })
    return flat


_GEN = re.compile(r"gen\s*[-_]?\s*(\d+)", re.I)
_CN_MODEL = re.compile(r"(天玑|骁龙|麒麟|昇腾|思元|征程|玄戒|澎湃)\s*([0-9]{3,4}[A-Za-z]?)")
_EN_MODEL = re.compile(
    r"\b(snapdragon|dimensity|kylin|ascend|cambricon|ryzen|exynos|tensor)"
    r"\s*([0-9]{3,4}[A-Za-z]?)", re.I,
)


def _normalize_fact(fact: str) -> str:
    """只归一「Gen 4」这类写法；不碰「256 TOPS」这种数值+单位。"""
    return _GEN.sub(lambda m: f"gen{m.group(1)}", fact or "")


def _canon(token: str) -> str:
    return token.replace("-", "").replace("_", "").lower()


def _entity_tokens(fact: str) -> list:
    """能标识「同一对象」的型号：Gen4、天玑9400、MLU370-S 等。"""
    text = fact or ""
    out = {f"gen{m.group(1)}" for m in _GEN.finditer(text)}
    out |= {(m.group(1) + m.group(2)).lower() for m in _CN_MODEL.finditer(text)}
    out |= {(m.group(1) + m.group(2)).lower() for m in _EN_MODEL.finditer(text)}
    for t in key_tokens(text):
        if _YEAR.match(t) or "/" in t or not any(c.isdigit() for c in t):
            continue
        if len(t) >= 4:
            out.add(_canon(t))
    return sorted(out)


def _nums(fact: str) -> set:
    return {t for t in numeric_tokens(fact) if not _YEAR.match(t)}


def conflict_candidates(notes: list) -> list:
    """同一型号出现不同数字 → 候选。是否真是同一属性由模型确认。"""
    groups = {}
    for i, n in enumerate(notes):
        for t in set(_entity_tokens(n["fact"])):
            grouped = groups.setdefault(t, {"label": t, "idxs": []})
            grouped["idxs"].append(i)

    seen, out = set(), []
    for key, group in groups.items():
        token, idxs = group["label"], group["idxs"]
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                # 同一域名不算独立来源：同一站点的两篇文章可能是同一套口径
                if source_quality.domain(notes[i].get("url", "")) == \
                        source_quality.domain(notes[j].get("url", "")):
                    continue
                ni, nj = _nums(notes[i]["fact"]), _nums(notes[j]["fact"])
                if not (ni and nj) or ni == nj:
                    continue
                key = tuple(sorted((notes[i]["fact"], notes[j]["fact"])))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "a": notes[i]["fact"],
                    "b": notes[j]["fact"],
                    "issue": f"同一对象 {token} 出现不同数值：{sorted(ni)} vs {sorted(nj)}（可能是不同属性，需确认）",
                    "discovered_by": "code",
                })
    return out[:10]


def solitary_candidates(notes: list) -> list:
    """同一组硬数字只出现在一个独立域名 → 孤证候选。"""
    corr = source_quality.corroboration(notes)
    out = []
    for n, ok in zip(notes, corr):
        if not ok and _nums(n["fact"]):
            out.append(n["fact"])
    return out[:10]


def _parse(text: str) -> dict:
    t = (text or "").strip()
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
    return {}


def check_all(topic: str, notes: list[dict]) -> dict:
    """返回 conflicts / solitary / candidate_review；LLM 失败时降级为只给孤证候选。"""
    flat = _notes_flat(notes)
    if len(flat) < 2:
        return {"conflicts": [], "solitary": [], "candidate_review": {}}

    cc = conflict_candidates(flat)
    sc = solitary_candidates(flat)
    cc_text = "\n".join(
        f"[{i}] {c['a']}\n    与之不一致：{c['b']}\n    线索：{c['issue']}"
        for i, c in enumerate(cc, 1)
    ) or "（无）"
    sc_text = "\n".join(f"[{i}] {s}" for i, s in enumerate(sc, 1)) or "（无）"
    notes_text = "\n".join(f"- {n['fact']}（来源: {n['source_title']}）" for n in flat)

    resp = invoke(llm, "fact_checker", CHECK_PROMPT.format(
        topic=topic, notes=notes_text,
        conflict_candidates=cc_text, solitary_candidates=sc_text,
    ))
    data = _parse(resp.content)
    if not data:
        print("[fact_checker] JSON 解析失败，保留代码候选中的孤证")
        return {
            "conflicts": [],
            "solitary": sc,
            "candidate_review": {"conflicts": len(cc), "solitary": len(sc),
                                 "confirmed": 0, "degraded": True},
        }

    confirmed = [
        {**c, "discovered_by": "code_candidate"}
        for c in (data.get("conflicts") or []) if isinstance(c, dict)
    ]
    additional = [
        {**c, "discovered_by": "model"}
        for c in (data.get("additional_conflicts") or [])
        if isinstance(c, dict) and c.get("a") and c.get("b")
    ]
    # 同一对笔记只保留一条，代码候选优先
    merged, seen = [], set()
    for c in confirmed + additional:
        key = tuple(sorted((str(c.get("a", "")), str(c.get("b", "")))))
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)

    solitary = [s for s in (data.get("solitary") or []) if isinstance(s, str)]
    rejected = [r for r in (data.get("rejected") or []) if isinstance(r, dict)]
    return {
        "conflicts": merged,
        "solitary": solitary,
        "candidate_review": {
            "conflict_candidates": len(cc),
            "solitary_candidates": len(sc),
            "confirmed_conflicts": len(confirmed),
            "model_additional": len(additional),
            "rejected": len(rejected),
        },
    }