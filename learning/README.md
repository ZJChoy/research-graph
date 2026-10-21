# 学习阶段脚本（不参与主流程）

M1–M3 的分模块练习，保留用于回顾概念。从项目根目录运行：

    python -m learning.graph            # M1 最小图 planner → writer
    python -m learning.graph_interrupt  # M1 interrupt 人工确认
    python -m learning.parallel         # M2 串行对比冒烟
    python -m learning.test_m2          # M2 三模块联测（联网 + 调模型）
    python -m learning.test_search      # 检索层自检（联网）

主流程请用 `run_cli.py` / `server.py`。
