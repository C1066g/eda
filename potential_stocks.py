import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

stocks = {
    "NVDA": "英伟达 — AI芯片之王",
    "PLTR": "Palantir — AI平台龙头",
    "NBIS": "Nebius — AI云基础设施",
    "BE":  "Bloom Energy — AI数据中心电力",
    "PATH": "UiPath — 企业自动化AI",
}

end = datetime.now()
start = end - timedelta(days=180)

print("=" * 72)
print(f"{'潜力成长股 6个月对比分析':^72}")
print(f"{'分析日期':>20}: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 72)

all_data = {}

for ticker, name in stocks.items():
    print(f"\n📡 正在获取 {ticker} ({name})...", end=" ", flush=True)
    try:
        df = yf.download(ticker, start=start, end=end, session=session, progress=False, auto_adjust=True)
        if df.empty:
            print("❌ 无数据")
            continue
        info = yf.Ticker(ticker, session=session).info or {}
        close = df["Close"].squeeze()
        high_vals = df["High"].squeeze()
        low_vals = df["Low"].squeeze()
        print("✅")
        all_data[ticker] = {"df": df, "info": info, "name": name,
                             "close_series": close, "high_series": high_vals, "low_series": low_vals}
    except Exception as e:
        print(f"❌ {e}")

print("\n" + "=" * 72)
print(f"{'📊 综合对比':^72}")
print("=" * 72)

header = f"{'代码':>6} | {'最新价':>8} | {'6月涨幅':>8} | {'年化波动':>8} | {'RSI':>6} | {'市值':>12} | {'P/E':>8} | {'评级':>8}"
print(header)
print("-" * 72)

results = []

for ticker in stocks:
    if ticker not in all_data:
        continue
    d = all_data[ticker]
    df = d["df"]
    info = d["info"]
    close = d["close_series"]
    high_vals = d["high_series"]
    low_vals = d["low_series"]

    # 价格 & 涨跌
    first = float(close.iloc[0])
    last = float(close.iloc[-1])
    change = (last / first - 1) * 100

    # 波动率（年化）
    daily_ret = close.pct_change().dropna()
    volatility = float(daily_ret.std() * np.sqrt(252) * 100)

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])

    # 市值 & PE
    mcap = info.get("marketCap", 0)
    pe = info.get("forwardPE") or info.get("trailingPE") or 0

    # 评分 (动量+RSI综合)
    score = 0
    score += 2 if change > 30 else 1 if change > 10 else 0
    score += 1 if 30 < rsi < 70 else 0  # 非超买超卖
    score += 1 if pe and pe < 50 else 0  # PE合理

    if score >= 3:
        rating = "⭐⭐⭐⭐"
    elif score >= 2:
        rating = "⭐⭐⭐"
    elif score >= 1:
        rating = "⭐⭐"
    else:
        rating = "⭐"

    mcap_str = f"${mcap/1e9:.1f}B" if mcap else "N/A"
    pe_str = f"{pe:.1f}" if pe else "N/A"

    print(f"{ticker:>6} | ${last:>7.2f} | {change:>+7.2f}% | {volatility:>6.1f}% | {rsi:>5.1f} | {mcap_str:>12} | {pe_str:>8} | {rating:>8}")

    results.append({
        "ticker": ticker,
        "name": d["name"],
        "close": last,
        "change_pct": round(change, 2),
        "volatility": round(volatility, 1),
        "rsi": round(rsi, 1),
        "mcap": mcap_str,
        "pe": pe_str,
        "rating": rating,
        "score": score,
    })

# ========== 深入分析前3名 ==========
results.sort(key=lambda x: x["score"], reverse=True)
print("\n" + "=" * 72)
print(f"{'🔍 精选 TOP 3 深度分析':^72}")
print("=" * 72)

for r in results[:3]:
    ticker = r["ticker"]
    d = all_data[ticker]
    info = d["info"]
    df = d["df"]
    close = d["close_series"]
    high_vals = d["high_series"]
    low_vals = d["low_series"]

    # 最高最低
    max_close = close.idxmax()
    min_close = close.idxmin()

    # 均线
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    ma_status = "多头↑" if sma20 > sma50 else "空头↓"

    # 52周高低
    high52 = info.get("fiftyTwoWeekHigh", 0)
    low52 = info.get("fiftyTwoWeekLow", 0)
    from_high = (float(close.iloc[-1]) / high52 - 1) * 100 if high52 else 0

    # 企业信息
    sector = info.get("sector", "N/A")
    industry = info.get("industry", "N/A")
    target = info.get("targetMeanPrice", 0)
    target_pct = (target / float(close.iloc[-1]) - 1) * 100 if target else 0

    print(f"\n  {ticker} — {r['name']}")
    print(f"  {'行业':>12}: {sector} / {industry}")
    print(f"  {'最新价':>12}: ${float(close.iloc[-1]):.2f}  6月涨幅: {r['change_pct']:+.2f}%")
    print(f"  {'最高收盘':>12}: ${float(close.max()):.2f} ({max_close.strftime('%m-%d')})")
    print(f"  {'最低收盘':>12}: ${float(close.min()):.2f} ({min_close.strftime('%m-%d')})")
    print(f"  {'距52周高':>12}: {from_high:+.2f}%")
    if target:
        print(f"  {'分析师目标':>12}: ${target:.2f} ({target_pct:+.1f}% 空间)")
    print(f"  {'均线形态':>12}: {ma_status}  (SMA20=${sma20:.2f}, SMA50=${sma50:.2f})")
    print(f"  {'RSI(14)':>12}: {r['rsi']}")
    print(f"  {'年化波动':>12}: {r['volatility']}%")

    news_list = info.get("news", []) or []
    if news_list:
        print(f"  {'最新动态':>12}: {news_list[0].get('title', 'N/A')[:60]}")
    print()

# ========== 风险提示 ==========
print("=" * 72)
print(f"{'⚠️  风险提示':^72}")
print("=" * 72)
print("""
  1. 以上数据基于过去6个月表现，不构成投资建议
  2. 高增长往往伴随高波动，请评估自身风险承受能力
  3. AI/半导体板块估值偏高，注意回调风险
  4. 建议分散配置，不要重仓单一标的
  5. 投资前请自行深入研究或咨询专业顾问
""")
print("=" * 72)
