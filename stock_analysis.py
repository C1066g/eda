import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import requests
from datetime import datetime, timedelta

# ========== 1. 获取数据 ==========
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

end = datetime.now()
start = end - timedelta(days=180)
df = yf.download("AAPL", start=start, end=end, session=session)
df.columns = [col[0] for col in df.columns]

close = df["Close"]
high = df["High"]
low = df["Low"]
volume = df["Volume"]

# ========== 2. 整体趋势 ==========
first_price = close.iloc[0]
last_price = close.iloc[-1]
change_pct = (last_price / first_price - 1) * 100
trend = "上涨 📈" if change_pct > 0 else "下跌 📉"

# SMA 判断中期趋势
sma_20 = close.rolling(20).mean().iloc[-1]
sma_50 = close.rolling(50).mean().iloc[-1]
ma_trend = "多头排列（上升趋势）" if sma_20 > sma_50 else "空头排列（下降趋势）"

# ========== 3. 最高 / 最低点 ==========
max_idx = close.idxmax()
min_idx = close.idxmin()

# ========== 4. 支撑位 & 压力位（用过去6个月的关键高低点聚类） ==========
def find_key_levels(prices, num_levels=3):
    """用 KDE 密度聚类找价格密集区"""
    from scipy.signal import argrelextrema

    local_max = argrelextrema(prices.values, np.greater, order=5)[0]
    local_min = argrelextrema(prices.values, np.less, order=5)[0]

    peaks = prices.iloc[local_max].values if len(local_max) else np.array([])
    troughs = prices.iloc[local_min].values if len(local_min) else np.array([])

    def cluster(points, n=num_levels):
        if len(points) < 2:
            return sorted(points.tolist()) if len(points) else []
        from scipy.cluster.hierarchy import fcluster, linkage
        Z = linkage(points.reshape(-1, 1), method="ward")
        clusters = fcluster(Z, t=n, criterion="maxclust")
        levels = []
        for c in range(1, n + 1):
            members = points[clusters == c]
            if len(members):
                levels.append(round(np.mean(members), 2))
        return sorted(levels, reverse=True)

    resistances = cluster(peaks)
    supports = cluster(troughs)
    return supports, resistances

supports, resistances = find_key_levels(close)

# 过滤：只保留在最近价格附近的位
current = float(close.iloc[-1])
supports = [s for s in supports if s < current][-3:]
resistances = [r for r in resistances if r > current][:3]

# ========== 5. RSI 判断超买/超卖 ==========
delta = close.diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
avg_gain = gain.rolling(14).mean()
avg_loss = loss.rolling(14).mean()
rs = avg_gain / avg_loss
rsi = 100 - 100 / (1 + rs)
rsi_val = float(rsi.iloc[-1])
rsi_signal = "超买" if rsi_val > 70 else "超卖" if rsi_val < 30 else "中性"

# ========== 6. 布林带 ==========
sma20 = close.rolling(20).mean()
std20 = close.rolling(20).std()
bb_upper = sma20 + 2 * std20
bb_lower = sma20 - 2 * std20
in_band = bb_lower.iloc[-1] <= current <= bb_upper.iloc[-1]
bb_signal = "触及下轨（潜在反弹）" if current <= bb_lower.iloc[-1] + (bb_upper.iloc[-1] - bb_lower.iloc[-1]) * 0.1 else \
            "触及上轨（潜在回调）" if current >= bb_upper.iloc[-1] - (bb_upper.iloc[-1] - bb_lower.iloc[-1]) * 0.1 else \
            "在中轨附近运行"

# ========== 7. 成交量分析 ==========
vol_avg = volume.tail(20).mean()
vol_last = volume.iloc[-1]
vol_ratio = float(vol_last / vol_avg)
vol_signal = "放量" if vol_ratio > 1.5 else "缩量" if vol_ratio < 0.7 else "正常"

# ========== 8. 新闻情绪（抓取头条） ==========
try:
    news = yf.Search("AAPL", session=session).news
    headlines = []
    for n in news[:5]:
        t = n.get("title", "")
        if t:
            headlines.append(t)
except Exception:
    headlines = ["（新闻获取失败）"]

# ========== 9. 综合建议 ==========
score = 0
if trend == "上涨 📈":
    score += 1
if ma_trend == "多头排列（上升趋势）":
    score += 1
if rsi_val < 40:
    score += 1  # 超卖反弹机会
elif rsi_val > 70:
    score -= 1  # 超买风险
if current <= bb_lower.iloc[-1] * 1.03:
    score += 1
elif current >= bb_upper.iloc[-1] * 0.97:
    score -= 1

if score >= 2:
    advice = "买入"
    reason = "多重技术指标显示上行信号"
elif score >= 0:
    advice = "观望"
    reason = "多空信号交织，方向不明确"
else:
    advice = "卖出/减仓"
    reason = "技术面偏弱，存在下行风险"

# ========== 10. 输出报告 ==========
print("=" * 60)
print(f"{'AAPL 技术分析报告':^60}")
print(f"{'分析日期':>20}: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

print(f"\n{'▎ 价格概览':-<60}")
print(f"  起始价格: ${first_price:.2f}")
print(f"  最新收盘: ${last_price:.2f}")
print(f"  区间涨跌: {change_pct:+.2f}%  ({trend})")
print(f"  最高收盘: ${float(close.max()):.2f}  ({max_idx.strftime('%Y-%m-%d')})")
print(f"  最低收盘: ${float(close.min()):.2f}  ({min_idx.strftime('%Y-%m-%d')})")
print(f"  均线形态: {ma_trend}")

print(f"\n{'▎ 技术指标':-<60}")
print(f"  RSI(14):    {rsi_val:.1f}  ({rsi_signal})")
print(f"  布林带:     {bb_signal}")
print(f"  成交量:     {vol_signal}（当前为均值 {vol_ratio:.1f} 倍）")

print(f"\n{'▎ 支撑位 & 压力位':-<60}")
if supports:
    print(f"  支撑位:     " + ", ".join(f"${s:.2f}" for s in supports))
if resistances:
    print(f"  压力位:     " + ", ".join(f"${r:.2f}" for r in resistances))

print(f"\n{'▎ 近期新闻':-<60}")
for h in headlines:
    print(f"  · {h}")

print(f"\n{'▎ 综合建议':-<60}")
print(f"  建议: {advice}")
print(f"  理由: {reason}")
print("=" * 60)

# ========== 11. 绘制K线图 ==========
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    row_heights=[0.6, 0.15, 0.25],
)

fig.add_trace(go.Ohlc(
    x=df.index, open=df["Open"], high=df["High"],
    low=df["Low"], close=df["Close"], name="AAPL",
), row=1, col=1)

# 均线
fig.add_trace(go.Scatter(x=df.index, y=sma20, line=dict(color="orange", width=1), name="SMA20"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=sma20 + 2 * std20, line=dict(color="gray", width=1, dash="dash"), name="布林上轨"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=sma20 - 2 * std20, line=dict(color="gray", width=1, dash="dash"), name="布林下轨"), row=1, col=1)

# 支撑 & 压力
# 画虚线标注支撑/压力位
for s in supports:
    fig.add_hline(y=s, line=dict(color="green", width=1, dash="dot"), row=1, col=1)
for r in resistances:
    fig.add_hline(y=r, line=dict(color="red", width=1, dash="dot"), row=1, col=1)

# RSI
fig.add_trace(go.Scatter(x=df.index, y=rsi, line=dict(color="purple", width=1), name="RSI(14)"), row=2, col=1)
fig.add_hline(y=70, line=dict(color="gray", width=1, dash="dash"), row=2, col=1)
fig.add_hline(y=30, line=dict(color="gray", width=1, dash="dash"), row=2, col=1)

# 成交量
colors = ["red" if df["Close"].iloc[i] < df["Open"].iloc[i] else "green" for i in range(len(df))]
fig.add_trace(go.Bar(x=df.index, y=volume, marker_color=colors, name="成交量"), row=3, col=1)

fig.update_layout(
    title=f"AAPL 技术分析报告 ({datetime.now().strftime('%Y-%m-%d')})",
    template="plotly_dark",
    xaxis_rangeslider_visible=False,
    height=900,
    hovermode="x unified",
    margin=dict(l=50, r=50, t=60, b=30),
)
fig.update_yaxes(title_text="价格 (USD)", row=1, col=1)
fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
fig.update_yaxes(title_text="成交量", row=3, col=1)

fig.write_html("stock_analysis.html", auto_open=True)
print("\n图表已保存至 stock_analysis.html")
