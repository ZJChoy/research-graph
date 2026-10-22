import sqlite3

from checkpoint_prune import prune


def test_prune_keeps_latest_threads(workdir):
    conn = sqlite3.connect(workdir / "cp.db")
    conn.execute("create table checkpoints(thread_id text, checkpoint_id text)")
    conn.execute("create table writes(thread_id text)")
    for i in range(5):
        conn.execute("insert into checkpoints values (?, ?)", (f"t{i}", f"cp{i}"))
        conn.execute("insert into writes values (?)", (f"t{i}",))
    conn.commit()

    assert prune(conn, keep_threads=2) == 3
    left = {r[0] for r in conn.execute("select distinct thread_id from checkpoints")}
    assert left == {"t3", "t4"}
    assert conn.execute("select count(*) from writes").fetchone()[0] == 2


def test_prune_disabled(workdir):
    conn = sqlite3.connect(workdir / "cp2.db")
    conn.execute("create table checkpoints(thread_id text, checkpoint_id text)")
    conn.execute("insert into checkpoints values ('t', '1')")
    conn.commit()
    assert prune(conn, keep_threads=0) == 0