import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 测试永不联网、不读写真实缓存
os.environ["RESEARCH_GRAPH_NO_CACHE"] = "1"
os.environ.setdefault("DASHSCOPE_API_KEY", "test-key")
# 单元测试不跑断言核验（它会额外调用模型）；单独测 claim_verify 时再显式打开
os.environ.setdefault("CLAIM_VERIFY_ENABLED", "0")


@pytest.fixture
def workdir():
    """项目内临时目录：Windows 上系统 temp 可能不可写。"""
    d = ROOT / ".pytest_tmp" / uuid.uuid4().hex[:8]
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)
