"""M2 三模块联测：单路调研 → 交叉核查 → 带引用成稿。"""
from researcher import research_one
from fact_checker import check_all
from learning.writer_cited import write_cited

def main():
    topic = "端侧 AI 芯片格局（2025-2026）"
    subs = [
        "地平线征程6 算力与量产",
        "高通 Ride 平台量产车型",
        "端侧 AI 芯片竞争格局总结",
    ]
    print("=== 1/3 并行调研（3 路）===")
    notes = [research_one(s) for s in subs]  # 每路返回 dict：{"subquestion", "notes"}
    total = sum(len(r["notes"]) for r in notes)
    print(f"共 {total} 条笔记\n")
    assert total >= 3, "笔记太少，先检查代理和搜索"

    print("=== 2/3 事实核查 ===")
    verdict = check_all(topic, notes)
    print(f"冲突 {len(verdict['conflicts'])} 组，孤证 {len(verdict['solitary'])} 条\n")

    print("=== 3/3 带引用成稿 ===")
    flat = []
    for r in notes:
        flat.extend(r["notes"])
    report = write_cited(topic, "# 端侧 AI 芯片格局\n## 主要玩家\n## 量产进展\n## 格局总结", flat)
    print(report[:600])
    assert "[" in report and "]" in report, "报告应含引用编号"
    print("\nM2 联测通过")

if __name__ == "__main__":
    main()

