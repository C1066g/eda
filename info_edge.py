#!/usr/bin/env python3
"""
🔍 信息差挖掘工具 — 抢先捕捉市场异动

原理：市场定价需要时间，信息传播有先后。
找到「大部分人还没注意到」的信号，就是信息差。

用法:
  python info_edge.py                          # 全量扫描
  python info_edge.py --fast                   # 仅快讯（跳过深度数据）
  python info_edge.py --ticker NVDA            # 盯盘特定股票

输出: info_edge_report.html（自动打开）
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

# ── API ──
DEEPSEEK_KEY = "sk-24d6f1ea55cf44518cdb570683e2e3d2"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
CACHE_DIR = Path.home() / ".cache" / "info_edge"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_yf = None
def _get_yf():
    global _yf
    if _yf is None:
        try:
            import yfinance as _m
            _yf = _m
        except ImportError:
            _yf = False
    return _yf if _yf else None


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def _call_deepseek(prompt, sys_msg="你是一个敏锐的A股量化分析师，擅长从杂音中发现信号。"):
    for _ in range(3):
        try:
            r = requests.post(DEEPSEEK_URL, json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}, timeout=60)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return ""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ═══════════════════════════════════════════════════════
#  1. 快讯采集（最快信号）
# ═══════════════════════════════════════════════════════

def fetch_eastmoney_flash():
    """东方财富 7x24小时快讯"""
    items = []
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            params={
                "fields": "f58,f12,f14,f2,f3,f62,f184,f66,f69",
                "secids": "1.000001,0.399001,0.399006,1.000300",
                "fltt": "2",
                "cb": "j",
                "_": int(time.time() * 1000),
            },
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com"},
            timeout=8,
        )
        # Try the news flash API
        r2 = requests.get(
            "https://kuaixun.eastmoney.com/",
            headers={"User-Agent": UA},
            timeout=8,
        )
        r2.encoding = "utf-8"
        soup = BeautifulSoup(r2.text, "lxml")
        for li in soup.select("ul.list li, .news-item, li"):
            t = li.get_text(strip=True)
            if len(t) > 15:
                items.append({"title": t[:200], "source": "东方快讯", "time": _now(), "type": "flash"})
    except Exception:
        pass
    return items


def fetch_eastmoney_kuaixun_api():
    """东方财富 API 快讯"""
    items = []
    urls = [
        "https://push2ex.eastmoney.com/getStockNews?pageindex=0&pagesize=30",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com"}, timeout=8)
            data = r.json()
            for item in data.get("data", []):
                t = item.get("title", "").strip()
                if t and len(t) > 10:
                    items.append({
                        "title": t,
                        "url": item.get("url", "") or item.get("shareurl", ""),
                        "source": "东方快讯",
                        "time": _now(),
                        "type": "flash",
                    })
        except Exception:
            pass
    return items


def fetch_sina_flash():
    """新浪实时快讯"""
    items = []
    try:
        r = requests.get(
            "https://feed.mix.sina.com.cn/api/roll/get",
            params={"pageid": "153", "lid": "2510", "k": "", "num": "20"},
            headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"},
            timeout=8,
        )
        for item in r.json().get("result", {}).get("data", []):
            t = item.get("title", "").strip()
            if t:
                items.append({
                    "title": t,
                    "url": item.get("url", ""),
                    "source": "新浪快讯",
                    "time": item.get("ctime", _now()),
                    "type": "flash",
                })
    except Exception:
        pass
    return items


def fetch_yahoo_breaking():
    """雅虎财经 RSS + 实时新闻"""
    items = []
    for url in [
        "https://finance.yahoo.com/news/rssindex",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AAPL,TSLA,AMD&region=US&lang=en-US",
    ]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
            for item in BeautifulSoup(r.text, "xml").find_all("item"):
                t = item.find("title")
                if t and len(t.get_text(strip=True)) > 10:
                    link = item.find("link")
                    desc = item.find("description")
                    items.append({
                        "title": t.get_text(strip=True),
                        "url": link.get_text(strip=True) if link else "",
                        "summary": BeautifulSoup(desc.get_text(strip=True) if desc else "", "html.parser").get_text()[:200] if desc else "",
                        "source": "雅虎快讯",
                        "time": _now(),
                        "type": "flash",
                    })
        except Exception:
            pass
    return items


def fetch_reuters_rss():
    """Reuters RSS"""
    items = []
    for url in [
        "https://www.investing.com/rss/news.rss",
        "https://www.investing.com/rss/market_overview.rss",
    ]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
            for item in BeautifulSoup(r.text, "xml").find_all("item"):
                t = item.find("title")
                if t and len(t.get_text(strip=True)) > 10:
                    items.append({
                        "title": t.get_text(strip=True)[:200],
                        "url": item.find("link").get_text(strip=True) if item.find("link") else "",
                        "source": "Reuters",
                        "time": _now(),
                        "type": "flash",
                    })
        except Exception:
            pass
    return items


def fetch_all_flash():
    """聚合所有快讯"""
    all_n = []
    for name, fn in [
        ("东方快讯", fetch_eastmoney_kuaixun_api),
        ("新浪快讯", fetch_sina_flash),
        ("雅虎快讯", fetch_yahoo_breaking),
        ("Reuters", fetch_reuters_rss),
    ]:
        print(f"  ⚡ {name}...", end=" ", flush=True)
        try:
            items = fn()
            print(f"{len(items)} 条")
            all_n.extend(items)
        except Exception as e:
            print(f"失败: {e}")

    seen = set()
    uniq = []
    for n in all_n:
        key = n["title"][:30]
        if key not in seen:
            seen.add(key)
            uniq.append(n)
    return uniq


# ═══════════════════════════════════════════════════════
#  2. 深度数据采集（SEC、港交所、龙虎榜等）
# ═══════════════════════════════════════════════════════

def fetch_sec_filings():
    """SEC EDGAR 最新 filings（检测内部人交易、大额异动）"""
    items = []
    try:
        url = "https://efts.sec.gov/LATEST/search-index?dateRange=custom&startdt=2026-01-01&enddt=2026-12-31&category=form-CURRENT&count=10"
        r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=only&start=0&count=10&output=atom",
                         headers={"User-Agent": "Sample/1.0 (contact@example.com)"}, timeout=10)
        soup = BeautifulSoup(r.text, "xml")
        for entry in soup.find_all("entry")[:10]:
            title = entry.find("title")
            link = entry.find("link")
            if title:
                items.append({
                    "title": title.get_text(strip=True)[:200],
                    "url": link.get("href", "") if link else "",
                    "source": "SEC",
                    "time": _now(),
                    "type": "insider",
                })
    except Exception:
        pass
    # Fallback: 用 yfinance 查 insider
    yf = _get_yf()
    if yf and not items:
        for t in ["NVDA", "AAPL", "TSLA", "AMD", "MSFT"]:
            try:
                tk = yf.Ticker(t)
                inst = getattr(tk, "institutional_holders", None)
                if inst is not None and not inst.empty:
                    for _, row in inst.head(3).iterrows():
                        items.append({
                            "title": f"{t} 机构持仓: {row.get('Holder', '?')} 持有 {row.get('Shares', 0)} 股",
                            "url": f"https://finance.yahoo.com/quote/{t}/holders",
                            "source": "YF机构持仓",
                            "time": _now(),
                            "type": "insider",
                        })
                time.sleep(1)
            except Exception:
                pass
    return items


def fetch_hk_exchange():
    """港交所权益披露模拟（实际使用需要 API Key, 这里用公开数据）"""
    items = []
    # 港交所披露易 RSS
    try:
        r = requests.get("https://www.hkexnews.hk/revelation/cio6cj004_getRSS.htm",
                         headers={"User-Agent": UA}, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        for item in soup.find_all("item")[:8]:
            t = item.find("title")
            if t:
                items.append({
                    "title": t.get_text(strip=True)[:200],
                    "url": item.find("link").get_text(strip=True) if item.find("link") else "",
                    "source": "港交所",
                    "time": _now(),
                    "type": "insider",
                })
    except Exception:
        pass
    return items


def fetch_longhubang():
    """龙虎榜数据（东方财富接口）"""
    items = []
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "10", "po": "1", "np": "1",
                "fields": "f12,f14,f3,f62,f184,f66,f69,f70,f78",
                "fid": "f3",
                "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2",
            },
            headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"},
            timeout=8,
        )
        data = r.json()
        for item in data.get("data", {}).get("diff", [])[:10]:
            name = item.get("f14", "")
            chg = item.get("f3", 0)
            if name:
                items.append({
                    "title": f"龙虎榜: {name} 涨跌幅 {chg:+.2f}% 上榜",
                    "url": f"https://data.eastmoney.com/stock/{item.get('f12','')}.html",
                    "source": "龙虎榜",
                    "time": _now(),
                    "type": "depth",
                })
    except Exception:
        pass
    return items


def fetch_block_trades():
    """大宗交易"""
    items = []
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "10", "po": "1", "np": "1",
                "fields": "f12,f14,f2,f3,f4,f5,f6,f7,f8",
                "fid": "f3",
                "fs": "m:0+t:1+f:!2",
            },
            headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"},
            timeout=8,
        )
        data = r.json()
        for item in data.get("data", {}).get("diff", [])[:10]:
            name = item.get("f14", "")
            price = item.get("f2", 0)
            if name:
                items.append({
                    "title": f"大宗交易: {name} 成交价¥{price}",
                    "url": f"https://data.eastmoney.com/stock/{item.get('f12','')}.html",
                    "source": "大宗交易",
                    "time": _now(),
                    "type": "depth",
                })
    except Exception:
        pass
    return items


def fetch_margin_data():
    """融资融券变化（东方财富）"""
    items = []
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "10", "po": "1", "np": "1",
                "fields": "f12,f14,f4,f6,f8,f10,f12",
                "fid": "f4",
                "fs": "m:0+t:68+f:!2",
            },
            headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"},
            timeout=8,
        )
        data = r.json()
        for item in data.get("data", {}).get("diff", [])[:8]:
            name = item.get("f14", "")
            chg = item.get("f4", 0)
            if name and abs(chg) > 0.01:
                direction = "加杠杆" if chg > 0 else "去杠杆"
                items.append({
                    "title": f"两融异动: {name} 融资净{direction} ¥{abs(chg):.2f}亿",
                    "url": f"https://data.eastmoney.com/stock/{item.get('f12','')}.html",
                    "source": "两融数据",
                    "time": _now(),
                    "type": "depth",
                })
    except Exception:
        pass
    return items


def fetch_market_watch():
    """MarketWatch 热点"""
    items = []
    try:
        r = requests.get("https://www.marketwatch.com/latest-news",
                         headers={"User-Agent": UA}, timeout=8)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a[href*='/story']")[:10]:
            t = a.get_text(strip=True)
            href = a.get("href", "")
            if t and len(t) > 20:
                items.append({
                    "title": t[:200],
                    "url": f"https://www.marketwatch.com{href}" if href.startswith("/") else href,
                    "source": "MarketWatch",
                    "time": _now(),
                    "type": "flash",
                })
    except Exception:
        pass
    return items


def fetch_all_depth():
    """聚合所有深度数据"""
    all_n = []
    for name, fn in [
        ("SEC", fetch_sec_filings),
        ("港交所", fetch_hk_exchange),
        ("龙虎榜", fetch_longhubang),
        ("大宗交易", fetch_block_trades),
        ("两融数据", fetch_margin_data),
        ("MarketWatch", fetch_market_watch),
    ]:
        print(f"  📡 {name}...", end=" ", flush=True)
        try:
            items = fn()
            print(f"{len(items)} 条")
            all_n.extend(items)
        except Exception as e:
            print(f"失败: {e}")
    return all_n


# ═══════════════════════════════════════════════════════
#  3. 信息差识别（DeepSeek 分析）
# ═══════════════════════════════════════════════════════

def analyze_edge(items):
    """分析每条信息是否属于信息差，并分类"""
    if not items:
        return items

    print(f"\n🔍 DeepSeek 正在分析 {len(items)} 条信号中...")

    batch_size = 12
    analyzed = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i+batch_size]
        lines = "\n".join(
            f"{j+1}. [{n['source']}] {n['title'][:120]}" for j, n in enumerate(batch)
        )
        prompt = f"""分析以下每条市场信息，判断是否存在「信息差」机会。

信息差类型定义：
- 提前泄露: 公告前股价或成交量异常，或尚未正式公告的重要消息
- 认知差: 市场普遍忽视的利好/利空，大多数人还没意识到
- 时间差: 海外已发酵但A股尚未反应，或盘后消息
- 数据差: 财报/公告中容易被忽略的关键数据

对每条信息返回JSON：
[
  {{
    "index": 序号,
    "is_edge": true/false,
    "edge_type": "提前泄露/认知差/时间差/数据差",
    "tickers": ["相关股票代码，未知则空数组"],
    "urgency": 1-10（10=马上行动）,
    "reason": "为什么是信息差（<30字）",
    "time_window": "几小时内/1-2天/本周"
  }}
]

只返回JSON数组，不要markdown包裹。

信息：
{lines}"""

        result = _call_deepseek(prompt)
        if result:
            result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                for r in json.loads(result):
                    idx = r["index"] - 1
                    if 0 <= idx < len(batch):
                        batch[idx]["is_edge"] = r.get("is_edge", False)
                        batch[idx]["edge_type"] = r.get("edge_type", "")
                        batch[idx]["edge_tickers"] = r.get("tickers", [])
                        batch[idx]["urgency"] = r.get("urgency", 5)
                        batch[idx]["edge_reason"] = r.get("reason", "")
                        batch[idx]["time_window"] = r.get("time_window", "")
            except json.JSONDecodeError:
                pass

        for n in batch:
            n.setdefault("is_edge", False)
            n.setdefault("edge_type", "")
            n.setdefault("edge_tickers", [])
            n.setdefault("urgency", 5)
            n.setdefault("edge_reason", "")
            n.setdefault("time_window", "")

        analyzed.extend(batch)
        print(f"  🔍 已分析 {len(analyzed)}/{len(items)} 条")

    # 排序：只保留 is_edge=True 的，按 urgency 降序
    edges = [n for n in analyzed if n.get("is_edge")]
    edges.sort(key=lambda x: x.get("urgency", 0), reverse=True)
    return edges


# ═══════════════════════════════════════════════════════
#  4. 盯盘特定股票（--ticker）
# ═══════════════════════════════════════════════════════

def check_ticker_anomalies(ticker):
    """针对单只股票检查异常信号"""
    print(f"\n🎯 盯盘 {ticker} 专项扫描...")
    signals = []
    yf = _get_yf()
    if not yf:
        return signals

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}

        # 现价 & 变化
        price = info.get("regularMarketPrice", info.get("currentPrice", 0))
        prev_close = info.get("regularMarketPreviousClose", 0)
        if price and prev_close:
            chg = (price / prev_close - 1) * 100
            if abs(chg) > 3:
                signals.append(f"⚠️ 股价异动: 当前${price:.2f} vs 昨收${prev_close:.2f} ({chg:+.2f}%)")

        # 成交量异常
        vol = info.get("regularMarketVolume", 0)
        avg_vol = info.get("averageVolume", 0)
        if vol and avg_vol and vol > avg_vol * 2:
            signals.append(f"📊 放量{vol/avg_vol:.1f}x: 今日{vol/1e6:.1f}M vs 日均{avg_vol/1e6:.1f}M")

        # RSI
        try:
            df = tk.history(period="6mo")
            if not df.empty:
                close = df["Close"]
                delta = close.diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                ag = gain.rolling(14).mean()
                al = loss.rolling(14).mean()
                rsi = float((100 - 100 / (1 + ag / al)).iloc[-1])
                if rsi > 75:
                    signals.append(f"🔥 RSI={rsi:.0f} 超买区，注意回调风险")
                elif rsi < 25:
                    signals.append(f"🧊 RSI={rsi:.0f} 超卖区，反弹机会")
        except Exception:
            pass

        # 做空比例
        short_ratio = info.get("shortRatio", 0)
        if short_ratio > 5:
            signals.append(f"📉 做空比率{short_ratio:.1f}，极高做空压力")
        elif short_ratio > 2:
            signals.append(f"📉 做空比率{short_ratio:.1f}，存在轧空可能")

        # 分析师目标价
        target = info.get("targetMeanPrice", 0)
        if target and price:
            upside = (target / price - 1) * 100
            if abs(upside) > 20:
                signals.append(f"🎯 分析师目标${target:.0f}，较现价{upside:+.0f}%空间")

        # 内部人交易
        try:
            ins = tk.insider_transactions
            if ins is not None and not ins.empty:
                recent = ins.head(3)
                for _, r in recent.iterrows():
                    signals.append(f"🏦 内部人{r.get('Transaction','')}: {r.get('Shares',0)}股@{r.get('Value',0)}")
        except Exception:
            pass

    except Exception as e:
        signals.append(f"❌ 获取失败: {e}")

    return signals


# ═══════════════════════════════════════════════════════
#  5. HTML 报告
# ═══════════════════════════════════════════════════════

EDGE_COLORS = {
    "提前泄露": ("#e74c3c", "#fde8e8"),
    "认知差": ("#2980b9", "#e8f4fd"),
    "时间差": ("#e67e22", "#fef6e7"),
    "数据差": ("#27ae60", "#e8f5e9"),
}
SRC_COLORS = {
    "东方快讯": ("#e65100", "#fff3e0"),
    "新浪快讯": ("#1565c0", "#e3f2fd"),
    "雅虎快讯": ("#0d47a1", "#e3f2fd"),
    "Reuters": ("#000", "#f5f5f5"),
    "MarketWatch": ("#1a237e", "#e8eaf6"),
    "SEC": ("#b71c1c", "#ffebee"),
    "港交所": ("#1b5e20", "#e8f5e9"),
    "龙虎榜": ("#f57c00", "#fff3e0"),
    "大宗交易": ("#6a1b9a", "#f3e5f5"),
    "两融数据": ("#00838f", "#e0f7fa"),
    "YF机构持仓": ("#37474f", "#eceff1"),
}


def build_html(edges, flash_count, depth_count, ticker_signals=None, watch_ticker=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y%m%d")

    # 统计
    total = len(edges)
    edge_types = {}
    for e in edges:
        et = e.get("edge_type", "未知")
        edge_types[et] = edge_types.get(et, 0) + 1
    high_urgency = sum(1 for e in edges if e.get("urgency", 0) >= 8)

    # 策略区域
    if edges:
        top_signals = "\n".join(
            f"{i+1}. [{e['edge_type']}] [{e.get('source','')}] {e['title'][:80]} — urgency={e.get('urgency',0)}"
            for i, e in enumerate(edges[:10])
        )
        prompt = f"""你是首席交易员。基于以下信息差信号，给出今日交易策略。

返回JSON：
{{
  "verdict": "一句话市场判断",
  "strategy": "具体操作建议（100字内）",
  "risk": "最大风险警示（30字）"
}}

信号：
{top_signals}"""
        result = _call_deepseek(prompt, "你是华尔街交易员，决策果断，逻辑清晰。")
        strategy_json = {}
        if result:
            result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                strategy_json = json.loads(result)
            except json.JSONDecodeError:
                pass

        verdict = strategy_json.get("verdict", "")
        strategy = strategy_json.get("strategy", "")
        risk = strategy_json.get("risk", "")
    else:
        verdict = "暂无明确信息差信号"
        strategy = "建议维持现有仓位，等待更明确信号。"
        risk = "N/A"

    # 看板统计
    stats = f"""
    <div class="row">
        <div class="card"><div class="num">{total}</div><div class="lbl">信息差</div></div>
        <div class="card"><div class="num" style="color:#e74c3c">{edge_types.get('提前泄露',0)}</div><div class="lbl">提前泄露</div></div>
        <div class="card"><div class="num" style="color:#2980b9">{edge_types.get('认知差',0)}</div><div class="lbl">认知差</div></div>
        <div class="card"><div class="num" style="color:#e67e22">{edge_types.get('时间差',0)}</div><div class="lbl">时间差</div></div>
        <div class="card"><div class="num" style="color:#27ae60">{edge_types.get('数据差',0)}</div><div class="lbl">数据差</div></div>
    </div>"""

    # 策略卡片
    strat_html = f"""
    <div class="strat">
        <div class="strat-v">{verdict}</div>
        <div class="strat-t">{strategy}</div>
        <div class="strat-r">⚠️ {risk}</div>
    </div>"""

    # Tickker 盯盘
    ticker_html = ""
    if ticker_signals:
        items = "".join(f'<div class="tsig">🔔 {s}</div>' for s in ticker_signals)
        ticker_html = f"""
        <div class="ticker-box">
            <div class="ticker-hdr">🎯 {watch_ticker} 盯盘信号</div>
            {items}
        </div>"""

    # 时间轴
    timeline = ""
    for i, e in enumerate(edges[:15], 1):
        et = e.get("edge_type", "")
        tc, tb = EDGE_COLORS.get(et, ("#888", "#f0f0f0"))
        src = e.get("source", "?")
        sc = SRC_COLORS.get(src, ("#555", "#f5f5f5"))

        tickers = e.get("edge_tickers", [])
        ttags = " ".join(f'<span class="tt">{t}</span>' for t in tickers) if tickers else ""

        urgency = e.get("urgency", 0)
        urgency_bar = f'<span class="ubar" style="width:{urgency*10}%"></span>' if urgency else ""

        timeline += f"""
        <div class="edge-item urgency-{urgency // 3 if urgency else 1}">
            <div class="edge-num">{i}</div>
            <div class="edge-body">
                <div class="edge-hdr">
                    <span class="esrc" style="color:{sc[0]};background:{sc[1]}">{src}</span>
                    <span class="epill" style="color:{tc};background:{tb}">{et}</span>
                    <span class="eurge">紧迫度 {urgency}/10 {urgency_bar}</span>
                </div>
                <div class="edge-title">{e['title']}</div>
                {ttags}
                <div class="edge-reason">
                    💡 {e.get('edge_reason','')}
                    <span class="tw">{e.get('time_window','')}</span>
                </div>
                {f'<div class="edge-ftr"><a href="{e["url"]}" target="_blank">来源 →</a></div>' if e.get("url") else ""}
            </div>
        </div>"""

    if not timeline:
        timeline = '<div class="empty"><div style="font-size:48px">🔍</div><p>暂未发现明显信息差信号</p></div>'

    return f"""<!DOCTYPE html>
<html lang=zh-CN>
<head>
<meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>信息差报告 {date_str}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0a0a1a;color:#e0e0e0}}
.wrap{{max-width:860px;margin:0 auto;padding:14px}}
.head{{background:linear-gradient(135deg,#0d0d2b,#1a1a4e);border-radius:14px;padding:22px 26px;margin-bottom:14px;border:1px solid rgba(100,100,255,.15)}}
.head h1{{margin:0;font-size:20px;color:#fff}}
.head .meta{{font-size:12px;color:#888;display:flex;justify-content:space-between;margin-top:4px}}
.tag{{display:inline-block;background:rgba(100,100,255,.15);color:#8ab4ff;border-radius:20px;padding:2px 12px;font-size:11px;margin:3px 3px 0 0;white-space:nowrap}}

.row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px}}
.card{{background:#13132b;border-radius:12px;padding:12px 4px;text-align:center;border:1px solid rgba(100,100,255,.08)}}
.num{{font-size:24px;font-weight:700;color:#8ab4ff}}
.lbl{{font-size:11px;color:#666;margin-top:2px}}

.strat{{background:linear-gradient(135deg,#13132b,#1a1a3e);border-radius:12px;padding:16px;margin-bottom:14px;border-left:4px solid #8ab4ff}}
.strat-v{{font-size:16px;font-weight:600;color:#8ab4ff;margin-bottom:6px}}
.strat-t{{font-size:13px;line-height:1.7;color:#aaa}}
.strat-r{{margin-top:8px;font-size:12px;color:#e74c3c}}

.ticker-box{{background:#13132b;border-radius:12px;padding:16px;margin-bottom:14px;border:1px solid rgba(255,100,100,.15)}}
.ticker-hdr{{font-size:14px;font-weight:600;color:#ff6b6b;margin-bottom:8px}}
.tsig{{padding:6px 10px;margin-bottom:4px;background:rgba(255,100,100,.08);border-radius:6px;font-size:13px;color:#ccc}}

.edge-item{{display:flex;background:#13132b;border-radius:12px;margin-bottom:8px;overflow:hidden;border:1px solid rgba(100,100,255,.06)}}
.edge-num{{width:36px;background:#0d0d2b;color:#8ab4ff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;flex-shrink:0}}
.edge-body{{flex:1;padding:12px 14px;min-width:0}}
.edge-hdr{{display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap}}
.esrc{{font-size:9px;padding:1px 7px;border-radius:3px;font-weight:600}}
.epill{{font-size:10px;font-weight:600;padding:1px 8px;border-radius:3px}}
.eurge{{font-size:10px;color:#666;margin-left:auto;display:flex;align-items:center;gap:4px}}
.ubar{{display:inline-block;height:4px;background:linear-gradient(90deg,#8ab4ff,#e74c3c);border-radius:2px;vertical-align:middle}}
.edge-title{{font-size:13px;font-weight:500;line-height:1.5;margin-bottom:4px;color:#eee}}
.tt{{display:inline-block;background:rgba(100,100,255,.12);color:#8ab4ff;border-radius:3px;padding:0 6px;font-size:10px;margin:1px 2px}}
.edge-reason{{font-size:11px;color:#888;line-height:1.5;margin-top:4px}}
.tw{{font-size:10px;color:#666;margin-left:8px}}
.edge-ftr{{margin-top:5px}}
.edge-ftr a{{color:#5a7db0;font-size:10px;text-decoration:none}}
.empty{{text-align:center;padding:60px 20px;color:#555}}

.footer{{text-align:center;padding:20px;color:#444;font-size:11px}}
@media(max-width:600px){{.row{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class=wrap>
<div class=head>
<h1>🔍 信息差雷达</h1>
<div class=meta>
    <span>{now}</span>
    <span>⚡{flash_count}条快讯 📡{depth_count}条深度 🔍{total}个信号</span>
</div>
</div>

{stats}
{strat_html}
{ticker_html}

<div style="font-size:14px;font-weight:600;margin-bottom:10px;color:#8ab4ff">⏱ 信息差时间轴（按紧迫度排序）</div>
{timeline}

<div class=footer>数据: 东方快讯/新浪/雅虎/Reuters/SEC/港交所/龙虎榜/大宗/两融 &nbsp;|&nbsp; 分析: DeepSeek</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    fast_mode = "--fast" in sys.argv
    watch_ticker = ""
    for i, a in enumerate(sys.argv):
        if a == "--ticker" and i + 1 < len(sys.argv):
            watch_ticker = sys.argv[i + 1].upper()

    print("=" * 54)
    print("   🔍  信息差挖掘工具 — 发现市场盲点")
    print("=" * 54)
    print(f"   {_now()}")
    if fast_mode:
        print("   快速模式（仅快讯）")
    if watch_ticker:
        print(f"   盯盘: {watch_ticker}")
    print()

    # 1. 快讯采集
    print("📡 采集快讯...")
    flash_news = fetch_all_flash()
    print(f"\n⚡ 快讯共 {len(flash_news)} 条")

    # 2. 深度数据
    depth_data = []
    if not fast_mode:
        print("\n📡 采集深度数据...")
        depth_data = fetch_all_depth()
        print(f"\n📊 深度数据共 {len(depth_data)} 条")

    # 合并
    all_signals = flash_news + depth_data

    if not all_signals:
        print("⚠️  无数据")
        Path("info_edge_report.html").write_text(build_html([], 0, 0), encoding="utf-8")
        webbrowser.open(str(Path("info_edge_report.html").absolute()))
        return

    # 3. AI 分析信息差
    edges = analyze_edge(all_signals)
    print(f"\n🔍 发现 {len(edges)} 个信息差信号")

    # 4. 盯盘检查
    ticker_signals = None
    if watch_ticker:
        ticker_signals = check_ticker_anomalies(watch_ticker)
        if ticker_signals:
            print(f"\n🎯 {watch_ticker} 异常信号:")
            for s in ticker_signals:
                print(f"  {s}")
        else:
            print(f"\n🎯 {watch_ticker} 无显著异常")

    # 5. 报告
    path = Path("info_edge_report.html").absolute()
    html = build_html(edges, len(flash_news), len(depth_data), ticker_signals, watch_ticker)
    path.write_text(html, encoding="utf-8")
    webbrowser.open(str(path))

    # 终端输出
    print(f"\n{'='*54}")
    print(f"   📋 信息差 TOP {min(10, len(edges))}")
    print(f"{'='*54}")
    icons = {"提前泄露": "🚨", "认知差": "🧠", "时间差": "⏰", "数据差": "📊"}
    for e in edges[:10]:
        icon = icons.get(e.get("edge_type", ""), "🔍")
        print(f"\n  {icon} [{e.get('edge_type','?')}] [{e.get('source','?')}]")
        print(f"     {e['title'][:70]}")
        print(f"     紧迫度{e.get('urgency','?')}/10 | {e.get('edge_reason','')} | {e.get('time_window','')}")

    print(f"\n{'='*54}")
    print(f"  ✅ 报告: {path}")
    print(f"  💡 盯盘用法: python info_edge.py --ticker NVDA")
    print(f"{'='*54}")


if __name__ == "__main__":
    main()
