"""统一的模型封装：全部节点共用这一个入口。"""
import os
import time

import httpx
from dotenv import load_dotenv

# 关掉 langchain-openai 的 TCP keepalive 注入，避免它覆盖我们自己传的 http_client
os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")
from langchain_openai import ChatOpenAI

import llm_usage

load_dotenv()


def _client_kwargs() -> dict:
    """LLM 默认直连，不继承 HTTP(S)_PROXY。

    代理常用来翻墙搜网页，但 DashScope 是境内服务；代理挂了会连带
    让所有 LLM 调用失败。确实需要代理时设 LLM_USE_PROXY=1。
    """
    if os.getenv("LLM_USE_PROXY", "").lower() in ("1", "true", "yes"):
        return {}
    return {"http_client": httpx.Client(trust_env=False)}

def get_llm():
    # 注意：环境变量 HTTP(S)_PROXY 会被底层 httpx 读取，LLM 请求也会走代理。
    # 如果代理只用于搜索翻墙、LLM 想直连 dashscope，
    # 可改为传 http_client=httpx.Client(trust_env=False)（需 import httpx）。
    #
    # 温度默认 0：同一主题重跑时指标要能对齐，否则覆盖率会在 0.75~1.0 之间抖。
    # 需要更多样的行文时设 LLM_TEMPERATURE=0.3。
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "qwen-plus"),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        **_client_kwargs(),
    )


def get_claim_llm():
    """断言核验模型：默认复用主模型；可设 LLM_VERIFY_MODEL 换更便宜的。"""
    return ChatOpenAI(
        model=os.getenv("LLM_VERIFY_MODEL", os.getenv("LLM_MODEL", "qwen-plus")),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0,
        **_client_kwargs(),
    )


def invoke(llm_obj, node: str, prompt: str):
    """调用模型并记录该节点的 token/耗时。测试里替换的是 llm_obj，不影响统计。"""
    t0 = time.time()
    resp = llm_obj.invoke(prompt)
    usage = getattr(resp, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    if not usage:
        meta = getattr(resp, "response_metadata", None) or {}
        tu = meta.get("token_usage") or {}
        input_tokens = tu.get("prompt_tokens") or tu.get("input_tokens") or 0
        output_tokens = tu.get("completion_tokens") or tu.get("output_tokens") or 0
    llm_usage.record(node, input_tokens, output_tokens, time.time() - t0)
    return resp

