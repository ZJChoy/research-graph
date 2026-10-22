"""来源可信度分级：域名层级 + 发布时间 + 跨来源交叉印证。

定位：不判断「这句话对不对」，只回答「这条证据有多硬」。
接地检查保证句子能在来源里找到；这里再标出这个来源本身是官方、
媒体还是自媒体，以及同一组数字有没有第二个独立域名佐证。
"""
import re
from collections import Counter
from urllib.parse import urlparse

from grounding import key_tokens

# 域名后缀匹配。分级是启发式，不是权威判定；报告里只作为提示。
TIERS = {
    "official": (
        "gov.cn", "edu.cn", "ac.cn", "ieee.org", "acm.org", "iso.org", "w3.org",
        "qualcomm.com", "nvidia.com", "arm.com", "intel.com", "amd.com",
        "apple.com", "mediatek.com", "huawei.com", "hisilicon.com",
        "horizon.auto", "cambricon.com", "blacksesame.com",
        "idc.com", "gartner.com", "counterpointresearch.com", "canalys.com",
        "omdia.com", "statista.com", "semianalysis.com", "yolegroup.com",
        "trendforce.com", "mercuryresearch.com",
    ),
    "media": (
        "xinhuanet.com", "news.cn", "people.com.cn", "caixin.com", "yicai.com",
        "21jingji.com", "jiqizhixin.com", "leiphone.com", "eet-china.com",
        "eefocus.com", "36kr.com", "huxiu.com", "thepaper.cn", "cls.cn",
        "stcn.com", "jiemian.com", "ifeng.com", "sina.com.cn",
    ),
    "blog": (
        "csdn.net", "zhihu.com", "juejin.cn", "cnblogs.com", "baijiahao.baidu.com",
        "toutiao.com", "book118.com", "docin.com", "sohu.com", "163.com",
        "qq.com", "aichipfront.com", "guijiagi.com", "iim.net.cn",
        "ones.com.cn", "pingcode.com", "github.io", "medium.com", "substack.com",
    ),
}
LABEL = {"official": "官方/机构", "media": "媒体", "blog": "自媒体", "unknown": "未知"}
SCORE = {"official": 3, "media": 2, "unknown": 1, "blog": 0}
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_PUB = re.compile(r"(20\d{2})\s*[-年/.]\s*\d{1,2}")


def domain(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except (ValueError, TypeError):
        return ""
    return host[4:] if host.startswith("www.") else host


def tier(url: str) -> str:
    host = domain(url)
    if not host:
        return "unknown"
    for name, suffixes in (("official", TIERS["official"]),
                           ("media", TIERS["media"]),
                           ("blog", TIERS["blog"])):
        if any(host == s or host.endswith("." + s) for s in suffixes):
            return name
    return "unknown"


def published_year(text: str) -> int | None:
    """从正文里抽最近的发布年份；抽不到返回 None。"""
    years = [int(y) for y in _PUB.findall(text or "")]
    return max(years) if years else None


def _signature(fact: str) -> frozenset:
    """可用于跨来源比对的硬 token：数字 + 含数字的型号，年份不算。"""
    out = set()
    for t in key_tokens(fact):
        if _YEAR.match(t):
            continue
        if t[0].isdigit() or any(c.isdigit() for c in t):
            out.add(t)
    return frozenset(out)


def corroboration(notes: list) -> list:
    """逐条返回「是否有另一个独立域名给出同一组硬 token」。

    要求共享至少 2 个 token，或 1 个 4 位以上的 token（如具体型号），
    避免「2025」「100」这类通用数字把不相干的事实判成互相印证。
    """
    sigs = [_signature(str(n.get("fact", ""))) for n in notes]
    hosts = [domain(str(n.get("url", ""))) for n in notes]
    out = []
    for i, sig in enumerate(sigs):
        ok = False
        if sig:
            for j, other in enumerate(sigs):
                if i == j or not hosts[j] or hosts[j] == hosts[i]:
                    continue
                shared = sig & other
                if len(shared) >= 2 or any(len(t) >= 4 for t in shared):
                    ok = True
                    break
        out.append(ok)
    return out


def annotate(notes: list) -> list:
    """给扁平笔记补上 tier / corroborated / published 三个字段。"""
    corr = corroboration(notes)
    out = []
    for i, n in enumerate(notes):
        item = dict(n)
        item["tier"] = tier(str(n.get("url", "")))
        item["corroborated"] = corr[i]
        item["published"] = published_year(str(n.get("content", "")) or str(n.get("fact", "")))
        out.append(item)
    return out


def summarize(notes: list) -> dict:
    """给运行快照用的汇总：来源层级分布 + 交叉印证条数。"""
    tiers = Counter(n.get("tier") or tier(str(n.get("url", ""))) for n in notes)
    corr = sum(1 for n in notes if n.get("corroborated"))
    return {
        "total_sources": len(notes),
        "tiers": dict(tiers),
        "corroborated": corr,
        "single_source": len(notes) - corr,
    }
