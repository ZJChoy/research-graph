"""批量回归：多个主题各跑一次完整流程，汇总指标。

用法：
    python batch_eval.py                 # 跑内置 5 个主题
    python batch_eval.py topics.txt      # 每行一个主题
    python batch_eval.py --resume        # 复用已有结果，只补跑失败的

结果写入 batch_results.json 与 batch_report.md。检索走缓存，
第二次跑同样主题会快很多。
"""
import json
import statistics
import sys
import time
from pathlib import Path

DEFAULT_TOPICS = [
    "端侧 AI 芯片格局（2025-2026）",
    "RISC-V 在数据中心服务器的落地进展",
    "固态电池量产进度与产业链",
    "AI 编程助手对软件工程流程的影响",
    "人形机器人关节模组的成本结构",
]

OUT = Path("batch_results.json")
REPORT = Path("batch_report.md")


def run_one(topic: str, workdir: Path) -> dict:
    """跑一个主题，返回该次的指标快照。异常也记录，不中断整批。"""
    import uuid

    from langgraph.types import Command

    import eval_run
    import graph_full
    import llm_usage
    import source_quality

    llm_usage.reset()
    t0 = time.time()
    app = graph_full.build(str(workdir / "cp.sqlite"))
    try:
        cfg = {"configurable": {"thread_id": "batch-%s" % uuid.uuid4().hex[:8]},
               "max_concurrency": 3}
        payload = {"topic": topic}
        while True:
            interrupted = None
            for chunk in app.stream(payload, config=cfg, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    interrupted = chunk["__interrupt__"]
            if interrupted is None:
                break
            payload = Command(resume={"type": "continue"})

        state = app.get_state(cfg).values
        draft = state.get("draft") or ""
        metrics = eval_run.evaluate(
            draft, state.get("conflicts") or [], state.get("revision_count") or 0
        )
        cleanup = {"autocited": 0, "stripped": 0, "marked": 0}
        for w in state.get("grounding_warnings") or []:
            if "autocited_sentences" in w:
                cleanup["autocited"] = w["autocited_sentences"]
            if "stripped_unsupported_sentences" in w:
                cleanup["stripped"] = w["stripped_unsupported_sentences"]
            if "marked_inferences" in w:
                cleanup["marked"] = w["marked_inferences"]
        return {
            "topic": topic,
            "ok": bool(draft),
            "chars": len(draft),
            "elapsed_s": round(time.time() - t0, 1),
            "metrics": metrics,
            # 以最终交付稿为准：code_clean 之后 citation_errors 会被重新计算
            "blocking": (not metrics.get("quality_ok")) or bool(state.get("citation_errors")),
            "citation_errors": len(state.get("citation_errors") or []),
            "cleanup": cleanup,
            "source_quality": source_quality.summarize(state.get("final_notes") or []),
            "llm_usage": llm_usage.snapshot(),
            "raw_coverage": (state.get("raw_metrics") or {}).get("citation_coverage"),
            "final_coverage": (state.get("final_metrics") or metrics).get("citation_coverage"),
            "claim_verify": state.get("claim_verify_summary") or {},
        }
    except Exception as e:  # 单个主题失败不影响整批
        return {
            "topic": topic,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_s": round(time.time() - t0, 1),
        }
    finally:
        conn = getattr(app, "_sqlite_conn", None)
        if conn is not None:
            conn.close()


def summarize(results: list) -> dict:
    done = [r for r in results if r.get("ok")]
    if not done:
        return {"n": len(results), "ok": 0}
    cov = [r["metrics"]["citation_coverage"] for r in done]
    return {
        "n": len(results),
        "ok": len(done),
        "targets_met": sum(1 for r in done if r["metrics"].get("targets_met")),
        "quality_ok": sum(1 for r in done if r["metrics"].get("quality_ok")),
        "coverage_mean": round(statistics.mean(cov), 3),
        "coverage_min": min(cov),
        "raw_coverage_mean": round(statistics.mean(
            [r["raw_coverage"] for r in done if r.get("raw_coverage") is not None] or [0]), 3),
        "dangling_total": sum(len(r["metrics"]["dangling_citations"]) for r in done),
        "conflicts_total": sum(r["metrics"]["conflict_total"] for r in done),
        "autocited_total": sum((r.get("cleanup") or {}).get("autocited", 0) for r in done),
        "stripped_total": sum((r.get("cleanup") or {}).get("stripped", 0) for r in done),
        "marked_total": sum((r.get("cleanup") or {}).get("marked", 0) for r in done),
        "claim_supported_total": sum((r.get("claim_verify") or {}).get("supported", 0) for r in done),
        "claim_partial_total": sum((r.get("claim_verify") or {}).get("partial", 0) for r in done),
        "claim_unsupported_total": sum((r.get("claim_verify") or {}).get("unsupported", 0) for r in done),
        "input_tokens_total": sum((r.get("llm_usage") or {}).get("total", {}).get("input_tokens", 0) for r in done),
        "output_tokens_total": sum((r.get("llm_usage") or {}).get("total", {}).get("output_tokens", 0) for r in done),
        "median_elapsed_s": statistics.median([r["elapsed_s"] for r in done]),
    }


def render(results: list, summary: dict) -> str:
    lines = [
        "# 批量回归结果", "",
        "| 主题 | 字数 | 初稿→终稿覆盖率 | 来源(域名/页面) | 冲突 | 悬空 | 未达标 | 补引用/删句/标推断 | 断言核验 S/P/U | 耗时 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if not r.get("ok"):
            lines.append(f"| {r['topic']} | - | - | - | - | - | - | - | - | 失败：{r.get('error', '')[:40]} |")
            continue
        m = r["metrics"]
        sq = r["source_quality"]
        c = r.get("cleanup") or {}
        lines.append(
            "| %s | %d | %s→%.3f | %d/%d | %d | %d | %s | %d/%d/%d | %d/%d/%d | %.0fs |" % (
                r["topic"], r["chars"],
                ("%.3f" % r["raw_coverage"]) if r.get("raw_coverage") is not None else "-",
                r.get("final_coverage", m["citation_coverage"]),
                m["source_diversity"], m["source_pages"], m["conflict_total"],
                len(m["dangling_citations"]), "有" if r["blocking"] else "无",
                c.get("autocited", 0), c.get("stripped", 0), c.get("marked", 0),
                (r.get("claim_verify") or {}).get("supported", 0),
                (r.get("claim_verify") or {}).get("partial", 0),
                (r.get("claim_verify") or {}).get("unsupported", 0),
                r["elapsed_s"],
            )
        )
    lines += [
        "", "## 汇总", "",
        f"- 完成 {summary.get('ok', 0)}/{summary.get('n', 0)} 个主题",
        f"- targets_met：{summary.get('targets_met', 0)}；quality_ok：{summary.get('quality_ok', 0)}",
        f"- 引用覆盖率：初稿均值 {summary.get('raw_coverage_mean', 0)} → "
        f"终稿均值 {summary.get('coverage_mean', 0)}，最低 {summary.get('coverage_min', 0)}",
        f"- 悬空引用合计 {summary.get('dangling_total', 0)}；冲突检出合计 {summary.get('conflicts_total', 0)}",
        f"- 代码兜底合计：补引用 {summary.get('autocited_total', 0)} 句、"
        f"删句 {summary.get('stripped_total', 0)} 句、标推断 {summary.get('marked_total', 0)} 句",
        f"- 断言核验合计：supported {summary.get('claim_supported_total', 0)} / "
        f"partial {summary.get('claim_partial_total', 0)} / "
        f"unsupported {summary.get('claim_unsupported_total', 0)}",
        f"- Token 合计：{summary.get('input_tokens_total', 0)} input / "
        f"{summary.get('output_tokens_total', 0)} output",
        f"- 单主题耗时中位数 {summary.get('median_elapsed_s', 0)} 秒",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list) -> int:
    resume = "--resume" in argv
    files = [a for a in argv if not a.startswith("-")]
    topics = DEFAULT_TOPICS
    if files:
        topics = [s.strip() for s in Path(files[0]).read_text(encoding="utf-8").splitlines() if s.strip()]

    workdir = Path(".batch_run")
    workdir.mkdir(exist_ok=True)

    results = []
    if resume and OUT.exists():
        results = json.loads(OUT.read_text(encoding="utf-8"))
        done = {r["topic"] for r in results if r.get("ok")}
        results = [r for r in results if r.get("ok")]
        topics = [t for t in topics if t not in done]
        print(f"续跑：已完成 {len(done)} 个，待跑 {len(topics)} 个")

    for i, topic in enumerate(topics, 1):
        print(f"[{i}/{len(topics)}] {topic}", flush=True)
        r = run_one(topic, workdir)
        results.append(r)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if r.get("ok"):
            m = r["metrics"]
            print(f"    {r['chars']} 字 | 覆盖率 {m['citation_coverage']} | "
                  f"来源 {m['source_diversity']} | 悬空 {len(m['dangling_citations'])} | "
                  f"{r['elapsed_s']}s", flush=True)
        else:
            print(f"    失败：{r.get('error', '')[:80]}", flush=True)

    summary = summarize(results)
    REPORT.write_text(render(results, summary), encoding="utf-8")
    print("\n汇总:", json.dumps(summary, ensure_ascii=False))
    print(f"明细：{OUT}；汇总：{REPORT}")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
