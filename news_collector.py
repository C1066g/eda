#!/usr/bin/env python3
"""
📈 A股新闻情报站 Pro — 抓取 + AI深度分析 + 受益股技术面联动

用法:
  python news_collector.py                              # 默认关键词
  python news_collector.py 宁德时代 比亚迪 AI芯片       # 自定义关注
  python news_collector.py --quick                      # 快速模式（不提取正文）

数据源: 东方财富 / 新浪财经 / 雪球
AI:    DeepSeek
技术面: yfinance
输出:   news_report.html（自动打开）
"""

import sys
import os
import json
import time
import re
import hashlib
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# yfinance 懒加载
_yf = None
def _get_yf():
    global _yf
    if _yf is None:
        try:
            import yfinance as _yf_mod
            _yf = _yf_mod
        except ImportError:
            _yf = False
    return _yf if _yf else None

# ── API 配置 ───────────────────────────────────────
DEEPSEEK_API_KEY = "sk-24d6f1ea55cf44518cdb570683e2e3d2"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# ── 关键词 ─────────────────────────────────────────
BUY_SIGNALS = [
    "涨停", "大涨", "暴涨", "连板", "封板",
    "业绩", "预增", "净利润", "营收", "财报", "扭亏",
    "利好", "政策", "新政", "国务院", "央行",
    "机构买入", "北向资金", "主力资金", "增持", "回购",
    "中标", "大单", "订单", "合同", "签约",
    "突破", "新高", "创新高", "放量",
    "重组", "并购", "收购", "资产注入",
    "AI", "人工智能", "芯片", "半导体", "新能源", "光伏",
    "华为", "特斯拉", "英伟达", "宁德时代", "比亚迪",
    "降息", "降准", "印花税",
    "超预期", "拐点",
    # 英文关键词（雅虎财经匹配用）
    "AI", "chip", "semiconductor", "breakout", "rally", "record",
    "upgrade", "downgrade", "buy", "sell", "target", "beat", "earnings",
    "revenue", "growth", "profit", "surge", "plunge", "crash",
    "bull", "bear", "ipo", "merger", "acquisition", "dividend",
    "nvidia", "apple", "tesla", "amd", "microsoft", "google", "meta",
    "amazon", "netflix", "intel", "qualcomm", "broadcom", "oracle",
    "salesforce", "adobe", "servicenow", "palantir", "crowdstrike",
]
EXCLUDE = ["八卦", "体育", "明星", "电竞"]

CACHE_DIR = Path.home() / ".cache" / "stock_news"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ═══════════════════════════════════════════════════
#  1. 新闻采集
# ═══════════════════════════════════════════════════

def fetch_eastmoney():
    """东方财富 RSS feed"""
    news = []
    for url in [
        "https://feed.eastmoney.com/a/2026_1_2.html",
        "https://feed.eastmoney.com/a/2026_1_1.html",
    ]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
            r.encoding = "utf-8"
            for a in BeautifulSoup(r.text, "lxml").find_all("a", href=True):
                t = a.get_text(strip=True)
                h = a["href"]
                if len(t) > 10 and h.startswith("http") and ("news" in h or ".html" in h):
                    news.append({"title": t, "url": h, "source": "东方财富"})
            time.sleep(0.3)
        except Exception:
            pass
    return news


def fetch_sina():
    """新浪财经 滚动API (4栏目)"""
    news = []
    for lid, label in {"2509": "国内财经", "2510": "国际财经",
                        "2674": "行情快报", "2669": "公司新闻"}.items():
        try:
            r = requests.get(
                "https://feed.mix.sina.com.cn/api/roll/get",
                params={"pageid": "153", "lid": lid, "k": "", "num": "15"},
                headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"},
                timeout=10,
            )
            for item in r.json().get("result", {}).get("data", []):
                t = item.get("title", "").strip()
                if t:
                    news.append({"title": t, "url": item.get("url", ""), "source": label})
            time.sleep(0.3)
        except Exception:
            pass
    return news


def fetch_xueqiu():
    """雪球 今日热门"""
    news = []
    try:
        s = requests.Session()
        s.get("https://xueqiu.com", headers={"User-Agent": UA}, timeout=10)
        r = s.get(
            "https://xueqiu.com/query/v1/status/hots.json",
            params={"count": "15", "scope": "day", "type": "stock"},
            headers={"User-Agent": UA}, timeout=10,
        )
        for item in r.json().get("data", []):
            t = BeautifulSoup(item.get("text", ""), "html.parser").get_text(strip=True)
            if t and len(t) > 5:
                news.append({
                    "title": t[:120],
                    "url": f"https://xueqiu.com/{item.get('user_id','')}/{item.get('id','')}",
                    "source": "雪球",
                })
    except Exception:
        pass
    return news


def fetch_yahoo_finance():
    """雅虎财经 — RSS feed 抓取（无需API，稳定可靠）"""
    news = []

    # 多条 RSS feed 覆盖不同维度
    rss_urls = [
        ("https://finance.yahoo.com/news/rssindex", "雅虎财经-头条"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=TSLA&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=AMD&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=MSFT&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=300750.SZ&region=US&lang=en-US", "雅虎财经"),
        ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=002594.SZ&region=US&lang=en-US", "雅虎财经"),
    ]

    seen_titles = set()
    for url, source_label in rss_urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
            soup = BeautifulSoup(r.text, "xml")
            for item in soup.find_all("item"):
                title = item.find("title")
                if not title:
                    continue
                t = title.get_text(strip=True)
                if t[:50] in seen_titles or len(t) < 10:
                    continue
                seen_titles.add(t[:50])

                link = item.find("link")
                desc = item.find("description")
                pub = item.find("pubDate")

                news.append({
                    "title": t,
                    "url": link.get_text(strip=True) if link else "",
                    "source": source_label,
                    "summary": BeautifulSoup(desc.get_text(strip=True) if desc else "", "html.parser").get_text()[:300] if desc else "",
                    "publish_time": pub.get_text(strip=True) if pub else "",
                })
        except Exception:
            pass

    # 统一 source 为雅虎财经
    for n in news:
        n["source"] = "雅虎财经"
    return news


def translate_english_news(news_list):
    """用 DeepSeek 批量翻译英文新闻标题为中文"""
    en_items = [n for n in news_list if n.get("source") == "雅虎财经" and re.search(r'[a-zA-Z]{3,}', n["title"])]
    if not en_items:
        return news_list

    print(f"  🌐 正在翻译 {len(en_items)} 条英文新闻...")
    batch_size = 10
    for i in range(0, len(en_items), batch_size):
        batch = en_items[i:i+batch_size]
        lines = "\n".join(f"{j+1}. {n['title']}" for j, n in enumerate(batch))
        prompt = f"将以下英文新闻标题翻译为中文简洁标题，保留关键信息（公司名、数字等用原文）。每行一条：\n\n{lines}\n\n返回格式：\n1. 中文标题\n2. 中文标题\n..."
        result = call_deepseek(prompt, "你是一个专业翻译，简洁准确。")
        if result:
            for line in result.strip().split("\n"):
                m = re.match(r'(\d+)\.\s*(.*)', line)
                if m:
                    idx = int(m.group(1)) - 1
                    if 0 <= idx < len(batch):
                        cn = m.group(2).strip()
                        if cn and len(cn) > 3:
                            batch[idx]["title_cn"] = cn
        time.sleep(0.5)
        print(f"    翻译 {min(i+batch_size, len(en_items))}/{len(en_items)}")

    # 对已翻译的，用中文标题展示
    for n in en_items:
        if n.get("title_cn"):
            n["title_original"] = n["title"]
            n["title"] = n["title_cn"]
    return news_list


def fetch_all():
    """聚合去重"""
    all_n = []
    for name, fn in [("东方财富", fetch_eastmoney),
                     ("新浪财经", fetch_sina),
                     ("雪球", fetch_xueqiu),
                     ("雅虎财经", fetch_yahoo_finance)]:
        print(f"  📡 {name}...", end=" ", flush=True)
        try:
            items = fn()
            print(f"{len(items)} 条")
            all_n.extend(items)
        except Exception as e:
            print(f"失败: {e}")

    seen = set()
    uniq = []
    for n in all_n:
        key = n["title"][:25]
        if key not in seen:
            seen.add(key)
            uniq.append(n)
    return uniq


# ═══════════════════════════════════════════════════
#  2. 正文提取 + 关键数据抽取
# ═══════════════════════════════════════════════════

def extract_article_text(url, timeout=8):
    """从新闻 URL 中提取正文（自适应多网站）"""
    if not url or url == "#":
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")
        # 移除无用标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 尝试多个常见正文选择器
        for sel in [
            ".article-body", ".article-content", ".main-content", "#article",
            ".text-body", ".content", ".news-content", "#content",
            ".detail-content", ".article-main", ".detail-text",
            "article", '[class*="content"]', '[class*="article"]',
        ]:
            els = soup.select(sel)
            if els:
                text = "\n".join(e.get_text(strip=True) for e in els if e.get_text(strip=True))
                if len(text) > 100:
                    return text[:3000]
        # fallback: body 文字
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            lines = [l for l in text.split("\n") if len(l) > 20]
            return "\n".join(lines[:50])[:3000]
    except Exception:
        pass
    return ""


def extract_key_data(text):
    """从正文中提取数字类关键数据（金额、百分比、日期等）"""
    data = {}
    # 金额：X亿元 / X万元 / $X
    amounts = re.findall(r'(\d+\.?\d*)\s*(亿|万?元|亿美元|亿人民币|\$?\d+亿)', text)
    if amounts:
        data["金额"] = [f"{a}{b}" for a, b in amounts[:5]]
    # 百分比涨跌幅
    pcts = re.findall(r'([+-]?\d+\.?\d*)\s*%', text)
    if pcts:
        data["百分比"] = pcts[:5]
    # 订单 / 产能 / 业绩数字
    for kw, label in [("订单", "订单"), ("产能", "产能"), ("营收", "营收"),
                      ("净利润", "净利润"), ("增长", "增长")]:
        nums = re.findall(rf'{kw}[^。]*?(\d+\.?\d*\s*(亿|万|%))', text)
        if nums:
            data[label] = [n[0] for n in nums[:3]]
    return data


def enrich_top_articles(news_list, top_n=15):
    """对前 N 条新闻提取正文 + 关键数据"""
    print(f"\n📄 正在提取 TOP {top_n} 条新闻正文...")
    count = 0
    for n in news_list[:top_n]:
        if count >= 8:  # 最多取8篇正文防止过慢
            break
        text = extract_article_text(n.get("url", ""))
        if text:
            n["full_text"] = text
            n["key_data"] = extract_key_data(text)
            count += 1
            print(f"  ✅ {n['title'][:40]}...")
        time.sleep(0.5)
    if count < top_n:
        print(f"  共提取 {count} 篇正文")
    return news_list


# ═══════════════════════════════════════════════════
#  3. 过滤 & 排序
# ═══════════════════════════════════════════════════

def score_news(news_list, custom_kw=None):
    kws = BUY_SIGNALS + (custom_kw or [])
    sw = {"东方财富": 1.2, "国内财经": 1.1, "公司新闻": 1.1,
          "行情快报": 1.0, "国际财经": 0.9, "雪球": 1.0,
          "雅虎财经": 1.15}

    for n in news_list:
        title = n["title"]
        n["matched_kws"] = []
        s = 0
        for kw in kws:
            if kw.lower() in title.lower():
                s += 2
                n["matched_kws"].append(kw)
        n["keyword_score"] = s
        n["weight"] = s * sw.get(n.get("source", ""), 1.0)

    news_list[:] = [n for n in news_list if not any(k in n["title"] for k in EXCLUDE)]
    news_list.sort(key=lambda x: x["weight"], reverse=True)
    return news_list


# ═══════════════════════════════════════════════════
#  4. AI 深度分析（DeepSeek）
# ═══════════════════════════════════════════════════

def call_deepseek(prompt, system="你是一个专业的A股财经分析师，分析简洁精准。"):
    for _ in range(3):
        try:
            r = requests.post(
                DEEPSEEK_URL,
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4096,
                },
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                         "Content-Type": "application/json"},
                timeout=60,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return ""


def ai_analyze_deep(news_list, custom_kw=None):
    """Phase 1: 单条深度分析（含正文/关键数据）"""
    batch_size = 10
    analyzed = []

    for i in range(0, len(news_list), batch_size):
        batch = news_list[i:i+batch_size]
        lines = []
        for j, n in enumerate(batch):
            t = n["title"]
            ft = n.get("full_text", "")[:500]
            kd = n.get("key_data", {})
            kd_str = f" 关键数据: {json.dumps(kd, ensure_ascii=False)}" if kd else ""
            lines.append(f"{j+1}. [{n['source']}] {t}{kd_str}")
            if ft:
                lines.append(f"   正文摘要: {ft[:300]}")

        kw_hint = f"\n用户特别关注: {', '.join(custom_kw)}" if custom_kw else ""
        prompt = f"""你是一个A股分析师。深度分析每条新闻：

返回JSON格式（严格JSON数组，无markdown包裹）：
[
  {{
    "index": 序号,
    "sentiment": "利好/利空/中性",
    "stocks": ["具体受益/受损股票代码，如NVDA、TSLA等，未知则空数组"],
    "sector": "影响的行业/板块",
    "score": 重要度1-10,
    "time_horizon": "短期/中期/长期",
    "reason": "一句话分析（<20字）"
  }}
]{kw_hint}

新闻：
{chr(10).join(lines)}"""

        result = call_deepseek(prompt)
        if result:
            result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                for r in json.loads(result):
                    idx = r["index"] - 1
                    if 0 <= idx < len(batch):
                        batch[idx]["sentiment"] = r.get("sentiment", "中性")
                        batch[idx]["stocks"] = r.get("stocks", [])
                        batch[idx]["sector"] = r.get("sector", "")
                        batch[idx]["ai_score"] = r.get("score", 5)
                        batch[idx]["time_horizon"] = r.get("time_horizon", "短期")
                        batch[idx]["reason"] = r.get("reason", "")
            except json.JSONDecodeError:
                pass

        for n in batch:
            n.setdefault("sentiment", "中性")
            n.setdefault("stocks", [])
            n.setdefault("sector", "")
            n.setdefault("ai_score", 3)
            n.setdefault("time_horizon", "短期")
            n.setdefault("reason", "")

        analyzed.extend(batch)
        print(f"  🤖 已分析 {len(analyzed)}/{len(news_list)} 条")
        time.sleep(0.5)

    for n in analyzed:
        n["final_score"] = n.get("keyword_score", 0) + n.get("ai_score", 0)
    analyzed.sort(key=lambda x: x["final_score"], reverse=True)
    return analyzed


def ai_summary(news_list, custom_kw=None):
    """Phase 2: 生成今日汇总 + 投资策略"""
    if not news_list:
        return {}

    top = news_list[:15]
    items_text = "\n".join(
        f"{i+1}. [{n['sentiment']}] [{n.get('sector','')}] {n['title'][:60]} — {n.get('reason','')}"
        for i, n in enumerate(top)
    )

    all_stocks = set()
    for n in top:
        for s in n.get("stocks", []):
            all_stocks.add(s.upper().strip())

    kw_hint = f"\n用户特别关注: {', '.join(custom_kw)}" if custom_kw else ""
    prompt = f"""你是一个A股首席策略分析师。基于今日重要新闻汇总，输出今日投资策略。

要求返回JSON格式:
{{
  "market_mood": "偏多/偏空/震荡",
  "hot_sectors": ["板块1", "板块2"],
  "focus_stocks": ["NVDA", "TSLA"]（限3-5个最值得关注的标的，用美股代码或A股代码）,
  "strategy": "一段今日操作策略建议（150字内）",
  "risk_warning": "一条风险提示（50字内）"
}}

今日TOP新闻：
{items_text}

AI分析出的候选股票: {', '.join(all_stocks) if all_stocks else "无"}
{kw_hint}"""

    result = call_deepseek(prompt, "你是一个A股首席策略分析师，给出精准可操作的策略。")
    if result:
        result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            pass
    return {"market_mood": "震荡", "hot_sectors": [], "focus_stocks": [], "strategy": "", "risk_warning": ""}


# ═══════════════════════════════════════════════════
#  5. yfinance 技术面联动
# ═══════════════════════════════════════════════════

# ── A股 → yfinance 映射 ──────────────────────────
_A_SHARE_MAP = {
    # 常用 A 股
    "002594": "002594.SZ", "300750": "300750.SZ", "000858": "000858.SZ",
    "600519": "600519.SS", "000333": "000333.SZ", "300059": "300059.SZ",
    "002415": "002415.SZ", "002230": "002230.SZ", "600887": "600887.SS",
    "601318": "601318.SS", "600036": "600036.SS", "000001": "000001.SZ",
    "002475": "002475.SZ", "300124": "300124.SZ", "688981": "688981.SS",
    "688126": "688126.SS", "300308": "300308.SZ", "300502": "300502.SZ",
    "688041": "688041.SS", "300433": "300433.SZ", "002920": "002920.SZ",
    "300274": "300274.SZ", "600030": "600030.SS", "601012": "601012.SS",
    "300296": "300296.SZ", "002371": "002371.SZ", "688012": "688012.SS",
    "300782": "300782.SZ", "688256": "688256.SS",
    # 港股
    "00992.HK": "0992.HK", "01810": "1810.HK", "00700": "0700.HK",
    "603779": "603779.SS",
}


def _normalize_ticker(raw):
    """将 AI 输出的代码转为 yfinance 可用格式"""
    t = raw.upper().strip().replace(" ", "")
    # 已经在映射表
    if t in _A_SHARE_MAP:
        return _A_SHARE_MAP[t]
    # A 股纯数字代码（6 位）
    if t.isdigit() and len(t) == 6:
        if t.startswith(("600", "601", "603", "605", "688")):
            return f"{t}.SS"
        return f"{t}.SZ"
    # 港股纯数字
    if t.isdigit() and len(t) == 5:
        return f"{t}.HK"
    if t.endswith(".HK") and not t.startswith(("0", "1", "2")):
        return t.zfill(5 + 3) if "." in t else t
    # US 代码直接返回
    if t.isalpha() and len(t) <= 5:
        return t
    return None


def _run_yfinance_subprocess(tickers):
    """在隔离子进程中执行 yfinance 查询"""
    # 构建子进程用的 Python 脚本
    script = r'''
import os, sys, json, time
import requests
from datetime import datetime, timedelta

# 仅 print JSON 结果到 stdout
tickers = __TICKERS__
try:
    import yfinance as yf
except ImportError:
    print("[]")
    sys.exit(0)

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0"
end = datetime.now()
start = end - timedelta(days=180)

time.sleep(30)
results = []
for t in tickers:
    time.sleep(5)
    try:
        df = yf.download(t, start=start, end=end, session=s, progress=False, auto_adjust=True)
        if df.empty: continue
        close = df["Close"].squeeze()
        if close.empty: continue
        last = float(close.iloc[-1])
        first = float(close.iloc[0])
        change = (last / first - 1) * 100
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.rolling(14).mean()
        al = loss.rolling(14).mean()
        rsi = 50.0
        if float(al.iloc[-1]) != 0:
            rsi = float((100 - 100 / (1 + ag / al)).iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else 0
        trend = "1" if sma20 > sma50 else "0"
        signals = []
        if rsi > 70: signals.append("超买")
        elif rsi < 30: signals.append("超卖")
        if last > sma20: signals.append("站上20日线")
        else: signals.append("跌破20日线")
        if sma50 > 0: signals.append("多头排列" if trend == "1" else "空头排列")
        results.append({
            "t": t, "p": round(last, 2), "c": round(change, 2),
            "r": round(rsi, 1), "t2": trend, "sg": signals
        })
    except Exception:
        pass
print(json.dumps(results))
'''
    script = script.replace("__TICKERS__", json.dumps(tickers))

    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=180,
        )
        raw = json.loads(proc.stdout.strip())
    except Exception:
        return []

    # 补充 info 字段
    yf_mod = _get_yf()
    results = []
    for r in raw:
        ticker = r["t"]
        name = ticker
        mcap_s = "N/A"
        pe_v = "N/A"
        if yf_mod:
            try:
                info = yf_mod.Ticker(ticker).info or {}
                name = info.get("shortName", ticker)
                mc = info.get("marketCap", 0)
                mcap_s = f"${mc/1e9:.1f}B" if mc else "N/A"
                pe_v = round(info.get("forwardPE") or info.get("trailingPE") or 0, 1)
            except Exception:
                pass
        results.append({
            "ticker": ticker, "name": name,
            "price": r["p"], "change_6m": r["c"],
            "rsi": r["r"], "sma20": 0, "sma50": None,
            "trend": "多头↑" if r["t2"] == "1" else "空头↓",
            "signals": r["sg"],
            "mcap": mcap_s, "pe": pe_v,
        })
    results.sort(key=lambda x: x["rsi"])
    return results


def check_stock_technicals(tickers):
    """查询股票技术面（带缓存，直接调用 yfinance）"""
    if not tickers:
        return []

    seen = set()
    normalized = []
    for t in tickers:
        nt = _normalize_ticker(t)
        if nt and nt not in seen:
            seen.add(nt)
            normalized.append(nt)
    normalized = normalized[:6]
    if not normalized:
        return []

    # 检查缓存
    cache_key = hashlib.md5("_".join(sorted(normalized)).encode()).hexdigest()
    cache_file = CACHE_DIR / f"tech_{cache_key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            cached_data = cached.get("data", [])
            if cached_data:
                ct = datetime.fromisoformat(cached["_time"])
                if datetime.now() - ct < timedelta(hours=1):
                    print(f"  📊 受益股技术面（缓存有效）")
                    return cached_data
        except Exception:
            pass

    print(f"  📊 受益股技术面: {normalized}")

    # 用子进程隔离 yfinance 调用（避免模块导入导致的限流干扰）
    result = _run_yfinance_subprocess(normalized)
    if result:
        try:
            cache_file.write_text(json.dumps({"_time": datetime.now().isoformat(), "data": result}, ensure_ascii=False))
        except Exception:
            pass
    return result


# ═══════════════════════════════════════════════════
#  6. HTML 报告（升级版）
# ═══════════════════════════════════════════════════

def build_html(news_list, summary, stock_techs, custom_kw=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y%m%d")
    top = news_list[:10]
    total = len(news_list)
    bullish = sum(1 for n in news_list if n.get("sentiment") == "利好")
    bearish = sum(1 for n in news_list if n.get("sentiment") == "利空")

    sm = {"利好": ("#e74c3c","#fde8e8"), "利空": ("#27ae60","#e8f5e9"), "中性": ("#f39c12","#fef6e7")}
    th_map = {"短期": "#e67e22", "中期": "#3498db", "长期": "#9b59b6"}
    src_colors = {
        "雅虎财经": ("#fff","#1565c0","rgba(21,101,192,.08)"),
        "东方财富": ("#fff","#e65100","rgba(230,81,0,.08)"),
        "雪球":     ("#fff","#2e7d32","rgba(46,125,50,.08)"),
    }

    kw_tags = ""
    if custom_kw:
        kw_tags = '<div style="margin-top:8px">' + \
                  "".join(f'<span class="tag">{k}</span>' for k in custom_kw) + "</div>"

    # ── 策略区 ──
    mood_icon = {"偏多": "🟢", "偏空": "🔴", "震荡": "🟡"}
    mi = mood_icon.get(summary.get("market_mood", "震荡"), "🟡")
    sectors_html = " ".join(f'<span class="tag">{s}</span>' for s in summary.get("hot_sectors", []))

    strategy_html = f"""
    <div class="strategy-card">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
            <span style="font-size:24px">{mi}</span>
            <span style="font-weight:600;font-size:16px">今日市场: {summary.get('market_mood','震荡')}</span>
            <span style="margin-left:auto;font-size:12px;color:#999">热点板块:</span>
            <span>{sectors_html}</span>
        </div>
        <div class="strategy-text">{summary.get('strategy','')}</div>
        {f'<div class="risk-warn">⚠️ {summary["risk_warning"]}</div>' if summary.get('risk_warning') else ''}
    </div>""" if summary else ""

    # ── 受益股票区 ──
    stocks_html = ""
    if stock_techs:
        rows = ""
        for s in stock_techs:
            sigs = " ".join(f'<span class="sig">{x}</span>' for x in s.get("signals", []))
            pe_str = f"{s['pe']}x" if s['pe'] != "N/A" else "N/A"
            chg_cls = "up" if s["change_6m"] > 0 else "down"
            rows += f"""
            <tr>
                <td><b>{s['ticker']}</b></td>
                <td>{s['name']}</td>
                <td>${s['price']:.2f}</td>
                <td class="{chg_cls}">{s['change_6m']:+.2f}%</td>
                <td>{s['rsi']}</td>
                <td>{s['trend']}</td>
                <td>{sigs}</td>
                <td>{pe_str}</td>
            </tr>"""

        focus_list = summary.get("focus_stocks", [])
        focus_str = " ".join(f'<span class="tag focus">{f}</span>' for f in focus_list) if focus_list else ""

        stocks_html = f"""
        <div style="background:#fff;border-radius:12px;padding:16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
            <div style="font-size:15px;font-weight:600;margin-bottom:10px;color:#1a1a2e">
                📊 AI精选关注 {focus_str}
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead>
                    <tr style="background:#f8f9fa">
                        <th style="padding:8px 6px;text-align:left">代码</th>
                        <th style="padding:8px 6px;text-align:left">名称</th>
                        <th style="padding:8px 6px;text-align:right">现价</th>
                        <th style="padding:8px 6px;text-align:right">6月</th>
                        <th style="padding:8px 6px;text-align:right">RSI</th>
                        <th style="padding:8px 6px;text-align:center">趋势</th>
                        <th style="padding:8px 6px;text-align:center">信号</th>
                        <th style="padding:8px 6px;text-align:right">P/E</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>"""

    # ── 新闻列表 ──
    items_html = ""
    for i, n in enumerate(top, 1):
        sent = n.get("sentiment", "中性")
        color, bg = sm.get(sent, ("#f39c12","#fef6e7"))
        kws = ", ".join(n.get("matched_kws", [])[:3])
        kw_line = f'<div class="kws">🔥 {kws}</div>' if kws else ""

        stocks_list = n.get("stocks", [])
        stock_tags = " ".join(f'<span class="stock-tag">{s}</span>' for s in stocks_list) if stocks_list else ""

        th = n.get("time_horizon", "")
        th_color = th_map.get(th, "#999")
        th_tag = f'<span class="th-tag" style="color:{th_color}">⏱ {th}</span>' if th else ""

        ft = n.get("full_text", "")
        ft_html = ""
        if ft:
            short = ft[:400]
            ft_html = f'<details><summary class="detail-summary">查看正文摘要</summary><div class="full-text">{short}{"..." if len(ft) > 400 else ""}</div></details>'

        # 来源颜色
        src_name = n.get("source", "?")
        if src_name in src_colors:
            sc_fg, sc_bg, sc_bg2 = src_colors[src_name]
            src_style = f'background:{sc_bg2};color:{sc_bg};font-weight:700'
        else:
            src_style = ""

        # 英文原标题
        orig_title = n.get("title_original", "")
        orig_html = f'<div class="orig-title">🌐 {orig_title}</div>' if orig_title else ""

        items_html += f"""
        <div class="item">
            <div class="rank">{i}</div>
            <div class="body">
                <div class="hdr">
                    <span class="src" style="{src_style}">{src_name}</span>
                    <span class="pill" style="background:{bg};color:{color}">{sent}</span>
                    <span class="sc">重要度 {n.get("ai_score","-")}/10</span>
                    {th_tag}
                </div>
                <div class="tit">{n["title"]}</div>
                {orig_html}
                {kw_line}
                {stock_tags}
                <div class="alz">
                    <b>影响:</b> {n.get("sector","-")} &nbsp;&nbsp;
                    <b>分析:</b> {n.get("reason","-")}
                </div>
                {ft_html}
                <div class="ftr"><a href="{n.get("url","#")}" target="_blank">查看原文 →</a></div>
            </div>
        </div>"""

    if not items_html:
        items_html = '<div class="empty"><div style="font-size:48px">📭</div><p>暂无匹配新闻</p></div>'

    # ── 统计卡片 ──
    neutral = total - bullish - bearish
    stats = f"""
    <div class="row">
        <div class="card"><div class="num">{total}</div><div class="lbl">总新闻</div></div>
        <div class="card"><div class="num" style="color:#e74c3c">{bullish}</div><div class="lbl">利好</div></div>
        <div class="card"><div class="num" style="color:#27ae60">{bearish}</div><div class="lbl">利空</div></div>
        <div class="card"><div class="num" style="color:#f39c12">{neutral}</div><div class="lbl">中性</div></div>
        <div class="card"><div class="num" style="color:#3498db">{len(top)}</div><div class="lbl">精选</div></div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang=zh-CN>
<head>
<meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>A股情报 Pro - {date_str}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f0f2f5;color:#333}}
.wrap{{max-width:860px;margin:0 auto;padding:14px}}
.head{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;border-radius:14px;padding:22px 26px;margin-bottom:14px}}
.head h1{{margin:0 0 4px;font-size:20px}}
.head .meta{{font-size:12px;opacity:.7;display:flex;justify-content:space-between}}
.tag{{display:inline-block;background:rgba(255,255,255,.15);border-radius:20px;padding:2px 12px;font-size:11px;margin:3px 3px 0 0;white-space:nowrap}}
.tag.focus{{background:#3498db;color:#fff}}
.row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px}}
.card{{background:#fff;border-radius:12px;padding:12px 4px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.num{{font-size:24px;font-weight:700}}
.lbl{{font-size:11px;color:#999;margin-top:2px}}

.strategy-card{{background:#fff;border-radius:12px;padding:16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);border-left:4px solid #3498db}}
.strategy-text{{font-size:14px;line-height:1.7;color:#444;padding:6px 0}}
.risk-warn{{margin-top:8px;padding:8px 12px;background:#fef6e7;border-radius:8px;font-size:13px;color:#e67e22;border-left:3px solid #f39c12}}

.item{{display:flex;background:#fff;border-radius:12px;margin-bottom:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.rank{{width:40px;background:#1a1a2e;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0}}
.body{{flex:1;padding:12px 14px;min-width:0}}
.hdr{{display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap}}
.src{{font-size:10px;color:#888;background:#f0f2f5;padding:1px 7px;border-radius:3px}}
.pill{{font-size:10px;font-weight:600;padding:1px 8px;border-radius:3px}}
.sc{{font-size:10px;color:#aaa;margin-left:auto}}
.th-tag{{font-size:10px;font-weight:600}}
.tit{{font-size:14px;font-weight:500;line-height:1.5;margin-bottom:4px}}
.kws{{font-size:11px;color:#e67e22;margin-bottom:4px}}
.orig-title{{font-size:11px;color:#888;font-style:italic;margin-bottom:3px}}
.stock-tag{{display:inline-block;background:#e8f4fd;color:#2980b9;border-radius:4px;padding:0 7px;font-size:10px;font-weight:600;margin:1px 2px}}
.alz{{font-size:12px;color:#555;line-height:1.6;margin-top:4px}}
.detail-summary{{font-size:11px;color:#3498db;cursor:pointer;margin-top:4px;user-select:none}}
.full-text{{font-size:11px;color:#777;line-height:1.6;margin-top:4px;padding:8px;background:#f8f9fa;border-radius:6px;max-height:200px;overflow-y:auto}}
.ftr{{margin-top:5px}}
.ftr a{{color:#3498db;font-size:11px;text-decoration:none}}
.empty{{text-align:center;padding:60px 20px;color:#999}}

table th{{font-size:11px;color:#888}}
table td{{padding:8px 6px;border-bottom:1px solid #f0f0f0}}
.up{{color:#e74c3c}}
.down{{color:#27ae60}}
.sig{{display:inline-block;font-size:9px;padding:1px 6px;border-radius:3px;margin:1px;background:#f0f2f5;color:#555}}

.footer{{text-align:center;padding:20px;color:#bbb;font-size:11px}}
@media(max-width:600px){{.row{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class=wrap>
<div class=head>
<h1>📈 A股情报站 Pro</h1>
<div class=meta>
    <span>{now}</span>
    <span>📊 {total} 条 · 利好 <b style=color:#e74c3c>{bullish}</b> · 利空 <b style=color:#27ae60>{bearish}</b></span>
</div>
{kw_tags}
</div>

{stats}
{strategy_html}
{stocks_html}

<div style="font-size:14px;font-weight:600;margin-bottom:10px;color:#1a1a2e">🏆 TOP {len(top)} 深度分析</div>
{items_html}

<div class=footer>数据: 东方财富 / 新浪财经 / 雪球 / 雅虎财经 &nbsp;|&nbsp; AI: DeepSeek &nbsp;|&nbsp; 技术面: yfinance</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════

def main():
    quick_mode = "--quick" in sys.argv
    custom_kw = [k.strip() for k in sys.argv[1:] if k.strip() and not k.startswith("--")]

    print("=" * 52)
    print("   📈  A股情报站 Pro — 深度分析")
    print("=" * 52)
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if custom_kw:
        print(f"   关注: {', '.join(custom_kw)}")
    if quick_mode:
        print("   快速模式（跳过正文提取）")
    print()

    # 1. 采集
    print("📡 正在采集新闻...")
    all_news = fetch_all()
    print(f"\n📊 共 {len(all_news)} 条（去重后）")

    if not all_news:
        print("⚠️  无数据。")
        Path("news_report_v3.html").write_text(build_html([], {}, [], custom_kw), encoding="utf-8")
        webbrowser.open(str(Path("news_report_v3.html").absolute()))
        return

    # 2. 翻译英文新闻
    if not quick_mode:
        all_news = translate_english_news(all_news)

    # 3. 过滤
    all_news = score_news(all_news, custom_kw)
    matched = [n for n in all_news if n["keyword_score"] > 0]
    top_unmatched = [n for n in all_news if n["keyword_score"] == 0][:20]
    candidates = matched + top_unmatched
    print(f"🔍 关键词匹配: {len(matched)} 条 → 进入分析: {len(candidates)} 条")

    # 5. AI 深度分析
    print("🤖 DeepSeek 深度分析中...")
    analyzed = ai_analyze_deep(candidates, custom_kw)

    # 6. AI汇总策略
    print("📝 正在生成汇总策略...")
    summary = ai_summary(analyzed, custom_kw)

    # 7. yfinance 技术面检查
    all_tickers = set()
    for n in analyzed:
        for s in n.get("stocks", []):
            all_tickers.add(s.upper().strip())
    # 加上策略推荐
    for s in summary.get("focus_stocks", []):
        all_tickers.add(s.upper().strip())

    stock_techs = []
    if all_tickers:
        print(f"📊 正在检查 {len(all_tickers)} 个受益股技术面...")
        stock_techs = check_stock_technicals(list(all_tickers)[:12])
        print(f"   ✅ {len(stock_techs)} 个股票分析完成")

    # 8. 报告
    path = Path("news_report_v3.html").absolute()
    html = build_html(analyzed, summary, stock_techs, custom_kw)
    path.write_text(html, encoding="utf-8")
    webbrowser.open(str(path))

    # ── 终端输出 ──
    print(f"\n{'='*52}")
    print(f"   📋 今日TOP{min(10, len(analyzed))} 深度简报")
    print(f"{'='*52}")
    icons = {"利好": "🟢", "利空": "🔴", "中性": "🟡"}
    for n in analyzed[:10]:
        icon = icons.get(n.get("sentiment", ""), "⚪")
        stocks = ", ".join(n.get("stocks", [])[:3])
        print(f"\n  {icon}  [{n.get('source','?')}] {n['title'][:60]}")
        print(f"     {n.get('sentiment','?')} | {n.get('sector','-')} | 重要度{n.get('ai_score','-')} | {n.get('time_horizon','')}")
        if stocks:
            print(f"     📌 相关: {stocks}")
        if n.get("reason"):
            print(f"     💡 {n['reason']}")

    if summary:
        print(f"\n{'─'*52}")
        print(f"  📊 综合策略 | 市场: {summary.get('market_mood','?')}")
        print(f"  热点: {'/'.join(summary.get('hot_sectors',[]))}")
        if summary.get("strategy"):
            print(f"  💬 {summary['strategy'][:120]}")
    if stock_techs:
        print(f"\n{'─'*52}")
        print(f"  📊 AI精选股票技术面状态:")
        for s in stock_techs[:5]:
            sigs = "|".join(s.get("signals", []))
            print(f"  {s['ticker']:>6}  ${s['price']:>7.2f}  RSI:{s['rsi']:>5.1f}  {s['trend']}  {sigs}")

    print(f"\n{'='*52}")
    print(f"  ✅ 简报: {path}")
    print(f"{'='*52}")


if __name__ == "__main__":
    main()
