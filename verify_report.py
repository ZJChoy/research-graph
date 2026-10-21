"""引用审计：逐句核对「句子里的数字/型号是否真的在被引来源里」。

用法：
    python verify_report.py demo_report.md demo_state.json
    python verify_report.py demo_report.md demo_state.json --fetch

离线模式只核对「句子 ↔ 笔记」；加 --fetch 再核对「句子 ↔ 被引网页正文」（走缓存）。
退出码 0 = 全部通过，1 = 有未支持断言或悬空引用。
"""
import argparse
import json
import re
import sys

from eval_run import dangling_citations
from grounding import cited_in, critical_tokens, split_sentences
from sources import bibliography_indices, cited_indices

_BIB_ENTRY = re.compile(r"(?m)^\s*\[(\d+)\]\s*(.*?)\s+-\s+(https?://\S+)")


def load_notes(path: str) -> list:
    try:
        state = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    # 优先用 writer 实际编号的那份（同页截断后），否则退回全量笔记
    final = [n for n in (state.get("final_notes") or []) if isinstance(n, dict)]
    if final:
        return final
    flat = []
    for g in state.get("research_notes") or []:
        for n in (g.get("notes") or []):
            if isinstance(n, dict):
                flat.append(n)
    return flat


def _cell(text: str, limit: int = 110) -> str:
    s = (text or "").replace("|", "\\|").replace("\n", " ")
    return s[:limit] + ("…" if len(s) > limit else "")


def audit(report: str, notes: list, fetch: bool) -> tuple[list, int]:
    rows = []
    checked = 0
    note_by_idx = {i + 1: n for i, n in enumerate(notes)}
    bib = {int(i): url for i, _, url in _BIB_ENTRY.findall(report)}

    pages_cache = {}
    if fetch:
        from search import fetch_page
        for i, n in note_by_idx.items():
            url = n.get("url")
            if url and url not in pages_cache:
                pages_cache[url] = fetch_page(url)

    for sent in split_sentences(report):
        cites = [i for i in cited_in(sent) if i in note_by_idx or i in bib]
        if not cites:
            continue
        checked += 1

        facts = [str(note_by_idx[i].get("fact", "")) for i in cites if i in note_by_idx]
        note_bad = critical_tokens(sent, facts) if facts else None

        page_bad = None
        if fetch:
            urls = {note_by_idx[i].get("url") for i in cites if i in note_by_idx}
            urls |= {bib[i] for i in cites if i in bib}
            urls.discard(None)
            pages = [pages_cache.get(u) or "" for u in urls]
            if pages and any(pages):
                page_bad = critical_tokens(sent, pages)
            else:
                page_bad = ["<页面抓取失败>"]

        bad = bool(note_bad) or bool(page_bad)
        if bad:
            rows.append({
                "sentence": sent,
                "cites": cites,
                "note_bad": note_bad,
                "page_bad": page_bad,
            })
    return rows, checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", nargs="?", default="demo_report.md")
    ap.add_argument("state", nargs="?", default="demo_state.json")
    ap.add_argument("--fetch", action="store_true", help="同时核对被引网页正文（走缓存）")
    ap.add_argument("--out", default="verification.md")
    args = ap.parse_args()

    report = open(args.report, encoding="utf-8").read()
    notes = load_notes(args.state)
    rows, checked = audit(report, notes, args.fetch)
    dangling = dangling_citations(report)

    lines = [
        "# 引用审计",
        "",
        f"- 报告：`{args.report}`",
        f"- 笔记快照：`{args.state}`（{len(notes)} 条笔记）",
        f"- 正文引用编号：{cited_indices(report)}",
        f"- 来源表编号：{bibliography_indices(report)}",
        f"- 悬空引用：{dangling or '无'}",
        f"- 逐句核对：{checked} 句，未支持 {len(rows)} 句",
        "",
        "| 句子 | 引用 | 笔记核对 | 页面核对 |",
        "|---|---|---|---|",
    ]
    def verdict(bad):
        if bad is None:
            return "-"
        return "、".join(bad) if bad else "OK"

    for r in rows:
        lines.append(
            "| %s | %s | %s | %s |" % (
                _cell(r["sentence"]),
                ",".join(str(i) for i in r["cites"]),
                verdict(r["note_bad"]),
                verdict(r["page_bad"]),
            )
        )
    out = "\n".join(lines) + "\n"
    open(args.out, "w", encoding="utf-8").write(out)

    print(out)
    if dangling:
        print("FAIL: 有悬空引用", dangling)
    if rows:
        print(f"FAIL: {len(rows)} 句存在未支持的数字/型号")
    if dangling or rows:
        return 1
    print(f"OK: {checked} 句全部可溯源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
