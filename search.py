"""M1 模块 2：检索工具层。

职责：主题/子问题 → 结构化检索片段（内容 + URL + 标题）。
三步：DuckDuckGo 搜索（挂代理）→ httpx 抓网页 → trafilatura 抽正文。
"""
import os
import re
import httpx
import trafilatura
from dotenv import load_dotenv
from ddgs import DDGS

load_dotenv()

# 每个子问题最多取多少条搜索结果（多了慢且重复，M3 评测时再调）
MAX_RESULTS = 4

def _proxy() -> dict:
    """读 .env 里的代理配置；没配就不走代理。"""
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    return {"proxy": proxy} if proxy else {}

def search_web(query: str, retries: int = 2) -> list[dict]:
    """搜索：返回 [{title, url}]，失败重试一次后返回空列表（不抛异常）。"""
    last = None
    for attempt in range(retries):
        try:
            with DDGS(**_proxy()) as ddgs:
                hits = [
                    {"title": h["title"], "url": h["href"], "body": h.get("body", "")}
                    for h in ddgs.text(query, max_results=MAX_RESULTS)
                ]
            if hits:
                return hits
            last = "空结果"
        except Exception as e:
            last = str(e)[:120]
    print(f"[search_web] 搜索失败（{query[:20]}）: {last}")
    return []

def fetch_page(url: str, timeout: float = 15.0) -> str:
    """抓单个网页并抽取正文，失败返回空串。"""
    try:
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy,
            headers={"User-Agent": "Mozilla/5.0 (research-graph/0.1)"},
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[fetch_page] 抓取失败 {url}: {e}")
        return ""
    text = trafilatura.extract(resp.text) or ""
    return text[:4000]  # 截断：正文太长时只取前 4000 字，够 LLM 用

def _bigrams(text: str) -> set:
    """粗粒度中文分词：连续两字组合，够用来做相关性筛选。"""
    clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def _relevant(query: str, hit: dict) -> bool:
    """标题+摘要与查询至少共现 2 个二字词，才算沾边。"""
    q = _bigrams(query)
    hay = _bigrams((hit.get("title") or "") + (hit.get("body") or ""))
    return len(q & hay) >= 2


def retrieve(query: str) -> list[dict]:
    """检索入口：query → [{source_title, url, content}]。"""
    hits = search_web(query)
    kept = [h for h in hits if _relevant(query, h)]
    # 全都不沾边时退回原结果，避免直接空手而归
    hits = kept or hits
    results = []
    for hit in hits:
        content = fetch_page(hit["url"])
        if content:
            results.append({
                "source_title": hit["title"],
                "url": hit["url"],
                "content": content,
            })
    return results

if __name__ == "__main__":
    # 冒烟：跑一条真实查询
    items = retrieve("端侧 AI 芯片 地平线 高通 2025")
    print(f"拿到 {len(items)} 条结果\n")
    for it in items:
        print("-", it["source_title"], "|", it["url"])
        print(" 正文前 120 字：", it["content"][:120].replace("\n", " "))
        print()
