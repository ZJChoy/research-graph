"""检索结果磁盘缓存。

用途：
1. 重跑同一主题时不再反复打 DuckDuckGo（也降低被限流的概率）；
2. demo 可复现——同一查询拿到同一批来源；
3. 离线验证报告引用时可直接用缓存页面。

只缓存非空结果：一次临时失败不应该在缓存里躺 7 天。
设置 RESEARCH_GRAPH_NO_CACHE=1 可完全绕过。
"""
import hashlib
import json
import os
import time
from pathlib import Path

CACHE_DIR = Path(os.getenv("RESEARCH_GRAPH_CACHE_DIR", ".cache"))
TTL_SECONDS = int(float(os.getenv("RESEARCH_GRAPH_CACHE_TTL_DAYS", "7")) * 86400)


def enabled() -> bool:
    return os.getenv("RESEARCH_GRAPH_NO_CACHE", "").lower() not in ("1", "true", "yes")


def _path(kind: str, key) -> Path:
    raw = json.dumps([kind, key], ensure_ascii=False, sort_keys=True)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{kind}-{h}.json"


def get(kind: str, key):
    if not enabled():
        return None
    p = _path(kind, key)
    try:
        if time.time() - p.stat().st_mtime > TTL_SECONDS:
            return None
        return json.loads(p.read_text(encoding="utf-8"))["value"]
    except (OSError, ValueError, KeyError):
        return None


def put(kind: str, key, value) -> None:
    if not enabled() or value in (None, "", [], {}):
        return
    p = _path(kind, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"key": key, "value": value}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, p)
    except OSError:
        pass
