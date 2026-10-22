"""用人工标注的 claim-source 对校准断言核验。

标注文件每行一个 JSON：
    {"claim": "...", "source": "...", "label": "supported|partial|unsupported"}

用法：
    python calibrate_claim_verify.py
    python calibrate_claim_verify.py my_labels.jsonl --out calibration.md

输出一致率与混淆矩阵。一致率低不代表核验没用，而是说明模型判官
需要按你的标注口径调 prompt 或换模型；没达到 0.8 之前不要拿它做硬判。
"""
import argparse
import json
import sys
from pathlib import Path

import claim_verify

LABELS = ("supported", "partial", "unsupported")


def load(path: str) -> list:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("label") not in LABELS:
            raise ValueError(f"未知 label: {row.get('label')}")
        rows.append(row)
    return rows


def render(rows: list, preds: list, agreement: float) -> str:
    matrix = {a: {b: 0 for b in LABELS} for a in LABELS}
    mismatches = []
    for row, pred in zip(rows, preds):
        got = pred["verdict"]
        if got in matrix[row["label"]]:
            matrix[row["label"]][got] += 1
        if got != row["label"]:
            mismatches.append((row, got, pred.get("reason", "")))

    lines = [
        "# 断言核验校准", "",
        f"- 样本数：{len(rows)}",
        f"- 一致率：{agreement:.2f}",
        f"- 阈值建议：≥ 0.80 才可用于硬判", "",
        "## 混淆矩阵（行=人工，列=模型）", "",
        "| 人工\\模型 | supported | partial | unsupported |",
        "|---|---|---|---|",
    ]
    for a in LABELS:
        lines.append(f"| {a} | {matrix[a]['supported']} | {matrix[a]['partial']} | {matrix[a]['unsupported']} |")
    lines += ["", "## 不一致样本", ""]
    if not mismatches:
        lines.append("（无）")
    for row, got, reason in mismatches:
        lines.append(f"- 人工 **{row['label']}** / 模型 **{got}**：{row['claim']}")
        lines.append(f"  - 来源：{row['source']}")
        if reason:
            lines.append(f"  - 模型理由：{reason}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="?", default="eval/claim_labels.example.jsonl")
    ap.add_argument("--out", default="calibration.md")
    args = ap.parse_args()

    rows = load(args.labels)
    items = [{"claim": r["claim"], "sources": [r["source"]]} for r in rows]
    preds = claim_verify.classify_pairs(items)
    agreement = sum(1 for r, p in zip(rows, preds) if r["label"] == p["verdict"]) / len(rows)
    text = render(rows, preds, agreement)
    Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if agreement >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())