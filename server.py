"""Web 界面：FastAPI + SSE，实时展示图流转。

关键点：
1. 用 graph.stream(..., stream_mode="updates") 拿到每个节点的完成事件，推给前端；
2. interrupt 出现时推大纲，前端确认后通过 /resume 回传，再 Command(resume=...) 继续；
3. 每次运行用独立 thread_id，避免旧会话状态串进新任务。
"""
import html
import json
import os
import queue
import threading
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

import eval_run
import grounding
import llm_usage
import run_store
import source_quality

app = FastAPI(title="Research Graph")

# 每个 SSE 订阅者一个独立队列，事件广播给所有订阅者。
# 之前是全局单队列：多个页面同时连 /events 会互相抢事件，A 拿走 report 后 B 永远收不到。
_subscribers: "list[queue.Queue]" = []
_sub_lock = threading.Lock()

resume_value = None
current_thread = None
waiting_for_resume = threading.Event()   # 只有图真的在 interrupt 处等待时，/resume 才生效
cancel_event = threading.Event()         # 用户主动取消
run_lock = threading.Lock()
RESUME_TIMEOUT = 600                     # 等人工确认的最长秒数，超时终止本次运行

# 节点顺序（用于把下一个节点标成 active）
NODE_ORDER = [
    "planner", "human_review", "research_one_node",
    "fact_checker_node", "writer", "critic", "revise",
]
UI_NAME = {
    "planner": "planner",
    "human_review": "human_review",
    "research_one_node": "research",
    "fact_checker_node": "fact_checker",
    "writer": "writer",
    "critic": "critic",
    "revise": "revise",
}

PAGE = """<!doctype html>
<html lang="zh"><meta charset="utf-8"><title>Research Graph</title>
<style>
  body{font-family:system-ui;max-width:880px;margin:24px auto;padding:0 16px;background:#0d1117;color:#e6edf3}
  h1{font-size:20px} .row{display:flex;gap:8px;margin:8px 0}
  input{flex:1;padding:9px;background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px}
  button{padding:9px 18px;background:#238636;color:#fff;border:0;border-radius:6px;cursor:pointer}
  button:disabled{background:#2d333b;color:#8b949e;cursor:default}
  .node{display:inline-block;padding:5px 12px;margin:4px 4px 4px 0;border-radius:14px;background:#21262d;color:#8b949e;font-size:13px}
  .node.active{background:#1f6feb;color:#fff} .node.done{background:#238636;color:#fff}
  pre{background:#161b22;padding:12px;border-radius:8px;white-space:pre-wrap;max-height:460px;overflow:auto;font-size:13px}
  .interrupt{border:1px solid #d29922;border-radius:8px;padding:12px;margin:12px 0;display:none}
  .muted{color:#8b949e;font-size:13px}
  a{color:#58a6ff}
  #btn-cancel{background:#8b2c2c}
</style>
<h1>Research Graph · 多智能体调研报告</h1>
<div class="row"><input id="topic" value="端侧 AI 芯片格局（2025-2026）">
  <button id="btn-start" type="button">开始</button>
  <button id="btn-cancel" type="button" disabled>取消</button>
  <a href="/runs" style="align-self:center">历史</a>
</div>
<div id="nodes">
  <span class="node" id="n-planner">planner</span><span class="node" id="n-human_review">human_review</span>
  <span class="node" id="n-research">researcher×N</span><span class="node" id="n-fact_checker">fact_checker</span>
  <span class="node" id="n-writer">writer</span><span class="node" id="n-critic">critic</span>
  <span class="node" id="n-revise">revise</span>
</div>
<div class="interrupt" id="interrupt">
  <b>请确认调研大纲</b><pre id="outline"></pre>
  <div class="row"><input id="feedback" placeholder="留空=通过；输入修改意见"><button id="btn-resume" type="button">确认并继续</button></div>
</div>
<div class="muted" id="status"></div>
<div class="muted" id="runlink"></div>
<pre id="log"></pre>
<script>
const $ = id => document.getElementById(id);
let es = null;

function setStatus(t){ $("status").textContent = t; }
function markDone(name){
  const el = $("n-" + name);
  if (el){ el.className = "node done"; }
}
function markActive(name){
  const el = $("n-" + name);
  if (el && el.className.indexOf("done") < 0){ el.className = "node active"; }
}

async function start(){
  $("log").textContent = "";
  $("interrupt").style.display = "none";
  document.querySelectorAll(".node").forEach(n => n.className = "node");
  $("btn-start").disabled = true;
  $("btn-cancel").disabled = false;
  $("runlink").textContent = "";
  setStatus("启动中…");
  await fetch("/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({topic: $("topic").value})
  });
  listen();
}

async function resume(){
  const f = $("feedback").value;
  $("interrupt").style.display = "none";
  setStatus("继续执行…");
  await fetch("/resume", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({feedback: f})
  });
}

async function cancel(){
  setStatus("取消中…");
  await fetch("/cancel", {method: "POST"});
}

function listen(){
  if (es){ es.close(); }
  es = new EventSource("/events");
  es.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.type === "node"){ markActive(m.name); setStatus("执行中：" + m.name); }
    if (m.type === "node_done"){ markDone(m.name); }
    if (m.type === "log"){ $("log").textContent += m.text + String.fromCharCode(10); }
    if (m.type === "interrupt"){
      $("outline").textContent = m.outline;
      $("interrupt").style.display = "block";
      setStatus("等待你确认大纲");
    }
    if (m.type === "report"){
      $("log").textContent = m.text;
      if (!m.ok){ setStatus("失败"); }
      else if (m.quality === false){ setStatus("完成（有未解决问题：" + m.citation_errors + " 处引用）"); }
      else { setStatus("完成"); }
      if (m.run_id){
        $("runlink").innerHTML = '<a href="/runs/' + m.run_id + '">查看本次运行详情</a>';
      }
      $("btn-start").disabled = false;
      $("btn-cancel").disabled = true;
      if (es){ es.close(); es = null; }
    }
  };
  es.onerror = () => { setStatus("连接中断，刷新页面可重看结果"); };
}

document.getElementById("btn-start").onclick = () => start();
document.getElementById("btn-resume").onclick = () => resume();
document.getElementById("btn-cancel").onclick = () => cancel();
</script></html>"""


class StartBody(BaseModel):
    topic: str


class ResumeBody(BaseModel):
    feedback: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.post("/start")
def start(body: StartBody):
    global resume_value, current_thread
    if not run_lock.acquire(blocking=False):
        return {"ok": False, "error": "已有任务在跑"}
    resume_value = None
    waiting_for_resume.clear()
    cancel_event.clear()
    current_thread = f"web-{uuid.uuid4().hex[:8]}"
    # 清掉各订阅者上次运行残留的事件，避免新任务被旧事件污染
    with _sub_lock:
        for q in _subscribers:
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
    threading.Thread(target=run_graph, args=(body.topic.strip(), current_thread), daemon=True).start()
    return {"ok": True, "thread": current_thread}


@app.post("/cancel")
def cancel():
    if not run_lock.locked():
        return {"ok": False, "error": "当前没有任务在跑"}
    cancel_event.set()
    return {"ok": True}


@app.post("/resume")
def resume(body: ResumeBody):
    global resume_value
    # 校验当前确实在等确认：否则这里写入的值会被下一次 interrupt 直接消费掉，
    # 等于跳过人工确认
    if not waiting_for_resume.is_set():
        return {"ok": False, "error": "当前没有等待确认的任务"}
    text = body.feedback.strip()
    resume_value = text if text else {"type": "continue"}
    return {"ok": True}


RUNS_CSS = """
body{font-family:system-ui;max-width:1100px;margin:24px auto;padding:0 16px;background:#0d1117;color:#e6edf3}
h1{font-size:20px} h2{font-size:16px;margin-top:24px}
a{color:#58a6ff} .muted{color:#8b949e;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
th,td{border-bottom:1px solid #30363d;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#8b949e;font-weight:500}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#21262d}
.b-official{background:#1f6feb;color:#fff}.b-media{background:#238636;color:#fff}
.b-blog{background:#6e40c9;color:#fff}.b-unknown{background:#30363d;color:#8b949e}
pre{background:#161b22;padding:12px;border-radius:8px;white-space:pre-wrap;max-height:600px;overflow:auto;font-size:13px}
"""


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{RUNS_CSS}</style>
<body><h1>{html.escape(title)}</h1><p><a href="/">← 返回</a> · <a href="/runs">运行历史</a></p>
{body}</body></html>"""


@app.get("/runs", response_class=HTMLResponse)
def runs_index():
    runs = run_store.list_runs()
    if not runs:
        return _shell("运行历史", '<p class="muted">还没有运行记录。</p>')
    rows = []
    for r in runs:
        quality = ('<span class="ok">达标</span>' if r.get("quality_ok")
                   else '<span class="bad">未达标</span>')
        cov = r.get("coverage")
        rows.append(
            "<tr><td><a href=\"/runs/%s\">%s</a></td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(str(r.get("id"))), html.escape(str(r.get("created_at"))),
                html.escape(str(r.get("topic"))), quality,
                "%.3f" % cov if cov is not None else "-",
                r.get("sources", "-"), r.get("chars", "-"),
            )
        )
    body = ("<table><tr><th>时间</th><th>主题</th><th>交付</th><th>覆盖率</th>"
            "<th>来源数</th><th>事实句</th></tr>" + "".join(rows) + "</table>")
    return _shell("运行历史", body)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: str):
    run = run_store.get(run_id)
    if not run:
        return HTMLResponse(_shell("找不到该运行", '<p class="bad">运行记录不存在。</p>'),
                            status_code=404)
    metrics = run.get("metrics") or {}
    sq = run.get("source_quality") or {}
    notes = run.get("final_notes") or []
    report = run.get("report") or ""
    sents = grounding.split_sentences(report)

    summary = [
        ("交付", "达标" if run.get("quality_ok") else "未达标"),
        ("覆盖率", "%.3f" % metrics.get("citation_coverage", 0)),
        ("来源", "%s 域名 / %s 页面" % (metrics.get("source_diversity", 0),
                                     metrics.get("source_pages", 0))),
        ("冲突", "%s 组（处理率 %s）" % (metrics.get("conflict_total", 0),
                                      metrics.get("conflict_handled"))),
        ("悬空引用", len(metrics.get("dangling_citations") or [])),
        ("事实句", metrics.get("fact_statements", 0)),
        ("多源印证", "%s / %s" % (sq.get("corroborated", 0), sq.get("total_sources", 0))),
    ]
    total = (run.get("llm_usage") or {}).get("total") or {}
    summary.append(("模型用量", "%s 次调用 / %s input + %s output tokens" % (
        total.get("calls", 0), total.get("input_tokens", 0), total.get("output_tokens", 0))))
    cv = run.get("claim_verify_summary") or {}
    if cv.get("total"):
        summary.append(("断言核验", "S %s / P %s / U %s / ? %s" % (
            cv.get("supported", 0), cv.get("partial", 0),
            cv.get("unsupported", 0), cv.get("unverified", 0))))

    summary_html = "".join(
        "<tr><th>%s</th><td>%s</td></tr>" % (html.escape(k), html.escape(str(v)))
        for k, v in summary
    )

    source_rows = []
    for i, n in enumerate(notes, 1):
        tier = n.get("tier") or source_quality.tier(n.get("url") or "")
        label = source_quality.LABEL.get(tier, "未知")
        cited = [s for s in sents if i in grounding.cited_in(s)]
        first = html.escape(cited[0][:120]) if cited else '<span class="muted">未被正文引用</span>'
        source_rows.append(
            "<tr><td>[%d]</td><td><span class=\"badge b-%s\">%s</span></td>"
            "<td><a href=\"%s\">%s</a><br><span class=\"muted\">%s</span></td>"
            "<td>%s</td><td>%s</td><td>%s<br><span class=\"muted\">%s</span></td></tr>" % (
                i, html.escape(tier), html.escape(label),
                html.escape(str(n.get("url") or "")),
                html.escape(str(n.get("source_title") or "")[:80]),
                html.escape(source_quality.domain(n.get("url") or "")),
                html.escape(str(n.get("published") or "-")),
                "多源印证" if n.get("corroborated") else "单一来源",
                len(cited), first,
            )
        )
    sources_html = ("<table><tr><th>#</th><th>层级</th><th>来源</th><th>发布年</th>"
                    "<th>印证</th><th>被引用</th></tr>" + "".join(source_rows) + "</table>")

    claim_rows = []
    for c in run.get("claim_verification") or []:
        v = c.get("verdict", "unverified")
        cls = {"supported": "ok", "partial": "warn",
               "unsupported": "bad"}.get(v, "muted")
        claim_rows.append(
            "<tr><td class=\"%s\">%s</td><td>%s</td><td>%s</td></tr>" % (
                cls, html.escape(v), html.escape(c.get("sentence", "")[:160]),
                html.escape(c.get("reason", "")[:200]),
            )
        )
    claims_html = ("<table><tr><th>判定</th><th>句子</th><th>理由</th></tr>"
                   + "".join(claim_rows) + "</table>") if claim_rows else '<p class="muted">未做断言核验。</p>'

    conflicts = run.get("conflicts") or []
    conflict_html = "".join(
        "<li>%s<br><span class=\"muted\">与之不一致：%s</span><br>"
        "<span class=\"warn\">%s</span></li>" % (
            html.escape(str(c.get("a", ""))), html.escape(str(c.get("b", ""))),
            html.escape(str(c.get("issue", ""))))
        for c in conflicts
    ) or '<li class="muted">本次未检出冲突。</li>'

    body = f"""
<table>{summary_html}</table>
<h2>来源与引用</h2>{sources_html}
<h2>断言核验</h2>{claims_html}
<h2>冲突</h2><ul>{conflict_html}</ul>
<h2>报告</h2><pre>{html.escape(report)}</pre>
"""
    return _shell("运行详情 · %s" % run.get("topic", ""), body)


def broadcast(item: dict):
    """把事件推给所有 SSE 订阅者。"""
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        q.put(item)


def push_node(name: str):
    ui = UI_NAME.get(name, name)
    broadcast({"type": "node_done", "name": ui})
    idx = NODE_ORDER.index(name) if name in NODE_ORDER else -1
    if idx >= 0 and idx + 1 < len(NODE_ORDER):
        nxt = NODE_ORDER[idx + 1]
        if nxt != "revise":
            broadcast({"type": "node", "name": UI_NAME.get(nxt, nxt)})


def summarize(node: str, update) -> str:
    """把节点产出压成一行日志，前端能看出进展。"""
    if not isinstance(update, dict):
        return ""
    if node == "planner":
        return "大纲生成完毕：" + update.get("outline", "")[:80].replace("\n", " ")
    if node == "research_one_node":
        groups = update.get("research_notes") or []
        total = sum(len(g.get("notes", [])) for g in groups)
        return f"一路调研完成，新增 {total} 条笔记"
    if node == "fact_checker_node":
        return "核查完成：冲突 %d 组" % len(update.get("conflicts", []))
    if node == "writer":
        return "报告成稿 %d 字" % len(update.get("draft", ""))
    if node == "critic":
        rep = update.get("review_report") or {}
        return "审稿：" + ("通过" if rep.get("pass") else "不通过，返工")
    return ""


def _snapshot(topic: str, thread_id: str, state: dict, draft: str,
              metrics: dict, quality_ok: bool) -> dict:
    return {
        "thread_id": thread_id,
        "topic": topic,
        "report": draft,
        "quality_ok": quality_ok,
        "metrics": metrics,
        "raw_metrics": state.get("raw_metrics") or {},
        "final_metrics": state.get("final_metrics") or metrics,
        "final_notes": state.get("final_notes") or [],
        "conflicts": state.get("conflicts") or [],
        "solitary": state.get("solitary") or [],
        "conflict_candidates": state.get("conflict_candidates") or {},
        "citation_errors": state.get("citation_errors") or [],
        "grounding_warnings": state.get("grounding_warnings") or [],
        "source_quality": source_quality.summarize(state.get("final_notes") or []),
        "llm_usage": llm_usage.snapshot(),
        "claim_verification": state.get("claim_verification") or [],
        "claim_verify_summary": state.get("claim_verify_summary") or {},
        "review_report": state.get("review_report") or {},
    }


def run_graph(topic: str, thread_id: str):
    global resume_value
    llm_usage.reset()
    cfg = {"configurable": {"thread_id": thread_id}, "max_concurrency": 3}
    app_graph = None
    try:
        try:
            import graph_full
            app_graph = graph_full.build()
        except Exception as e:
            broadcast({"type": "report", "ok": False, "text": f"图装配失败：{e}"})
            return

        payload = {"topic": topic}
        try:
            while True:
                interrupted = None
                cancelled = False
                for chunk in app_graph.stream(payload, config=cfg, stream_mode="updates"):
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    if "__interrupt__" in chunk:
                        interrupted = chunk["__interrupt__"]
                        continue
                    for node, update in chunk.items():
                        if node.startswith("__"):
                            continue
                        push_node(node)
                        line = summarize(node, update)
                        if line:
                            broadcast({"type": "log", "text": f"[{node}] {line}"})
                if cancelled:
                    broadcast({"type": "report", "ok": False, "text": "已取消本次运行"})
                    return
                if interrupted is None:
                    break
                value = interrupted[0].value if interrupted else {}
                broadcast({"type": "interrupt", "outline": value.get("outline", "")})
                # 等人工确认，带超时：用户关页面不确认时线程不能永远挂着，
                # 否则 run_lock 永不释放，之后所有 /start 都会报「已有任务在跑」
                waiting_for_resume.set()
                waited = 0.0
                while (resume_value is None and waited < RESUME_TIMEOUT
                       and not cancel_event.is_set()):
                    time.sleep(0.2)
                    waited += 0.2
                waiting_for_resume.clear()
                if cancel_event.is_set():
                    broadcast({"type": "report", "ok": False, "text": "已取消本次运行"})
                    return
                if resume_value is None:
                    broadcast({"type": "report", "ok": False,
                               "text": f"等待大纲确认超时（{RESUME_TIMEOUT // 60} 分钟），本次运行已终止"})
                    return
                payload = Command(resume=resume_value)
                resume_value = None

            state = app_graph.get_state(cfg).values
            draft = state.get("draft") or "(未生成报告)"
            metrics = eval_run.evaluate(
                draft, state.get("conflicts") or [], state.get("revision_count") or 0
            )
            quality_ok = bool(metrics.get("quality_ok")) and not (state.get("citation_errors") or [])
            rid = None
            try:
                rid = run_store.save(_snapshot(topic, thread_id, state, draft, metrics, quality_ok))
            except Exception as e:
                print(f"[server] 运行历史保存失败: {e}")
            broadcast({
                "type": "report",
                "ok": True,
                "text": draft,
                "quality": quality_ok,
                "citation_errors": len(state.get("citation_errors") or []),
                "metrics": metrics,
                "llm_usage": llm_usage.snapshot(),
                "claim_verify": state.get("claim_verify_summary") or {},
                "run_id": rid,
            })
        except Exception as e:
            broadcast({"type": "report", "ok": False,
                       "text": f"图执行失败：{type(e).__name__}: {e}"})
    finally:
        # 关掉本次运行专用的 sqlite 连接，避免每次「开始」泄漏一个连接
        if app_graph is not None:
            conn = getattr(app_graph, "_sqlite_conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        run_lock.release()


@app.get("/events")
def sse():
    q: "queue.Queue" = queue.Queue()
    with _sub_lock:
        _subscribers.append(q)

    def gen():
        try:
            while True:
                try:
                    item = q.get(timeout=20)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") == "report":
                    break
        finally:
            with _sub_lock:
                if q in _subscribers:
                    _subscribers.remove(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
