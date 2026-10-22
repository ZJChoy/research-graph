"""运行历史：每次运行落一个 JSON，供 Web 列表/详情页读取。

不写数据库：一次运行一个文件，便于直接查看、备份、diff。
目录默认 runs/，可用 RUNS_DIR 覆盖。
"""
import json
import os
import re
import time
from pathlib import Path

RUNS_DIR = Path(os.getenv("RUNS_DIR", "runs"))
_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def save(snapshot: dict) -> str:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    thread = str(snapshot.get("thread_id", ""))[:8]
    rid = f"{time.strftime('%Y%m%d-%H%M%S')}-{thread}" if thread else time.strftime("%Y%m%d-%H%M%S")
    data = {"id": rid, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), **snapshot}
    path = RUNS_DIR / f"{rid}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return rid


def list_runs(limit: int = 50) -> list:
    if not RUNS_DIR.exists():
        return []
    items = []
    for p in sorted(RUNS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        m = d.get("metrics") or {}
        items.append({
            "id": d.get("id"),
            "created_at": d.get("created_at"),
            "topic": d.get("topic"),
            "quality_ok": d.get("quality_ok"),
            "coverage": m.get("citation_coverage"),
            "sources": (d.get("source_quality") or {}).get("total_sources"),
            "chars": m.get("fact_statements"),
        })
    return items


def get(run_id: str):
    if not run_id or not _ID.match(run_id):
        return None
    path = RUNS_DIR / f"{run_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None