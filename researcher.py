"""M2 模块 4：单路 researcher（子问题 → 结构化笔记）。

流程：子问题 → search.retrieve 拿带 URL 的正文 → LLM 从正文提取事实笔记。
LLM 只做'抽取'不做'创作'：笔记里的事实必须能在正文里找到。
"""
import json
from llm import get_llm
from search import retrieve

llm = get_llm()

EXTRACT_PROMPT = """你是事实抽取员。下面是关于「{subquestion}」的网页资料（每段标了来源编号）。

{sources}

任务：从资料中抽取 3-6 条事实笔记。要求：
1. 只抽取资料里明确写出的事实，禁止补充资料外的知识
2. 每条笔记一句话，具体（含数字/型号/时间优先）
3. citation 用资料里的来源编号，如 [S1]
4. 输出 JSON：{{"notes": [{{"fact": "...", "citation": "S1"}}, ...]}}
只输出 JSON。"""

def research_one(subquestion: str) -> dict:
    """单路调研：检索 → 抽取。返回 dict（图内统一形态，可序列化）。任何失败降级为空笔记。"""
    pages = retrieve(subquestion)
    if not pages:
        return {"subquestion": subquestion, "notes": []}

    # 组装带来源编号的资料文本
    sources_text = "\n\n".join(
        f"[S{i+1}] 标题：{p['source_title']}\nURL：{p['url']}\n内容：{p['content'][:1500]}"
        for i, p in enumerate(pages)
    )
    url_map = {f"S{i+1}": p["url"] for i, p in enumerate(pages)}
    title_map = {f"S{i+1}": p["source_title"] for i, p in enumerate(pages)}

    resp = llm.invoke(EXTRACT_PROMPT.format(subquestion=subquestion, sources=sources_text))
    try:
        data = json.loads(resp.content)
    except json.JSONDecodeError:
        # 模型偶尔输出带 ```json 围栏的 JSON，剥一次再试
        cleaned = resp.content.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"[research_one] JSON 解析失败: {subquestion}")
            return {"subquestion": subquestion, "notes": []}

    notes = []
    for n in data.get("notes", []):
        cite = n.get("citation", "")
        if cite in url_map:  # 只保留能溯源到真实 URL 的笔记
            notes.append({
                "fact": n.get("fact", "").strip(),
                "url": url_map[cite],
                "source_title": title_map[cite],
                "confidence": "medium",
            })
    return {"subquestion": subquestion, "notes": notes}

if __name__ == "__main__":
    r = research_one("2025 年地平线征程 6 芯片的算力和量产情况")
    print(f"子问题：{r['subquestion']}\n拿到 {len(r['notes'])} 条笔记：")
    for n in r['notes']:
        print(f"- {n['fact']}\n  来源: {n['source_title']} {n['url']}")

