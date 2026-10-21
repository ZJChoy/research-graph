"""M1 模块 2：检索工具层。

职责：主题/子问题 → 结构化检索片段（内容 + URL + 标题）。
三步：DuckDuckGo 搜索（挂代理）→ httpx 抓网页 → trafilatura 抽正文。
"""
import ipaddress
import os
import re
from urllib.parse import urlparse

import httpx
import trafilatura
from dotenv import load_dotenv
from ddgs import DDGS

import cache

load_dotenv()

# 每个子问题最多取多少条搜索结果（多了慢且重复，M3 评测时再调）
MAX_RESULTS = 6
# 每个子问题最多保留几页正文：太少会几节共用同一来源，太多则 token 吃紧
MAX_PAGES_PER_QUERY = 3

def _proxy() -> dict:
    """读 .env 里的代理配置；没配就不走代理。"""
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    return {"proxy": proxy} if proxy else {}

def search_web(query: str, retries: int = 2) -> list[dict]:
    """搜索：返回 [{title, url, body}]，失败重试一次后返回空列表（不抛异常）。"""
    cache_key = {"q": query, "n": MAX_RESULTS}
    cached = cache.get("search", cache_key)
    if cached is not None:
        return cached
    last = None
    for attempt in range(retries):
        try:
            with DDGS(**_proxy()) as ddgs:
                hits = [
                    {"title": h["title"], "url": h["href"], "body": h.get("body", "")}
                    for h in ddgs.text(query, max_results=MAX_RESULTS)
                ]
            if hits:
                cache.put("search", cache_key, hits)
                return hits
            last = "空结果"
        except Exception as e:
            last = str(e)[:120]
    print(f"[search_web] 搜索失败（{query[:20]}）: {last}")
    return []

def _is_safe_url(url: str) -> bool:
    """SSRF 防护：只放行公网 http(s) 地址，挡回环/内网/链路本地地址。

    局限：域名解析到内网 IP 的情况这里查不到（不做 DNS 解析），
    由 fetch_page 里对最终 URL（含重定向后）的二次校验兜底。
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True          # 普通域名，放行
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


def fetch_page(url: str, timeout: float = 15.0) -> str:
    """抓单个网页并抽取正文，失败返回空串。"""
    if not _is_safe_url(url):
        print(f"[fetch_page] 拒绝访问非公网地址: {url}")
        return ""
    cached = cache.get("page", url)
    if cached is not None:
        return cached
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
        # 重定向可能把请求带进内网，对最终 URL 再校验一次
        if not _is_safe_url(str(resp.url)):
            print(f"[fetch_page] 重定向到非公网地址，已丢弃: {resp.url}")
            return ""
    except Exception as e:
        print(f"[fetch_page] 抓取失败 {url}: {e}")
        return ""
    text = trafilatura.extract(resp.text) or ""
    text = text[:4000]  # 截断：正文太长时只取前 4000 字，够 LLM 用
    cache.put("page", url, text)
    return text

def _bigrams(text: str) -> set:
    """粗粒度中文分词：连续两字组合，够用来做相关性筛选。"""
    clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def _relevant(query: str, hit: dict) -> bool:
    """标题+摘要与查询至少共现 2 个二字词，才算沾边。"""
    q = _bigrams(query)
    hay = _bigrams((hit.get("title") or "") + (hit.get("body") or ""))
    return len(q & hay) >= 2


_QUERY_PUNCT = re.compile(r"[的与和及或、，。：:；;（）()【】\[\]？?！!\"'“”‘’\s]+")
_QUERY_TAIL = re.compile(r"(情况|分析|研究|进展|总结|探讨|概述|现状)$")


def to_query(s: str, max_len: int = 16) -> str:
    """把大纲标题改写成检索词：去虚词、去问句尾巴、限长。

    实测「2025年地平线征程6芯片的算力和量产情况」这类长句在 DuckDuckGo
    上直接零结果；缩短到「2025年地平线征程6芯片 算力」后才有命中。
    """
    q = _QUERY_PUNCT.sub(" ", s or "").strip()
    q = _QUERY_TAIL.sub("", q).strip()
    if len(q) > max_len:
        parts = q.split()
        out = []
        for p in parts:
            if sum(len(x) for x in out) + len(p) > max_len:
                break
            out.append(p)
        q = " ".join(out) if out else q[:max_len]
    return q.strip() or (s or "").strip()[:max_len]


def query_variants(s: str) -> list:
    """同一子问题的多个检索写法，按命中率从高到低试。"""
    q = to_query(s)
    outs = [q]
    if "2025" not in q and len(q) < 14:
        outs.append(q + " 2025")
    core = q.split()[0] if q.split() else q
    if core and core != q:
        outs.append(core[:12])
    seen, uniq = set(), []
    for x in outs:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def build_queries(topic: str, subquestion: str) -> list:
    """主题锚点 + 子问题关键词的组合查询。

    只用子问题搜，会搜回「产品路线图工具」「供应链」这类跑题页；
    只用主题搜，5 路子问题又全变成同一个查询。所以两者都要带上。
    """
    anchor = to_query(topic, 10)
    sub = to_query(subquestion, 14)
    outs = []
    # 先搜子问题本身（保证各路来源不重叠），再搜组合，最后才退回主题
    if sub:
        outs.append(sub)
    if anchor and sub:
        outs.append(f"{anchor} {sub}")
    if anchor:
        outs.append(anchor)
    seen, uniq = set(), []
    for q in outs:
        if q and q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def retrieve(query: str, topic: str | None = None) -> list[dict]:
    """检索入口：query → [{source_title, url, content}]。

    返回值只保留与主题锚点相关的页面：全都不沾边时返回空，
    由上游写「公开资料有限，待补充」。宁缺勿滥——跑题页面进笔记，
    最后就是一份每句都有引用、却没有一句站得住的报告。
    """
    anchor = to_query(topic, 10) if topic else to_query(query, 10)
    queries = build_queries(topic, query) if topic else query_variants(query)

    seen_urls = set()
    results = []
    for q in queries:
        hits = search_web(q)
        if not hits:
            continue
        # 主题锚点是硬过滤：跑题页面即使命中了子问题关键词也不收
        on_topic = [h for h in hits if _relevant(anchor, h)]
        if not on_topic:
            continue
        # 与子问题更贴近的排前面
        on_topic.sort(key=lambda h: len(_bigrams(to_query(query, 20)) & _bigrams((h.get("title") or "") + (h.get("body") or ""))), reverse=True)
        for hit in on_topic:
            if hit["url"] in seen_urls:
                continue
            seen_urls.add(hit["url"])
            content = fetch_page(hit["url"])
            if content:
                results.append({
                    "source_title": hit["title"],
                    "url": hit["url"],
                    "content": content,
                })
            if len(results) >= MAX_PAGES_PER_QUERY:
                return results
    return results

if __name__ == "__main__":
    # 冒烟：跑一条真实查询
    items = retrieve("端侧 AI 芯片 地平线 高通 2025")
    print(f"拿到 {len(items)} 条结果\n")
    for it in items:
        print("-", it["source_title"], "|", it["url"])
        print(" 正文前 120 字：", it["content"][:120].replace("\n", " "))
        print()
