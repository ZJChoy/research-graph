"""从运行快照导出 claim-source 对，供人工标注后校准断言核验。

用法：
    python make_claim_labels.py demo_state.json
    # 生成 claim_labels.to_label.jsonl：label 为空，人工填 supported/partial/unsupported
    python calibrate_claim_verify.py claim_labels.to_label.jsonl

只导出带引用、且命中高风险特征的句子；同一句子只出现一次。
"""
import argparse
import json
import sys
from pathlib import Path

import grounding


def load_notes(path: str) -> list:
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    final = [n for n in (state.get("final_notes") or []) if isinstance(n, dict)]
    if final:
        return final
    flat = []
    for g in state.get("research_notes") or []:
        for n in (g.get("notes") or []):
            if isinstance(n, dict):
                flat.append(n)
    return flat


def export(report: str, notes: list, max_pairs: int = 50) -> list:
    out, seen = [], set()
    for sent in grounding.split_sentences(report):
        cites = [i for i in grounding.cited_in(sent) if 1 <= i <= len(notes)]
        if not cites or sent in seen:
            continue
        if not (grounding.critical_tokens(sent, []) or
                any(w in sent for w in ("不", "未", "没有", "导致", "因为", "首次", "普遍"))):
            continue
        seen.add(sent)
        out.append({
            "claim": sent,
            "source": "\n".join(str(notes[i - 1].get("fact", "")) for i in cites),
            "label": "",
        })
        if len(out) >= max_pairs:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("state", nargs="?", default="demo_state.json")
    ap.add_argument("--report", default="demo_report.md")
    ap.add_argument("--out", default="claim_labels.to_label.jsonl")
    ap.add_argument("--max", type=int, default=50)
    args = ap.parse_args()

    report = Path(args.report).read_text(encoding="utf-8")
    notes = load_notes(args.state)
    rows = export(report, notes, args.max)
    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"导出 {len(rows)} 条到 {args.out}；填好 label 后运行 calibrate_claim_verify.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())