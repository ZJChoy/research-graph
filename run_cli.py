"""命令行跑一次完整调研（自动放行大纲），报告写入 demo_report.md。

用法：python run_cli.py "端侧 AI 芯片格局（2025-2026）"
"""
import sys
import time

from langgraph.types import Command

import eval_run
import graph_full


def main(topic: str) -> None:
    app = graph_full.build()
    cfg = {"configurable": {"thread_id": "cli-%d" % int(time.time())}}
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
    with open("demo_report.md", "w", encoding="utf-8") as f:
        f.write(draft)

    metrics = eval_run.evaluate(draft, state.get("conflicts", []), state.get("revision_count", 0))
    print("报告已写入 demo_report.md（%d 字）" % len(draft))
    print("指标:", metrics)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_cli.py \"调研主题\"")
        sys.exit(1)
    main(sys.argv[1])
