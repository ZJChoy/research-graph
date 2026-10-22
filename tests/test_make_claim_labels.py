import make_claim_labels


def test_export_filters_uncited_and_dedupes():
    notes = [{"fact": "甲芯片算力 128 TOPS"}]
    report = "甲芯片算力 128 TOPS[1]。行业正在演进（推断）。甲芯片算力 128 TOPS[1]。"
    rows = make_claim_labels.export(report, notes)
    assert len(rows) == 1
    assert rows[0]["claim"] == "甲芯片算力 128 TOPS[1]。"
    assert "128 TOPS" in rows[0]["source"]
    assert rows[0]["label"] == ""


def test_export_respects_max():
    notes = [{"fact": "甲芯片算力 128 TOPS"}]
    report = "甲芯片算力 128 TOPS[1]。甲芯片算力 128 TOPS[1] 的第二句。"
    rows = make_claim_labels.export(report, notes, max_pairs=1)
    assert len(rows) == 1