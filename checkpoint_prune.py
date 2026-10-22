"""清理旧的 checkpoint 线程，避免 checkpoints.sqlite 无限增长。

按 thread 保留最近 N 个（默认 20），其余连同 writes 一起删除。
设置 CHECKPOINT_KEEP_THREADS=0 可关闭。
"""
import os
import sqlite3


def prune(conn: sqlite3.Connection, keep_threads: int | None = None) -> int:
    if keep_threads is None:
        try:
            keep_threads = int(os.getenv("CHECKPOINT_KEEP_THREADS", "20"))
        except ValueError:
            keep_threads = 20
    if keep_threads <= 0:
        return 0
    try:
        rows = conn.execute(
            "select thread_id, max(checkpoint_id) as last "
            "from checkpoints group by thread_id order by last desc"
        ).fetchall()
    except sqlite3.Error:
        return 0
    old = [tid for tid, _ in rows[keep_threads:]]
    if not old:
        return 0
    for tid in old:
        conn.execute("delete from writes where thread_id = ?", (tid,))
        conn.execute("delete from checkpoints where thread_id = ?", (tid,))
    conn.commit()
    return len(old)