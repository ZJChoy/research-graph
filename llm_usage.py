"""按节点统计 LLM 调用次数、token 与耗时。

用途：
1. 回答「一份报告花多少钱、时间花在哪个节点」；
2. 给批量回归提供成本列；
3. 断言核验的额外开销可以被单独看到（node="claim_verify"）。

价格默认不填：不同账号/套餐单价不同，硬编码会误导。
设置 LLM_PRICE_INPUT_PER_M / LLM_PRICE_OUTPUT_PER_M（元/百万 token）后才给估算。
"""
import os
import threading
from collections import defaultdict

_lock = threading.Lock()
_nodes = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                              "seconds": 0.0})


def reset() -> None:
    with _lock:
        _nodes.clear()


def record(node: str, input_tokens: int = 0, output_tokens: int = 0,
           seconds: float = 0.0) -> None:
    with _lock:
        item = _nodes[node]
        item["calls"] += 1
        item["input_tokens"] += int(input_tokens or 0)
        item["output_tokens"] += int(output_tokens or 0)
        item["seconds"] = round(item["seconds"] + float(seconds or 0), 2)


def snapshot() -> dict:
    with _lock:
        nodes = {k: dict(v) for k, v in _nodes.items()}
    total = {
        "calls": sum(v["calls"] for v in nodes.values()),
        "input_tokens": sum(v["input_tokens"] for v in nodes.values()),
        "output_tokens": sum(v["output_tokens"] for v in nodes.values()),
        "seconds": round(sum(v["seconds"] for v in nodes.values()), 2),
    }
    cost = _estimate_cost(total)
    if cost is not None:
        total["cost_estimate"] = cost
    return {"nodes": nodes, "total": total}


def _estimate_cost(total: dict):
    try:
        pin = float(os.getenv("LLM_PRICE_INPUT_PER_M", "0"))
        pout = float(os.getenv("LLM_PRICE_OUTPUT_PER_M", "0"))
    except ValueError:
        return None
    if pin <= 0 and pout <= 0:
        return None
    return round(total["input_tokens"] / 1e6 * pin
                 + total["output_tokens"] / 1e6 * pout, 4)