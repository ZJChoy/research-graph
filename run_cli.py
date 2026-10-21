"""命令行跑一次完整调研（自动放行大纲），报告写入 demo_report.md。

用法：python run_cli.py "端侧 AI 芯片格局（2025-2026）"
"""
import json
import sys
import uuid

from langgraph.types import Command

import eval_run
import graph_full


def main(topic: str) -> None:
    app = graph_full.build()
    try:
        # 并行调研最多 3 路同时跑，避免一次打太多搜索请求被限流
        cfg = {"configurable": {"thread_id": "cli-%s" % uuid.uuid4().hex[:8]}, "max_concurrency": 3}
        payload = {"topic": topic}

        while True:
            interrupted = None
            for chunk in app.stream(payload, config=cfg, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    interrupted = chunk["__interrupt__"]
                    continue
                for node in chunk:
                    if not node.startswith("__"):
                        print("[node] " + node, flush=True)
            if interrupted is None:
                break
            print("[node] 大纲已生成，自动放行", flush=True)
            payload = Command(resume={"type": "continue"})

        state = app.get_state(cfg).values
        draft = state.get("draft", "")
        if not draft.strip():
            print("警告：本次运行没有产出报告（draft 为空），请检查上面各节点日志")
        with open("demo_report.md", "w", encoding="utf-8") as f:
            f.write(draft)

        metrics = eval_run.evaluate(draft, state.get("conflicts", []), state.get("revision_count", 0))
        review = state.get("review_report") or {}
        quality_ok = bool(metrics.get("quality_ok")) and not (state.get("citation_errors") or []) and not review.get("blocking")
        snapshot = {
            "topic": state.get("topic"),
            "outline": state.get("outline"),
            "research_notes": state.get("research_notes") or [],
            "final_notes": state.get("final_notes") or [],
            "conflicts": state.get("conflicts") or [],
            "solitary": state.get("solitary") or [],
            "review_report": state.get("review_report") or {},
            "revision_count": state.get("revision_count") or 0,
            "citation_errors": state.get("citation_errors") or [],
            "grounding_warnings": state.get("grounding_warnings") or [],
            "citation_meta": state.get("citation_meta") or {},
            "metrics": metrics,
            "quality_ok": quality_ok,
        }
        with open("demo_state.json", "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        print("报告已写入 demo_report.md（%d 字），运行快照写入 demo_state.json" % len(draft))
        print("指标:", metrics)
        if not quality_ok:
            print("警告：硬指标未达标或仍有未解决的引用问题（见 demo_state.json）")
        elif not review.get("pass"):
            print("审稿建议（不影响交付判定）：" + "；".join((review.get("problems") or [])[:2])[:200])
    finally:
        conn = getattr(app, "_sqlite_conn", None)
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_cli.py \"调研主题\"")
        sys.exit(1)
    main(sys.argv[1])
