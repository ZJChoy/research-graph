"""比较两次运行的快照：引用、来源、冲突、指标的变化。

用法：
    python compare_runs.py demo_state_prev.json demo_state.json --out compare.md

用途：同一主题重跑后，确认「结论/来源/指标」没有因为检索抖动而漂移；
也用于审稿返工前后对比。退出码 0 表示没有新增悬空引用或硬问题。
"""
import argparse
import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_urls(state: dict) -> list:
    return [n.get("url", "") for n in (state.get("final_notes") or [])]


def metrics(state: dict) -> dict:
    return state.get("metrics") or {}


def compare(prev: dict, cur: dict) -> dict:
    p_urls, c_urls = source_urls(prev), source_urls(cur)
    p_set, c_set = set(p_urls), set(c_urls)
    pm, cm = metrics(prev), metrics(cur)
    keys = ["citation_coverage", "source_diversity", "conflict_total",
            "conflict_handled", "revisions", "fact_statements"]
    deltas = {}
    for k in keys:
        if k in pm and k in cm:
            deltas[k] = round((cm[k] or 0) - (pm[k] or 0), 3)
    return {
        "sources_added": sorted(c_set - p_set),
        "sources_removed": sorted(p_set - c_set),
        "sources_kept": len(p_set & c_set),
        "deltas": deltas,
        "prev_dangling": len(pm.get("dangling_citations") or []),
        "cur_dangling": len(cm.get("dangling_citations") or []),
        "prev_blocking": bool((prev.get("review_report") or {}).get("blocking")),
        "cur_blocking": bool((cur.get("review_report") or {}).get("blocking")),
    }


def render(result: dict) -> str:
    lines = ["# 两次运行对比", ""]
    lines.append(f"- 来源保留 {result['sources_kept']} 个；"
                 f"新增 {len(result['sources_added'])}，移除 {len(result['sources_removed'])}")
    for u in result["sources_added"]:
        lines.append(f"  - + {u}")
    for u in result["sources_removed"]:
        lines.append(f"  - - {u}")
    lines += ["", "| 指标 | 变化 |", "|---|---|"]
    for k, v in result["deltas"].items():
        lines.append(f"| {k} | {v:+} |")
    lines += [
        "",
        f"- 悬空引用：{result['prev_dangling']} → {result['cur_dangling']}",
        f"- 阻塞性硬问题：{'有' if result['prev_blocking'] else '无'} → "
        f"{'有' if result['cur_blocking'] else '无'}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prev")
    ap.add_argument("cur", nargs="?", default="demo_state.json")
    ap.add_argument("--out", default="compare.md")
    args = ap.parse_args()

    result = compare(load(args.prev), load(args.cur))
    text = render(result)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    ok = result["cur_dangling"] == 0 and not result["cur_blocking"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
