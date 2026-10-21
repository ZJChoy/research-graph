# Research Graph · 多智能体深度调研报告生成器

输入一个主题，多个 agent 并行检索、交叉核查、带引用成稿；大纲先人工确认。基于 LangGraph 的 StateGraph / 条件边 / interrupt / Send 并行 / Checkpointer。

设计文档见 [../调研报告生成器-PRD.md](../调研报告生成器-PRD.md)。

## 图结构

```
planner → human_review（interrupt 人工确认大纲）
        → research_one_node × N（Send 并行，每路一个子问题）
        → fact_checker_node（多来源比对，标冲突与孤证）
        → writer（按大纲成稿，事实句标 [n]）
        → critic（模型判质量 + 代码判硬指标）
           ├─ 不通过 → revise → critic（最多 2 轮）
           └─ 通过 / 预算耗尽 → END
```

## 跑起来

```powershell
cd research-graph
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # 填 DASHSCOPE_API_KEY 与代理端口
python server.py          # 浏览器打开 http://127.0.0.1:8000
```

命令行跑一次完整流程（自动放行大纲，报告写入 demo_report.md）：

```powershell
python run_cli.py "端侧 AI 芯片格局（2025-2026）"
```

评测：

```powershell
python eval_run.py demo_report.md
```

## 评测口径

| 指标 | 定义 | v1 目标 |
|---|---|---|
| 引用覆盖率 | 含数字/英文专名的事实句里带 [n] 的比例（标了「（推断）」的句子不计入分母） | ≥ 90% |
| 来源多样性 | 来源表中的唯一域名数 | ≥ 3 |
| 冲突处理率 | fact_checker 标出的冲突在终稿被说明或回避的比例 | 100% |
| 返工次数 | critic 触发 revise 的次数 | 观察项 |

## 设计上值得说的几处

- **引用编号由代码映射到 URL**（sources.py）：模型只负责写 [n]，来源表由代码根据笔记生成，避免 URL 被模型编造或漏抄。
- **critic 的硬指标不交给模型**：正文零引用、长度不足 300 字由代码直接判不通过。
- **重写丢引用时保留原稿**：revise 若把引用洗掉，代码回退到上一版并结束返工，避免越改越差。
- **检索失败降级不炸图**：搜索/抓取失败返回空结果，某一路调研空手而归不影响整张图。
- **并行写状态用 reducer**：research_notes 挂 merge_list，Send 的多路写入才不冲突。

## 已知限制

- DuckDuckGo 中文结果质量一般，部分子问题会空手而归；已加关键词相关性过滤与一次重试，仍不保证覆盖率。
- 知乎/百度学术等站点反爬，抓取会 403，按设计降级。
- 一次完整调研 2–4 分钟（真检索 + 多轮 LLM + 可能的返工）。
- 断点续跑已落盘（SQLite），Web 端未做「重启后自动恢复上次进度」的界面。
