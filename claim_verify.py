"""断言级核验：数字对得上 ≠ 这句话被来源支持。

对带引用的句子，用便宜模型判断来源是否支持该陈述：
supported / partial / unsupported。默认只记录、不阻塞交付；
设置 CLAIM_VERIFY_STRICT=1 才把 unsupported 计入 citation_errors。

成本控制：
- 默认最多核验 20 句（CLAIM_VERIFY_MAX_CLAIMS）；
- 只挑高风险句子（含数字/型号，或含否定/因果/程度词）；
- 8 句一批，模型默认 qwen-turbo（LLM_VERIFY_MODEL）。
"""
import json
import os
import re

import grounding
from llm import get_claim_llm, invoke

llm = get_claim_llm()

BATCH = 8
_RISK = re.compile(r"(不|未|没有|并非|导致|因为|因此|使得|从而|只有|唯一|首次|超过|低于|高于|普遍)")

PROMPT = """你是事实核查员。判断每条 claim 是否被所给资料支持。
只依据资料本身，不要使用你的外部知识。

verdict 只能是：
- supported：资料明确支持该陈述，数字、时间、主体、否定关系都一致
- partial：核心方向一致，但范围/程度/限定被夸大或遗漏，
  且没有关键数字或时间的直接矛盾（例：资料说「部分厂商」，陈述说「所有厂商」）
- unsupported：关键数字、时间、否定关系或主体与资料矛盾，
  或资料根本没有提及该结论（例：资料 256 TOPS，陈述 512 TOPS；
  资料计划 2026 年上市，陈述 2025 年正式发布）

待核查：
{items}

输出 JSON（每条都要有结果，id 对应上面的编号）：
{{"results": [{{"id": 1, "verdict": "supported", "reason": "一句话"}}]}}
只输出 JSON。"""


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


def classify_pairs(items: list) -> list:
    """items = [{"claim": ..., "sources": [文本...]}] → [{verdict, reason}]。"""
    out = [{"verdict": "unverified", "reason": "未提交核验"} for _ in items]
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        blocks = []
        for i, item in enumerate(batch, 1):
            sources = "\n".join(f"- {s}" for s in item.get("sources") or [])
            blocks.append(f"[{i}] claim：{item.get('claim', '')}\n资料：\n{sources}")
        try:
            resp = invoke(llm, "claim_verify", PROMPT.format(items="\n\n".join(blocks)))
        except Exception as e:
            for i in range(1, len(batch) + 1):
                out[start + i - 1] = {"verdict": "unverified",
                                      "reason": f"核验调用失败: {e}"[:200]}
            continue
        data = _parse(resp.content)
        got = {}
        for r in (data.get("results") or []):
            if not isinstance(r, dict):
                continue
            try:
                idx = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            verdict = str(r.get("verdict", "")).lower()
            if 1 <= idx <= len(batch) and verdict in ("supported", "partial", "unsupported"):
                got[idx] = {"verdict": verdict, "reason": str(r.get("reason", ""))[:200]}
        for i in range(1, len(batch) + 1):
            out[start + i - 1] = got.get(
                i, {"verdict": "unverified", "reason": "模型未返回该条结果"}
            )
    return out


def _high_risk(sentence: str) -> bool:
    return bool(grounding.critical_tokens(sentence, []) or _RISK.search(sentence))


def verify_claims(draft: str, notes: list, max_claims: int | None = None) -> tuple[list, dict]:
    """返回 (明细, 汇总)。只核验带引用且高风险的句子。"""
    if max_claims is None:
        try:
            max_claims = int(os.getenv("CLAIM_VERIFY_MAX_CLAIMS", "20"))
        except ValueError:
            max_claims = 20

    items, meta = [], []
    for sent in grounding.split_sentences(draft):
        cites = [i for i in grounding.cited_in(sent) if 1 <= i <= len(notes)]
        if not cites or not _high_risk(sent) or len(items) >= max_claims:
            continue
        items.append({
            "claim": sent,
            "sources": [str(notes[i - 1].get("fact", "")) for i in cites],
        })
        meta.append({"sentence": sent[:160], "citations": cites})

    if not items:
        return [], {"total": 0, "supported": 0, "partial": 0,
                    "unsupported": 0, "unverified": 0}

    verdicts = classify_pairs(items)
    detail = []
    for m, v in zip(meta, verdicts):
        detail.append({**m, **v})
    summary = {"total": len(detail)}
    for key in ("supported", "partial", "unsupported", "unverified"):
        summary[key] = sum(1 for d in detail if d["verdict"] == key)
    return detail, summary