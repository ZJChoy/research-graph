"""M2 模块 5：fact_checker——交叉验证笔记，标记冲突与孤证。

输入：所有路的调研笔记。输出：冲突清单 + 可用笔记（孤证降级标记）。
规则简单可解释：
- 冲突：两条笔记讲同一对象但数字/结论矛盾
- 孤证：一个事实只有单一来源，降级为 low confidence
"""
from llm import get_llm

llm = get_llm()

CHECK_PROMPT = """你是事实核查员。以下是围绕主题「{topic}」从多个来源抽取的笔记：

{notes}

任务：
1. 找出相互矛盾的笔记对（同一对象、不同数字或相反结论）
2. 找出只有单一来源支撑、且涉及关键数字/结论的孤证笔记
3. 输出 JSON：
{{"conflicts": [{{"a": "笔记1内容", "b": "笔记2内容", "issue": "矛盾点一句话"}}],
 "solitary": ["孤证笔记内容", ...]}}
只输出 JSON，没有就输出空数组。"""

def check_all(topic: str, notes: list[dict]) -> dict:
    """返回 {conflicts: [...], solitary: [...]}；LLM 失败返回空结果（降级）。"""
    flat = []
    for r in notes:
        if not isinstance(r, dict):     # 上游形态异常就跳过这一路，不让核查链断掉
            continue
        for n in (r.get("notes") or []):   # notes 已形态归一为纯 dict
            fact = n.get("fact", "").strip()
            if not fact:
                continue
            flat.append(f"- {fact}（来源: {n.get('source_title', '')}）")
    if len(flat) < 2:
        return {"conflicts": [], "solitary": []}
    resp = llm.invoke(CHECK_PROMPT.format(topic=topic, notes="\n".join(flat)))
    import json
    try:
        return json.loads(resp.content)
    except json.JSONDecodeError:
        cleaned = resp.content.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print("[fact_checker] JSON 解析失败，返回空核查结果")
            return {"conflicts": [], "solitary": []}

