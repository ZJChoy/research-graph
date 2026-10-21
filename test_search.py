"""模块 2 自检：不依赖 LLM，只测检索层。"""
from search import search_web, fetch_page, retrieve

def test_search_web_returns_hits():
    hits = search_web("地平线机器人 征程6 芯片")
    assert len(hits) > 0, "搜索应至少返回 1 条结果"
    assert all("url" in h and h["url"].startswith("http") for h in hits)

def test_fetch_page_returns_text():
    hits = search_web("地平线机器人 征程6 芯片")
    assert hits, "前置：搜索要有结果"
    text = fetch_page(hits[0]["url"])
    assert len(text) > 100, "正文抽取应得到实质内容"

def test_retrieve_filters_dead_pages():
    items = retrieve("端侧 AI 芯片 2025")
    assert all(it["content"] for it in items), "retrieve 返回的每条都应有正文"

if __name__ == "__main__":
    test_search_web_returns_hits()
    print("test_search_web OK")
    test_fetch_page_returns_text()
    print("test_fetch_page OK")
    test_retrieve_filters_dead_pages()
    print("test_retrieve OK")
    print("模块 2 全部自检通过")

