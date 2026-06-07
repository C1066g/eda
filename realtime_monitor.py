#!/usr/bin/env python3
"""
🚨 实时监控系统 — 多线程并行采集 + DeepSeek 实时分析 + Web 看板

启动:
  python realtime_monitor.py          # 启动监控 + Web 看板 (http://localhost:5000)
  python realtime_monitor.py --scan   # 单次扫描（不启动看板）

数据流:
  ┌─ 快讯(30s) ─┐
  │ 东方财富API  │──┐
  │ 新浪快讯     │──┤
  │ 雅虎RSS      │──┤
  └──────────────┘  │  ┌──────────┐  ┌──────────┐
  ┌─ 深度(5min) ─┐  ├→│ 去重缓存  │→│ DeepSeek  │→→ HTML看板
  │ yfinance价格 │──┤  │ (JSON)   │  │ 分析评分  │
  │ 北向资金    │──┤  └──────────┘  └──────────┘
  │ 异常成交量  │──┘
  └──────────────┘
"""

import sys
import os
import json
import time
import re
import hashlib
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import StringIO

import requests
from bs4 import BeautifulSoup

# ── 配置 ──
DEEPSEEK_KEY = "sk-24d6f1ea55cf44518cdb570683e2e3d2"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DATA_DIR = Path.home() / ".cache" / "realtime_monitor"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 全局状态 ──
_lock = threading.Lock()
_all_signals = []           # 所有信号（按时间排序）
_breaking_signals = []      # 重大突发信号 (edge_score >= 80)
_watch_signals = []         # 重点跟踪信号 (edge_score >= 60)
_dedup_db = {}              # 去重数据库: {hash: timestamp}
_stats = {                  # 统计
    "total_fetched": 0,
    "total_analyzed": 0,
    "breaking_count": 0,
    "watch_count": 0,
    "started_at": datetime.now().isoformat(),
    "last_update": "",
}

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


# ═══════════════════════════════════════════════════
#  去重引擎
# ═══════════════════════════════════════════════════

DEDUP_FILE = DATA_DIR / "dedup.json"
if DEDUP_FILE.exists():
    try:
        _dedup_db = json.loads(DEDUP_FILE.read_text())
    except Exception:
        _dedup_db = {}

def _dedup_key(item):
    """生成去重 hash"""
    raw = item.get("title", "")[:60] + item.get("source", "")
    return hashlib.md5(raw.encode()).hexdigest()

def _is_duplicate(item):
    key = _dedup_key(item)
    with _lock:
        if key in _dedup_db:
            age = time.time() - _dedup_db[key]
            # 24小时内算重复
            return age < 86400
        _dedup_db[key] = time.time()
    # 定期持久化
    if len(_dedup_db) % 50 == 0:
        try:
            DEDUP_FILE.write_text(json.dumps(_dedup_db, ensure_ascii=False))
        except Exception:
            pass
    return False

# 清理过期记录
now_ts = time.time()
_dedup_db = {k: v for k, v in _dedup_db.items() if now_ts - v < 86400}


# ═══════════════════════════════════════════════════
#  采集器（每 30s）
# ═══════════════════════════════════════════════════

def fetch_eastmoney_flash():
    """东方财富快讯 (最快)"""
    items = []
    try:
        r = requests.get(
            "https://push2ex.eastmoney.com/getStockNews",
            params={"pageindex": 0, "pagesize": 30},
            headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com"},
            timeout=8,
        )
        for item in r.json().get("data", []):
            t = item.get("title", "").strip()
            if t and len(t) > 8:
                items.append({
                    "title": t,
                    "url": item.get("url", "") or item.get("shareurl", ""),
                    "source": "东方快讯",
                    "ts": time.time(),
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
                    "ts": time.time(),
                    "type": "flash",
                })
    except Exception:
        pass
    return items


def fetch_yahoo_rss():
    """雅虎财经 RSS"""
    items = []
    for url in [
        "https://finance.yahoo.com/news/rssindex",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AAPL,TSLA,AMD&region=US&lang=en-US",
    ]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
            for item in BeautifulSoup(r.text, "xml").find_all("item")[:15]:
                t = item.find("title")
                if t and len(t.get_text(strip=True)) > 10:
                    items.append({
                        "title": t.get_text(strip=True),
                        "url": item.find("link").get_text(strip=True) if item.find("link") else "",
                        "source": "雅虎快讯",
                        "ts": time.time(),
                        "type": "flash",
                    })
        except Exception:
            pass
    return items


# ═══════════════════════════════════════════════════
#  采集器（每 5min）
# ═══════════════════════════════════════════════════

def fetch_prices():
    """yfinance 关键股票实时价格"""
    items = []
    yf = _get_yf()
    if not yf:
        return items
    tickers = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "DELL", "PLTR", "002594.SZ", "300750.SZ"]
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    for t in tickers:
        try:
            time.sleep(2)
            df = yf.download(t, period="5d", session=sess, progress=False, auto_adjust=True)
            if df.empty:
                continue
            close = df["Close"].squeeze()
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) > 1 else last
            chg_pct = (last / prev - 1) * 100
            if abs(chg_pct) > 1.5:
                items.append({
                    "title": f"📈 {t} 异动: ${last:.2f} ({chg_pct:+.2f}%)",
                    "url": f"https://finance.yahoo.com/quote/{t}",
                    "source": "价格监控",
                    "ts": time.time(),
                    "type": "alert",
                    "extra": {"ticker": t, "price": last, "change_pct": round(chg_pct, 2)},
                })
        except Exception:
            pass
    return items


def fetch_northbound():
    """北向资金流向"""
    items = []
    try:
        r = requests.get(
            "https://push2.eastmoney.com/api/qt/kamt.kline/get",
            params={"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54,f55",
                     "klt": "1", "lmt": "5", "secid": "1.000001"},
            headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"},
            timeout=8,
        )
        for k in r.json().get("data", {}).get("klines", [])[:2]:
            parts = k.split(",")
            if len(parts) >= 5:
                net = float(parts[3])
                if abs(net) > 10:
                    direction = "大幅净买入" if net > 0 else "大幅净卖出"
                    items.append({
                        "title": f"北向{direction} ¥{abs(net):.1f}亿",
                        "url": "",
                        "source": "北向资金",
                        "ts": time.time(),
                        "type": "alert",
                        "extra": {"net_amount": net},
                    })
    except Exception:
        pass
    return items


def fetch_volume_anomaly():
    """成交量异常检测"""
    items = []
    yf = _get_yf()
    if not yf:
        return items
    tickers = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT"]
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    for t in tickers:
        try:
            time.sleep(1)
            df = yf.download(t, period="1mo", session=sess, progress=False, auto_adjust=True)
            if df.empty:
                continue
            vol = df["Volume"].squeeze()
            avg_vol = float(vol.tail(20).mean())
            last_vol = float(vol.iloc[-1])
            if avg_vol > 0 and last_vol > avg_vol * 3:
                items.append({
                    "title": f"📊 {t} 放量{last_vol/avg_vol:.1f}x (日均{avg_vol/1e6:.0f}M → 今日{last_vol/1e6:.0f}M)",
                    "url": f"https://finance.yahoo.com/quote/{t}",
                    "source": "成交量监控",
                    "ts": time.time(),
                    "type": "alert",
                    "extra": {"ticker": t, "ratio": round(last_vol / avg_vol, 1)},
                })
        except Exception:
            pass
    return items


# ═══════════════════════════════════════════════════
#  DeepSeek 实时分析
# ═══════════════════════════════════════════════════

def analyze_item(item):
    """对单条消息进行实时分析评分"""
    prompt = f"""你是实时交易监控 AI。判断这条消息是否是重大市场信号。

消息: [{item.get('source','?')}] {item.get('title','')[:150]}

返回严格 JSON:
{{
  "is_breaking": true/false,
  "edge_score": 0-100,
  "stocks": ["相关股票代码"],
  "action": "立即关注/跟踪/忽略",
  "reason": "一句话理由（<20字）"
}}

edge_score 定义:
- 80-100: 重大突发，市场将迅速反应（财报超预期/突发政策/并购/黑天鹅）
- 60-79: 重要信息，值得跟踪（业绩预告/机构大额买卖/行业变化）
- 40-59: 一般信息，记录即可
- 0-39: 噪音

只返回 JSON，不要 markdown。"""

    for _ in range(2):
        try:
            r = requests.post(DEEPSEEK_URL, json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一个实时交易监控 AI，判断果断，不模棱两可。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.05,
                "max_tokens": 512,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}, timeout=15)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                result = json.loads(content)
                item["is_breaking"] = result.get("is_breaking", False)
                item["edge_score"] = result.get("edge_score", 0)
                item["stocks"] = result.get("stocks", [])
                item["action"] = result.get("action", "忽略")
                item["reason"] = result.get("reason", "")
                return item
            time.sleep(1)
        except Exception:
            time.sleep(1)
    item["is_breaking"] = False
    item["edge_score"] = 0
    item["stocks"] = []
    item["action"] = "忽略"
    item["reason"] = ""
    return item


# ═══════════════════════════════════════════════════
#  采集循环（后台线程）
# ═══════════════════════════════════════════════════

def _collect_and_analyze(collectors, is_fast=True):
    """执行一轮采集 + 分析"""
    global _all_signals, _breaking_signals, _watch_signals, _stats
    new_items = []

    for name, fn in collectors:
        try:
            items = fn()
            for item in items:
                if not _is_duplicate(item):
                    new_items.append(item)
        except Exception:
            pass

    if not new_items:
        return

    with _lock:
        _stats["total_fetched"] += len(new_items)

    print(f"  [{_now()}] 📥 {len(new_items)} 条新消息，正在分析...", flush=True)

    # DeepSeek 批量分析 (并发)
    analyzed = []
    threads = []
    for item in new_items:
        t = threading.Thread(target=lambda itm=item: analyzed.append(analyze_item(itm)))
        t.start()
        threads.append(t)
        if len(threads) >= 5:
            for t in threads:
                t.join()
            threads = []
    for t in threads:
        t.join()

    with _lock:
        for item in analyzed:
            _all_signals.append(item)
            _stats["total_analyzed"] += 1
            es = item.get("edge_score", 0)
            if es >= 80:
                _breaking_signals.append(item)
                _stats["breaking_count"] += 1
                print(f"    🚨 [{item['source']}] {item['title'][:60]} (edge_score={es})", flush=True)
            elif es >= 60:
                _watch_signals.append(item)
                _stats["watch_count"] += 1
                print(f"    📌 [{item['source']}] {item['title'][:60]} (edge_score={es})", flush=True)
        _stats["last_update"] = _now()

    # 限制内存增长
    with _lock:
        if len(_all_signals) > 2000:
            _all_signals = _all_signals[-1000:]
        if len(_breaking_signals) > 200:
            _breaking_signals = _breaking_signals[-100:]
        if len(_watch_signals) > 500:
            _watch_signals = _watch_signals[-300:]


def flash_loop():
    """30s 快讯循环"""
    collectors = [
        ("东方快讯", fetch_eastmoney_flash),
        ("新浪快讯", fetch_sina_flash),
        ("雅虎快讯", fetch_yahoo_rss),
    ]
    while True:
        try:
            _collect_and_analyze(collectors, is_fast=True)
        except Exception as e:
            print(f"  ⚠️ 快讯循环异常: {e}", flush=True)
        time.sleep(30)


def depth_loop():
    """5min 深度循环"""
    collectors = [
        ("价格监控", fetch_prices),
        ("北向资金", fetch_northbound),
        ("成交量监控", fetch_volume_anomaly),
    ]
    time.sleep(15)  # 错开启动
    while True:
        try:
            _collect_and_analyze(collectors, is_fast=False)
        except Exception as e:
            print(f"  ⚠️ 深度循环异常: {e}", flush=True)
        time.sleep(300)


# ═══════════════════════════════════════════════════
#  Web 看板 (localhost:5000)
# ═══════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang=zh-CN>
<head>
<meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>实时监控看板</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0a0a1a;color:#e0e0e0}
.wrap{max-width:960px;margin:0 auto;padding:14px}

.head{background:linear-gradient(135deg,#0d0d2b,#1a1a4e);border-radius:14px;padding:20px 24px;margin-bottom:14px;border:1px solid rgba(100,100,255,.15)}
.head h1{margin:0;font-size:18px;color:#fff;display:flex;align-items:center;gap:8px}
.head .meta{font-size:11px;color:#666;margin-top:4px;display:flex;justify-content:space-between}
.status-bar{display:flex;gap:12px;margin-top:8px;flex-wrap:wrap}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.dot.green{background:#27ae60;animation:pulse 2s infinite}
.dot.red{background:#e74c3c;animation:pulse 1s infinite}
.dot.yellow{background:#f39c12}
@keyframes pulse{0%{opacity:1}50%{opacity:.3}100%{opacity:1}}

.row{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px}
.card{background:#13132b;border-radius:12px;padding:14px 8px;text-align:center;border:1px solid rgba(100,100,255,.08)}
.num{font-size:22px;font-weight:700;color:#8ab4ff}
.lbl{font-size:10px;color:#666;margin-top:2px}

.section{margin-bottom:14px}
.section-header{font-size:13px;font-weight:600;color:#8ab4ff;margin-bottom:8px;display:flex;align-items:center;gap:6px}

.breaking-item{background:linear-gradient(135deg,#2a0a0a,#1a0a0a);border:1px solid rgba(255,50,50,.2);border-radius:10px;padding:12px 14px;margin-bottom:6px;border-left:3px solid #e74c3c}
.watch-item{background:#13132b;border-radius:10px;padding:12px 14px;margin-bottom:6px;border-left:3px solid #f39c12;border:1px solid rgba(100,100,255,.06)}

.item-hdr{display:flex;align-items:center;gap:6px;margin-bottom:3px;flex-wrap:wrap}
.src{font-size:9px;padding:1px 7px;border-radius:3px;font-weight:600}
.score{font-size:10px;font-weight:700}
.item-title{font-size:13px;line-height:1.5;margin-bottom:3px;color:#eee}
.item-meta{font-size:11px;color:#888;display:flex;gap:8px;flex-wrap:wrap}
.ttag{display:inline-block;background:rgba(100,100,255,.12);color:#8ab4ff;border-radius:3px;padding:0 6px;font-size:9px}
.empty{padding:40px;text-align:center;color:#444}

.footer{text-align:center;padding:16px;color:#333;font-size:10px}
</style>
</head>
<body>
<div class=wrap>
<div class=head>
<h1>🚨 实时监控 <span style="font-size:11px;color:#666;font-weight:400">| 30s 刷新</span></h1>
<div class=meta>
<span>{TIME}</span>
<span>
循环: <span class="dot green"></span>{FREQ_STATUS}
| 分析: {STATS_TOTAL_ANALYZED}条 | 🚨{BREAKING_COUNT} 🔍{WATCH_COUNT}
</span>
</div>
</div>

<div class=row>
<div class=card><div class=num style=color:#e74c3c>{BREAKING_COUNT}</div><div class=lbl>重大突发</div></div>
<div class=card><div class=num style=color:#f39c12>{WATCH_COUNT}</div><div class=lbl>重点跟踪</div></div>
<div class=card><div class=num style=color:#8ab4ff>{STATS_TOTAL_ANALYZED}</div><div class=lbl>累计分析</div></div>
<div class=card><div class=num style=color:#27ae60>{STATS_TOTAL_FETCHED}</div><div class=lbl>抓取消息</div></div>
<div class=card><div class=num style=color:#888}>{UPTIME}</div><div class=lbl>已运行</div></div>
</div>

<div class=section>
<div class=section-header><span class="dot red"></span> 重大突发 (edge_score >= 80)</div>
{BREAKING_HTML}
</div>

<div class=section>
<div class=section-header><span class="dot yellow"></span> 重点跟踪 (edge_score >= 60)</div>
{WATCH_HTML}
</div>

<div class=footer>数据: 东方快讯/新浪/雅虎/价格监控/北向/成交量 &nbsp;|&nbsp; AI: DeepSeek</div>
</div>
</body>
</html>"""


def _time_ago(ts):
    d = time.time() - ts
    if d < 60:
        return f"{int(d)}s前"
    if d < 3600:
        return f"{int(d/60)}m前"
    return f"{int(d/3600)}h前"


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _src_color(src):
    colors = {
        "东方快讯": ("#e65100","#fff3e0"),
        "新浪快讯": ("#1565c0","#e3f2fd"),
        "雅虎快讯": ("#0d47a1","#e3f2fd"),
        "价格监控": ("#e74c3c","#fde8e8"),
        "北向资金": ("#00838f","#e0f7fa"),
        "成交量监控": ("#6a1b9a","#f3e5f5"),
    }
    return colors.get(src, ("#666","#222"))


def _generate_html():
    with _lock:
        breaking = list(reversed(_breaking_signals[-20:]))
        watch = list(reversed(_watch_signals[-30:]))
        stats = dict(_stats)

    started = datetime.fromisoformat(stats["started_at"])
    uptime_sec = (datetime.now() - started).total_seconds()
    if uptime_sec < 3600:
        uptime_str = f"{int(uptime_sec/60)}m"
    else:
        uptime_str = f"{int(uptime_sec/3600)}h{int(uptime_sec%3600/60)}m"

    # 重大突发
    breaking_html = ""
    for item in breaking:
        src_name = item.get("source", "?")
        c, b = _src_color(src_name)
        stocks = " ".join(f'<span class="ttag">{s}</span>' for s in item.get("stocks",[]))
        breaking_html += f"""
<div class="breaking-item">
<div class="item-hdr">
<span class="src" style="color:{c};background:{b}">{src_name}</span>
<span class="score" style="color:#e74c3c">🚨 {item.get("edge_score",0)}</span>
<span style="font-size:10px;color:#666">{_time_ago(item.get("ts",time.time()))}</span>
</div>
<div class="item-title">{item.get("title","")}</div>
<div class="item-meta">
<span>{item.get("reason","")}</span>
{stocks}
</div>
</div>"""

    if not breaking_html:
        breaking_html = '<div class="empty">暂无重大突发信号</div>'

    # 重点跟踪
    watch_html = ""
    for item in watch:
        src_name = item.get("source", "?")
        c, b = _src_color(src_name)
        stocks = " ".join(f'<span class="ttag">{s}</span>' for s in item.get("stocks",[]))
        watch_html += f"""
<div class="watch-item">
<div class="item-hdr">
<span class="src" style="color:{c};background:{b}">{src_name}</span>
<span class="score" style="color:#f39c12">📌 {item.get("edge_score",0)}</span>
<span style="font-size:10px;color:#666">{_time_ago(item.get("ts",time.time()))}</span>
</div>
<div class="item-title">{item.get("title","")}</div>
<div class="item-meta">
<span>{item.get("reason","")}</span>
{stocks}
</div>
</div>"""

    if not watch_html:
        watch_html = '<div class="empty">暂无重点跟踪信号</div>'

    html = HTML_TEMPLATE
    html = html.replace("{TIME}", _now())
    html = html.replace("{FREQ_STATUS}", "30s/5min")
    html = html.replace("{STATS_TOTAL_ANALYZED}", str(stats["total_analyzed"]))
    html = html.replace("{STATS_TOTAL_FETCHED}", str(stats["total_fetched"]))
    html = html.replace("{BREAKING_COUNT}", str(len(breaking)))
    html = html.replace("{WATCH_COUNT}", str(len(watch)))
    html = html.replace("{UPTIME}", uptime_str)
    html = html.replace("{BREAKING_HTML}", breaking_html)
    html = html.replace("{WATCH_HTML}", watch_html)
    return html


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/data":
            # JSON API
            with _lock:
                data = {
                    "stats": _stats,
                    "breaking": [{
                        "title": s.get("title",""),
                        "source": s.get("source",""),
                        "edge_score": s.get("edge_score",0),
                        "stocks": s.get("stocks",[]),
                        "reason": s.get("reason",""),
                        "time_ago": _time_ago(s.get("ts",time.time())),
                    } for s in reversed(_breaking_signals[-20:])],
                    "watch": [{
                        "title": s.get("title",""),
                        "source": s.get("source",""),
                        "edge_score": s.get("edge_score",0),
                        "stocks": s.get("stocks",[]),
                        "reason": s.get("reason",""),
                        "time_ago": _time_ago(s.get("ts",time.time())),
                    } for s in reversed(_watch_signals[-30:])],
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_generate_html().encode())

    def log_message(self, format, *args):
        pass  # 静默日志


DEFAULT_PORT = 5001

def serve_forever(port=DEFAULT_PORT):
    # 设置 SO_REUSEADDR
    class ReuseServer(HTTPServer):
        allow_reuse_address = True
    server = ReuseServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n  🌐 打开看板: http://localhost:{port}")
    print(f"  💡 用法: python realtime_monitor.py --port 5001")
    print(f"  🔄 快讯每30s更新，深度数据每5min更新")
    webbrowser.open(f"http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  👋 停止")
        server.server_close()


# ═══════════════════════════════════════════════════
#  单次扫描模式
# ═══════════════════════════════════════════════════

def do_scan():
    """单次扫描所有来源 + 分析"""
    print("=" * 50)
    print("   🔍  实时监控 — 单次扫描")
    print("=" * 50)
    print(f"   {_now()}")
    print()

    all_collectors = [
        ("东方快讯", fetch_eastmoney_flash),
        ("新浪快讯", fetch_sina_flash),
        ("雅虎快讯", fetch_yahoo_rss),
        ("价格监控", fetch_prices),
        ("北向资金", fetch_northbound),
        ("成交量监控", fetch_volume_anomaly),
    ]
    _collect_and_analyze(all_collectors)

    with _lock:
        print(f"\n📊 统计")
        print(f"  总抓取: {_stats['total_fetched']}")
        print(f"  总分析: {_stats['total_analyzed']}")
        print(f"  重大突发: {_stats['breaking_count']}")
        print(f"  重点跟踪: {_stats['watch_count']}")

        if _breaking_signals:
            print(f"\n🚨 重大突发:")
            for s in _breaking_signals:
                print(f"  [{s.get('edge_score',0)}] {s['title'][:70]}")
                print(f"    → {s.get('reason','')} | {s.get('stocks',[])}")

        if _watch_signals:
            print(f"\n📌 重点跟踪:")
            for s in _watch_signals[:5]:
                print(f"  [{s.get('edge_score',0)}] {s['title'][:70]}")

    path = Path("realtime_report.html").absolute()
    path.write_text(_generate_html(), encoding="utf-8")
    webbrowser.open(str(path))
    print(f"\n  ✅ 报告: {path}")


# ═══════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════

def main():
    port = DEFAULT_PORT
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    if "--scan" in sys.argv:
        do_scan()
        return

    print("=" * 50)
    print("   🚨  实时监控系统")
    print("=" * 50)
    print(f"   启动时间: {_now()}")
    print(f"   快讯循环: 每 30s")
    print(f"   深度循环: 每 5min")
    print(f"   看板地址: http://localhost:{port}")
    print()

    # 启动后台采集线程
    t1 = threading.Thread(target=flash_loop, daemon=True)
    t2 = threading.Thread(target=depth_loop, daemon=True)
    t1.start()
    t2.start()

    # 主线程: HTTP 服务
    serve_forever(port)


if __name__ == "__main__":
    main()
