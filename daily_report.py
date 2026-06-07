#!/usr/bin/env python3
"""
📅 全自动每日简报 — 聚合 + AI分析 + 多渠道推送

用法:
  python daily_report.py                          # 完整版（含深度数据）
  python daily_report.py --fast                   # 轻量版（仅快讯）
  python daily_report.py --push email            # 推送：email/slack/dingtalk
  python daily_report.py --ticker NVDA           # 盯盘特定股票

输出: daily_report.html（自动打开）
"""

import sys
import os
import json
import time
import re
import hashlib
import smtplib
import webbrowser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 配置 ────────────────────────────────────────────
DEEPSEEK_KEY = "sk-24d6f1ea55cf44518cdb570683e2e3d2"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
CACHE_DIR = Path.home() / ".cache" / "daily_report"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# SMTP 配置（要推送邮件的话填这里）
SMTP_CONFIG = {
    "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "user": os.environ.get("SMTP_USER", ""),
    "pass": os.environ.get("SMTP_PASS", ""),
    "to": os.environ.get("SMTP_TO", ""),
}

# Slack / DingTalk Webhook
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK", "")
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")

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


def _call_deepseek(prompt, sys_msg="你是一个专业的A股分析师。"):
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
            }, headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}, timeout=90)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return ""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ═══════════════════════════════════════════════════
#  1. 数据采集（复用之前所有来源）
# ═══════════════════════════════════════════════════

# ── 新闻来源 ──

def fetch_eastmoney():
    items = []
    for url in ["https://feed.eastmoney.com/a/2026_1_2.html", "https://feed.eastmoney.com/a/2026_1_1.html"]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
            r.encoding = "utf-8"
            for a in BeautifulSoup(r.text, "lxml").find_all("a", href=True):
                t = a.get_text(strip=True)
                if len(t) > 10 and a["href"].startswith("http"):
                    items.append({"title": t, "url": a["href"], "source": "东方财富", "type": "news"})
            time.sleep(0.3)
        except Exception:
            pass
    return items


def fetch_sina():
    items = []
    for lid, label in {"2509": "国内财经", "2510": "国际财经", "2674": "行情快报", "2669": "公司新闻"}.items():
        try:
            r = requests.get("https://feed.mix.sina.com.cn/api/roll/get",
                             params={"pageid": "153", "lid": lid, "k": "", "num": "15"},
                             headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}, timeout=10)
            for item in r.json().get("result", {}).get("data", []):
                if item.get("title"):
                    items.append({"title": item["title"], "url": item.get("url",""), "source": label, "type": "news"})
            time.sleep(0.3)
        except Exception:
            pass
    return items


def fetch_xueqiu():
    items = []
    try:
        s = requests.Session()
        s.get("https://xueqiu.com", headers={"User-Agent": UA}, timeout=10)
        r = s.get("https://xueqiu.com/query/v1/status/hots.json",
                  params={"count": "15", "scope": "day", "type": "stock"},
                  headers={"User-Agent": UA}, timeout=10)
        for item in r.json().get("data", []):
            t = BeautifulSoup(item.get("text",""), "html.parser").get_text(strip=True)
            if t and len(t) > 5:
                items.append({"title": t[:120], "url": f"https://xueqiu.com/{item.get('user_id','')}/{item.get('id','')}",
                              "source": "雪球", "type": "news"})
    except Exception:
        pass
    return items


def fetch_yahoo():
    items = []
    for url in [
        "https://finance.yahoo.com/news/rssindex",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AAPL,TSLA,AMD&region=US&lang=en-US",
    ]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
            for item in BeautifulSoup(r.text, "xml").find_all("item"):
                t = item.find("title")
                if t and len(t.get_text(strip=True)) > 10:
                    desc = item.find("description")
                    items.append({
                        "title": t.get_text(strip=True),
                        "url": (item.find("link").get_text(strip=True) if item.find("link") else ""),
                        "summary": BeautifulSoup(desc.get_text(strip=True) if desc else "", "html.parser").get_text()[:200] if desc else "",
                        "source": "雅虎财经", "type": "news",
                    })
        except Exception:
            pass
    return items


# ── 数据来源 ──

def fetch_flash():
    """快讯：东方财富 API"""
    items = []
    try:
        r = requests.get("https://push2ex.eastmoney.com/getStockNews?pageindex=0&pagesize=30",
                         headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com"}, timeout=8)
        for item in r.json().get("data", []):
            t = item.get("title", "").strip()
            if t and len(t) > 10:
                items.append({"title": t, "url": item.get("url","") or item.get("shareurl",""),
                              "source": "快讯", "type": "flash"})
    except Exception:
        pass
    return items


def fetch_sina_flash():
    items = []
    try:
        r = requests.get("https://feed.mix.sina.com.cn/api/roll/get",
                         params={"pageid":"153","lid":"2510","k":"","num":"20"},
                         headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}, timeout=8)
        for item in r.json().get("result",{}).get("data",[]):
            if item.get("title"):
                items.append({"title": item["title"], "url": item.get("url",""), "source": "快讯", "type": "flash"})
    except Exception:
        pass
    return items


def fetch_longhubang():
    """龙虎榜"""
    items = []
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get",
                         params={"pn":"1","pz":"8","po":"1","np":"1",
                                  "fields":"f12,f14,f3,f62,f184,f66,f69,f70,f78",
                                  "fid":"f3","fs":"m:0+t:6+f:!2,m:0+t:80+f:!2"},
                         headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"}, timeout=8)
        for item in r.json().get("data",{}).get("diff",[]):
            name = item.get("f14","")
            chg = item.get("f3",0)
            if name:
                items.append({"title": f"龙虎榜: {name} ({chg:+.2f}%)",
                              "detail": f"涨跌幅{chg:+.2f}%，资金异动",
                              "source": "龙虎榜", "type": "data"})
    except Exception:
        pass
    return items


def fetch_northbound():
    """北向资金（沪港通/深港通）"""
    items = []
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/kamt.kline/get",
                         params={"fields1":"f1,f2,f3,f4","fields2":"f51,f52,f53,f54,f55",
                                  "klt":"1","lmt":"5","secid":"1.000001"},
                         headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"}, timeout=8)
        data = r.json()
        for item in data.get("data", {}).get("klines", [])[:3]:
            parts = item.split(",")
            if len(parts) >= 5:
                net = float(parts[3])
                direction = "净买入" if net > 0 else "净卖出"
                items.append({"title": f"北向资金: {direction} ¥{abs(net):.2f}亿",
                              "detail": f"沪股通+深股通合计",
                              "source": "北向资金", "type": "data"})
    except Exception:
        pass
    return items


def fetch_block_trades():
    """大宗交易"""
    items = []
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get",
                         params={"pn":"1","pz":"8","po":"1","np":"1",
                                  "fields":"f12,f14,f2,f3,f4,f5,f6,f7,f8",
                                  "fid":"f3","fs":"m:0+t:1+f:!2"},
                         headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"}, timeout=8)
        for item in r.json().get("data",{}).get("diff",[]):
            name = item.get("f14","")
            price = item.get("f2",0)
            if name and price > 0:
                items.append({"title": f"大宗交易: {name} ¥{price:.2f}",
                              "detail": "",
                              "source": "大宗交易", "type": "data"})
    except Exception:
        pass
    return items


def fetch_margin():
    """融资融券变化"""
    items = []
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get",
                         params={"pn":"1","pz":"8","po":"1","np":"1",
                                  "fields":"f12,f14,f4,f6,f8",
                                  "fid":"f4","fs":"m:0+t:68+f:!2"},
                         headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com"}, timeout=8)
        for item in r.json().get("data",{}).get("diff",[]):
            name = item.get("f14","")
            chg = item.get("f4",0)
            if name and abs(chg) > 0.01:
                direction = "加杠杆" if chg > 0 else "去杠杆"
                items.append({"title": f"两融: {name} {direction} ¥{abs(chg):.2f}亿",
                              "detail": "",
                              "source": "两融", "type": "data"})
    except Exception:
        pass
    return items


def fetch_sec():
    """SEC 内部人交易"""
    items = []
    try:
        r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=4&company=&dateb=&owner=only&start=0&count=5&output=atom",
                         headers={"User-Agent": "Sample/1.0 (contact@example.com)"}, timeout=10)
        for entry in BeautifulSoup(r.text, "xml").find_all("entry")[:5]:
            title = entry.find("title")
            if title:
                items.append({"title": title.get_text(strip=True)[:200], "url": "",
                              "source": "SEC", "type": "data"})
    except Exception:
        pass
    # yfinance insider fallback
    if not items:
        yf = _get_yf()
        if yf:
            for t in ["NVDA","AAPL","TSLA"]:
                try:
                    tk = yf.Ticker(t)
                    inst = getattr(tk, "institutional_holders", None)
                    if inst is not None and not inst.empty:
                        for _, row in inst.head(2).iterrows():
                            items.append({"title": f"机构持仓: {t} {row.get('Holder','?')} 增持",
                                          "url": "", "source": "SEC", "type": "data"})
                    time.sleep(1)
                except Exception:
                    pass
    return items


def fetch_reuters():
    """Reuters / Market News"""
    items = []
    for url in ["https://www.investing.com/rss/news.rss", "https://www.investing.com/rss/market_overview.rss"]:
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
            for item in BeautifulSoup(r.text, "xml").find_all("item")[:10]:
                t = item.find("title")
                if t and len(t.get_text(strip=True)) > 10:
                    items.append({"title": t.get_text(strip=True)[:200], "url": "",
                                  "source": "Reuters", "type": "flash"})
        except Exception:
            pass
    return items


def collect_all(fast=False):
    """聚合所有数据"""
    all_n = []
    collectors = [
        ("东方财富", fetch_eastmoney),
        ("新浪财经", fetch_sina),
        ("雪球", fetch_xueqiu),
        ("雅虎财经", fetch_yahoo),
        ("快讯", fetch_flash),
        ("新浪快讯", fetch_sina_flash),
    ]
    if not fast:
        collectors += [
            ("龙虎榜", fetch_longhubang),
            ("北向资金", fetch_northbound),
            ("大宗交易", fetch_block_trades),
            ("两融", fetch_margin),
            ("SEC", fetch_sec),
            ("Reuters", fetch_reuters),
        ]

    print("📡 采集数据中...")
    for name, fn in collectors:
        print(f"  {name}...", end=" ", flush=True)
        try:
            items = fn()
            print(f"{len(items)} 条")
            all_n.extend(items)
        except Exception as e:
            print(f"错: {e}")

    # 去重
    seen = set()
    uniq = []
    for n in all_n:
        key = n["title"][:30]
        if key not in seen:
            seen.add(key)
            uniq.append(n)
    return uniq


# ═══════════════════════════════════════════════════
#  2. DeepSeek 简报生成
# ═══════════════════════════════════════════════════

def generate_bulletin(all_items, watch_ticker=""):
    """调用 DeepSeek 生成完整简报"""
    if not all_items:
        return "# 今日暂无数据\n\n请稍后再试。\n"

    # ── 分类汇总 ──
    news = [n for n in all_items if n.get("type") in ("news", "flash")]
    data_items = [n for n in all_items if n.get("type") == "data"]

    # 新闻摘要
    news_summary = "\n".join(
        f"- [{n['source']}] {n['title'][:100]}" for n in news[:30]
    ) if news else "暂无新闻"

    # 数据摘要
    data_summary = "\n".join(
        f"- {n['title'][:100]}" for n in data_items[:15]
    ) if data_items else "暂无"

    # 如果是盯盘模式，加上该股票数据
    ticker_ctx = ""
    if watch_ticker:
        yf = _get_yf()
        if yf:
            try:
                tk = yf.Ticker(watch_ticker)
                info = tk.info or {}
                price = info.get("regularMarketPrice", info.get("currentPrice", "N/A"))
                chg = info.get("regularMarketChangePercent", 0)
                if chg:
                    chg_str = f"{float(chg):+.2f}%"
                else:
                    chg_str = "N/A"
                target = info.get("targetMeanPrice", 0)
                target_str = f", 目标价${target:.0f}" if target else ""

                ticker_ctx = (
                    f"\n【{watch_ticker} 实时】\n"
                    f"价格: ${price}{target_str}\n"
                    f"涨跌: {chg_str}\n"
                    f"市值: ${info.get('marketCap',0)/1e9:.1f}B\n"
                )
            except Exception:
                pass

    prompt = f"""你是一位专业的A股分析师，根据以下今日新闻和数据，用简洁专业的语言生成一份每日简报。

今日日期：{_now()}
{ticker_ctx}

【今日新闻】（{len(news)}条）
{news_summary}

【今日数据】（{len(data_items)}条）
{data_summary}

请生成以下格式的简报，要求语言简洁、数据具体、不废话：

# 📅 每日简报 YYYY-MM-DD

## 【今日市场情绪】
一句话概括今天的市场氛围

## 【最重要的3件事】
每件事格式：
1. **标题** — 是什么、影响什么股票、为什么重要

## 【信息差机会】
今天有没有市场还没反应的信息？是什么？为什么没反应？

## 【值得关注的股票】
最多3只，每只说明理由和参考价位

## 【明日预判】
根据今日信息推测明天可能的走势

## 【风险提示】
今日有哪些利空需要注意
"""

    print("\n🤖 DeepSeek 生成简报中...")
    result = _call_deepseek(prompt)
    if not result:
        result = "# 简报生成失败\n\n请检查 API 连接后重试。\n"
    return result


# ═══════════════════════════════════════════════════
#  3. HTML 报告
# ═══════════════════════════════════════════════════

SOURCE_COLORS = {
    "东方财富": "#e65100", "雪球": "#2e7d32", "雅虎财经": "#1565c0",
    "快讯": "#e74c3c", "龙虎榜": "#f57c00", "北向资金": "#00838f",
    "大宗交易": "#6a1b9a", "两融": "#37474f", "SEC": "#b71c1c",
    "Reuters": "#000", "国内财经": "#1565c0", "国际财经": "#0d47a1",
    "行情快报": "#e65100", "公司新闻": "#2e7d32",
}


def build_html(markdown_text, stats, watch_ticker=""):
    """把 Markdown 简报渲染为美观 HTML"""
    import re as _re
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 统计数
    total = stats.get("total", 0)
    news_count = stats.get("news", 0)
    data_count = stats.get("data", 0)

    # 把 markdown 转简单 HTML
    html_body = ""
    in_list = False
    for line in markdown_text.split("\n"):
        # 标题
        if line.startswith("# "):
            html_body += f"<h1>{line[2:]}</h1>\n"
        elif line.startswith("## "):
            html_body += f"<h2>{line[2:].strip()}</h2>\n"
        elif line.startswith("### "):
            html_body += f"<h3>{line[3:].strip()}</h3>\n"
        elif line.startswith("- "):
            if not in_list:
                html_body += "<ul>\n"
                in_list = True
            html_body += f"<li>{line[2:]}</li>\n"
        elif line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. "):
            if not in_list:
                html_body += "<ul>\n"
                in_list = True
            html_body += f"<li class='num'>{line}</li>\n"
        elif line.strip() == "":
            if in_list:
                html_body += "</ul>\n"
                in_list = False
            html_body += "<br>\n"
        elif _re.match(r'^\*\*(.+)\*\*', line):
            # Bold heading
            html_body += f"<p class='bold'>{line}</p>\n"
        else:
            html_body += f"<p>{line}</p>\n"
    if in_list:
        html_body += "</ul>\n"

    ticker_tag = f'<span class="tag">{watch_ticker}</span>' if watch_ticker else ""

    return f"""<!DOCTYPE html>
<html lang=zh-CN>
<head>
<meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>每日简报 {datetime.now().strftime("%Y%m%d")}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f6fa;color:#2d3436}}
.wrap{{max-width:780px;margin:0 auto;padding:14px}}
.head{{background:linear-gradient(135deg,#0c0c1d,#1a1a3e);color:#fff;border-radius:14px;padding:22px 26px;margin-bottom:14px}}
.head h1{{margin:0;font-size:20px}}
.head .meta{{font-size:12px;opacity:.7;display:flex;justify-content:space-between;margin-top:4px}}
.tag{{display:inline-block;background:rgba(255,255,255,.15);border-radius:20px;padding:2px 12px;font-size:11px;margin:3px 3px 0 0;white-space:nowrap}}

.row{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}}
.card{{background:#fff;border-radius:12px;padding:14px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.num{{font-size:22px;font-weight:700;color:#1a1a3e}}
.lbl{{font-size:11px;color:#999;margin-top:2px}}

.content{{background:#fff;border-radius:14px;padding:24px 28px;box-shadow:0 1px 3px rgba(0,0,0,.06);line-height:1.8}}
.content h1{{font-size:20px;color:#1a1a3e;margin:0 0 4px}}
.content h2{{font-size:16px;color:#1a1a3e;margin:20px 0 8px;padding-bottom:4px;border-bottom:2px solid #eef}}
.content h3{{font-size:14px;color:#555;margin:12px 0 4px}}
.content p{{font-size:14px;color:#444;margin:6px 0}}
.content ul{{margin:6px 0;padding-left:20px}}
.content li{{font-size:14px;color:#555;margin:4px 0}}
.content li.num{{list-style:none;margin-left:-20px;font-weight:500}}
.content .bold{{font-weight:600;font-size:15px;color:#333}}

.footer{{text-align:center;padding:20px;color:#bbb;font-size:11px}}
@media(max-width:600px){{.row{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class=wrap>
<div class=head>
<h1>📅 每日简报</h1>
<div class=meta><span>{now}</span><span>📊 {total} 条 · 📰 {news_count} 新闻 · 📈 {data_count} 数据</span></div>
{ticker_tag}
</div>

<div class=row>
<div class=card><div class=num>{total}</div><div class=lbl>总信息</div></div>
<div class=card><div class=num style=color:#3498db>{news_count}</div><div class=lbl>新闻</div></div>
<div class=card><div class=num style=color:#e67e22>{data_count}</div><div class=lbl>数据</div></div>
<div class=card><div class=num style=color:#27ae60>{datetime.now().strftime("%H:%M")}</div><div class=lbl>生成时间</div></div>
</div>

<div class=content>
{html_body}
</div>

<div class=footer>数据: 东方财富/新浪/雪球/雅虎/龙虎榜/北向/大宗/两融/SEC/Reuters &nbsp;|&nbsp; AI: DeepSeek</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════
#  4. 推送模块
# ═══════════════════════════════════════════════════

def push_email(markdown_text, subject="每日简报"):
    """方式一：邮件推送"""
    if not SMTP_CONFIG["user"] or not SMTP_CONFIG["pass"]:
        print("  ⚠️  未配置 SMTP，跳过邮件推送")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_CONFIG["user"]
        msg["To"] = SMTP_CONFIG["to"]
        msg.attach(MIMEText(markdown_text, "plain", "utf-8"))
        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as s:
            s.starttls()
            s.login(SMTP_CONFIG["user"], SMTP_CONFIG["pass"])
            s.sendmail(SMTP_CONFIG["user"], [SMTP_CONFIG["to"]], msg.as_string())
        print("  ✅ 邮件推送成功")
        return True
    except Exception as e:
        print(f"  ⚠️  邮件推送失败: {e}")
        return False


def push_slack(markdown_text):
    """方式二：Slack Webhook"""
    if not SLACK_WEBHOOK:
        print("  ⚠️  未配置 Slack Webhook，跳过")
        return False
    try:
        # 提取前 500 字作为预览
        preview = markdown_text[:500]
        requests.post(SLACK_WEBHOOK, json={"text": f"📅 *每日简报*\n{preview}..."}, timeout=10)
        print("  ✅ Slack 推送成功")
        return True
    except Exception as e:
        print(f"  ⚠️  Slack 推送失败: {e}")
        return False


def push_dingtalk(markdown_text):
    """方式三：钉钉机器人 Webhook"""
    if not DINGTALK_WEBHOOK:
        print("  ⚠️  未配置钉钉 Webhook，跳过")
        return False
    try:
        preview = markdown_text[:500]
        requests.post(DINGTALK_WEBHOOK, json={
            "msgtype": "markdown",
            "markdown": {"title": "每日简报", "text": preview},
        }, timeout=10)
        print("  ✅ 钉钉推送成功")
        return True
    except Exception as e:
        print(f"  ⚠️  钉钉推送失败: {e}")
        return False


def push_all(markdown_text, push_targets):
    """执行所有配置的推送"""
    for target in push_targets:
        target = target.lower()
        if target == "email":
            push_email(markdown_text)
        elif target == "slack":
            push_slack(markdown_text)
        elif target == "dingtalk":
            push_dingtalk(markdown_text)
        else:
            print(f"  ⚠️  未知推送方式: {target}")


# ═══════════════════════════════════════════════════
#  5. 主函数
# ═══════════════════════════════════════════════════

def daily_job(fast=False, watch_ticker="", push_targets=None):
    """每日简报完整工作流"""
    if push_targets is None:
        push_targets = []

    print("=" * 50)
    print("   📅  每日简报生成器")
    print("=" * 50)
    print(f"   {_now()}")
    if fast:
        print("   轻量模式")
    if watch_ticker:
        print(f"   盯盘: {watch_ticker}")
    if push_targets:
        print(f"   推送: {', '.join(push_targets)}")
    print()

    # 1. 采集
    all_items = collect_all(fast=fast)
    print(f"\n📊 共 {len(all_items)} 条信息")

    if not all_items:
        print("⚠️  无数据")
        return None

    # 2. 统计
    news_count = sum(1 for n in all_items if n.get("type") in ("news", "flash"))
    data_count = sum(1 for n in all_items if n.get("type") == "data")

    # 3. AI 简报
    markdown = generate_bulletin(all_items, watch_ticker)

    # 4. 保存 HTML
    path = Path("daily_report.html").absolute()
    html = build_html(markdown, {"total": len(all_items), "news": news_count, "data": data_count}, watch_ticker)
    path.write_text(html, encoding="utf-8")
    webbrowser.open(str(path))

    # 5. 控制台输出
    print(f"\n{'─'*50}")
    print(markdown)
    print(f"{'─'*50}")
    print(f"  ✅ HTML: {path}")

    # 6. 推送
    if push_targets:
        print("\n📤 推送中...")
        push_all(markdown, push_targets)

    return markdown


def main():
    fast = "--fast" in sys.argv
    watch_ticker = ""
    push_targets = []

    for i, a in enumerate(sys.argv):
        if a == "--ticker" and i + 1 < len(sys.argv):
            watch_ticker = sys.argv[i + 1].upper()
        if a == "--push" and i + 1 < len(sys.argv):
            push_targets = [t.strip() for t in sys.argv[i + 1].split(",")]

    daily_job(fast=fast, watch_ticker=watch_ticker, push_targets=push_targets)


if __name__ == "__main__":
    main()
