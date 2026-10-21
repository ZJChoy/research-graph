# Research Graph · 多智能体深度调研报告生成器

输入一个主题，多个 agent 并行检索、交叉核查、带引用成稿；大纲先人工确认。基于 LangGraph 的 StateGraph / 条件边 / interrupt / Send 并行 / Checkpointer。

## 图结构

```
planner → human_review（interrupt 人工确认大纲）
        → research_one_node × N（Send 并行，每路一个子问题）
        → fact_checker_node（多来源比对，标冲突与孤证）
        → writer（按大纲成稿，事实句标 [n]）
        → critic（代码判硬指标 + 模型给建议）
           ├─ 硬问题 → revise → critic（最多 2 轮）
           └─ 达标 / 预算耗尽 → END（无出处句子由代码删除）
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

命令行跑一次完整流程（自动放行大纲），产出三个文件：

```powershell
python run_cli.py "端侧 AI 芯片格局（2025-2026）"
# demo_report.md   报告
# demo_state.json  运行快照（笔记、冲突、审稿意见、指标）
# 控制台            指标 + 交付判定
```

离线测试（不联网、不花 API）：

```powershell
pip install pytest
python -m pytest
```

引用审计（逐句核对「句子里的数字/型号是否真的在被引来源里」）：

```powershell
python verify_report.py demo_report.md demo_state.json --fetch
# 退出码 0 = 全部可溯源；生成 verification.md
```

## 评测口径

| 指标 | 定义 | 目标 |
|---|---|---|
| 引用覆盖率 | 含数字/英文专名的事实句里带 [n] 的比例（切句含分号，标注「推断」「未披露」「待补充」的句子不计入分母） | ≥ 90% |
| 来源多样性 | 来源表中的唯一域名数 / 唯一页面数 | ≥ 3 |
| 冲突处理率 | fact_checker 标出的冲突在终稿（含代码生成的《数据分歧说明》）被说明的比例；未检出冲突时记为「未验证」而非 100% | 100% |
| 悬空引用 | 正文引用编号在来源表里找不到的个数 | 0 |
| 返工次数 | critic 触发 revise 的次数 | 观察项 |

`targets_met` 要求全部达标（冲突必须真实检出并处理）；`quality_ok` 是可交付判定，
允许「冲突未检出」但要求覆盖率、悬空引用、无阻塞性硬问题。

## 设计上值得说的几处

- **引用编号与来源表由代码生成**（sources.py）：模型只写 [n]，来源表按引用编号生成；
  模型自带的「参考文献/参考资料」小节无论哪种写法都会被剥掉；越界编号从正文删除并记入
  `citation_errors`，而不是只从来源表里悄悄丢掉。
- **一个来源一个编号**：同一 URL 的多条笔记合并到同一编号下，
  避免同一篇文章被编成 [5][6][12] 三个「独立来源」。
- **两层接地检查**（grounding.py）：
  抽取层要求笔记里的数字能在被引页面正文里找到，否则丢弃这条笔记；
  成稿层要求句子里出现的数字/型号能在被引笔记里找到，否则判为硬问题触发返工；
  返工预算用尽仍不合格时，**代码直接删除这些句子**，不交付无出处的数字。
- **检索先过主题锚点再排序**：只用子问题搜会搜回「产品路线图工具」这类跑题页；
  主题锚点做硬过滤，宁可某节写「公开资料有限，待补充」，也不收跑题内容。
- **冲突说明由代码生成**：模型经常把双方数据都抄进报告却不说明矛盾，
  终稿统一追加《数据分歧说明》附录，内容直接来自 fact_checker。
- **交付判定不交给模型**：引用覆盖率、悬空引用、覆盖率不足的句子清单都由代码算；
  LLM 审稿意见保留为建议（`review_report.problems`），只影响一轮返工，不阻塞交付。
- **并行写状态用 reducer**：research_notes 挂 merge_list，Send 的多路写入才不冲突；
  运行时并发限制为 3，避免一次打太多搜索请求被限流。
- **检索结果缓存**（cache.py，7 天 TTL）：重跑不再反复请求搜索引擎，demo 可复现。

## 已知限制

- DuckDuckGo 中文结果质量一般；长句查询会先改写成关键词，但仍不保证每节都有资料。
- 知乎/百度学术等站点反爬会 403，按设计降级为空结果。
- 一次完整调研 2–4 分钟（真检索 + 多轮 LLM + 可能的返工）。
- 接地检查只比对数字与型号，中文措辞层面对不上（改写、转述）只记为软警告，不强制返工。
- 信源本身的可靠性不做判定：如果来源是一篇推测性的行业博客，报告只能如实转述并标注来源。
- 断点续跑已落盘（SQLite），Web 端未做「重启后自动恢复上次进度」的界面。

## 目录

```
graph_full.py   图装配与节点       researcher.py  单路调研（检索→抽取）
search.py       检索层             sources.py     来源表/引用收口
grounding.py    接地检查           critic.py      审稿与返工路由
fact_checker.py 冲突/孤证核查      eval_run.py    评测口径
verify_report.py 引用审计          server.py      FastAPI + SSE
cache.py        检索缓存           tests/         离线测试
learning/       M1–M3 学习阶段的独立脚本（不参与主流程）
```
