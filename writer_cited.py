"""M2 模块 6：带引用的 writer——事实句带 [n] 编号，文末列来源。

与 M1 草稿 writer 的区别：只允许使用笔记里的事实，每个事实标引用编号。
"""
from llm import get_llm

llm = get_llm()

def write_cited(topic: str, outline: str, notes: list[dict]) -> str:
    """notes = [{fact, url, source_title}] 全量扁平化的笔记。"""
    numbered = "\n".join(
        f"[{i+1}] {n['fact']}（来源: {n['source_title']}）"
        for i, n in enumerate(notes)
    )
    resp = llm.invoke(
        f"主题：{topic}\n大纲：\n{outline}\n\n已核查的资料笔记：\n{numbered}\n\n"
        "任务：按大纲写 800 字左右的中文调研报告。要求：\n"
        "1. 每个事实性陈述后面标注资料编号，如 [2]\n"
        "2. 只使用资料笔记里的事实，禁止编造笔记外的内容\n"
        "3. 笔记覆盖不到的章节，写明「公开资料有限，待补充」\n"
        "4. 报告末尾列出全部引用来源"
    )
    return resp.content

