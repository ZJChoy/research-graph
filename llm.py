"""统一的模型封装：全部节点共用这一个入口。"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

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
    )

