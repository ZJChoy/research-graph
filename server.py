"""Web 界面：FastAPI + SSE，实时展示图流转。

关键点：
1. 用 graph.stream(..., stream_mode="updates") 拿到每个节点的完成事件，推给前端；
2. interrupt 出现时推大纲，前端确认后通过 /resume 回传，再 Command(resume=...) 继续；
3. 每次运行用独立 thread_id，避免旧会话状态串进新任务。
"""
import json
import queue
import threading
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

app = FastAPI(title="Research Graph")

events: "queue.Queue[dict]" = queue.Queue()
resume_value = None
current_thread = None
run_lock = threading.Lock()

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
</style>
<h1>Research Graph · 多智能体调研报告</h1>
<div class="row"><input id="topic" value="端侧 AI 芯片格局（2025-2026）"><button id="btn-start" type="button">开始</button></div>
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
      setStatus(m.ok ? "完成" : "失败");
      $("btn-start").disabled = false;
      if (es){ es.close(); es = null; }
    }
  };
  es.onerror = () => { setStatus("连接中断，刷新页面可重看结果"); };
}

document.getElementById("btn-start").onclick = () => start();
document.getElementById("btn-resume").onclick = () => resume();
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
    current_thread = f"web-{uuid.uuid4().hex[:8]}"
    while not events.empty():
        events.get_nowait()
    threading.Thread(target=run_graph, args=(body.topic.strip(), current_thread), daemon=True).start()
    return {"ok": True, "thread": current_thread}


@app.post("/resume")
def resume(body: ResumeBody):
    global resume_value
    text = body.feedback.strip()
    resume_value = text if text else {"type": "continue"}
    return {"ok": True}


def push_node(name: str):
    ui = UI_NAME.get(name, name)
    events.put({"type": "node_done", "name": ui})
    idx = NODE_ORDER.index(name) if name in NODE_ORDER else -1
    if idx >= 0 and idx + 1 < len(NODE_ORDER):
        nxt = NODE_ORDER[idx + 1]
        if nxt != "revise":
            events.put({"type": "node", "name": UI_NAME.get(nxt, nxt)})


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


def run_graph(topic: str, thread_id: str):
    global resume_value
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        import graph_full
        app_graph = graph_full.build()
    except Exception as e:
        events.put({"type": "report", "ok": False, "text": f"图装配失败：{e}"})
        run_lock.release()
        return

    payload = {"topic": topic}
    try:
        while True:
            interrupted = None
            for chunk in app_graph.stream(payload, config=cfg, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    interrupted = chunk["__interrupt__"]
                    continue
                for node, update in chunk.items():
                    if node.startswith("__"):
                        continue
                    push_node(node)
                    line = summarize(node, update)
                    if line:
                        events.put({"type": "log", "text": f"[{node}] {line}"})
            if interrupted is None:
                break
            value = interrupted[0].value if interrupted else {}
            events.put({"type": "interrupt", "outline": value.get("outline", "")})
            while resume_value is None:
                time.sleep(0.2)
            payload = Command(resume=resume_value)
            resume_value = None

        state = app_graph.get_state(cfg).values
        draft = state.get("draft") or "(未生成报告)"
        events.put({"type": "report", "ok": True, "text": draft})
    except Exception as e:
        events.put({"type": "report", "ok": False, "text": f"图执行失败：{type(e).__name__}: {e}"})
    finally:
        if run_lock.locked():
            run_lock.release()


@app.get("/events")
def sse():
    def gen():
        while True:
            try:
                item = events.get(timeout=20)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") == "report":
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
