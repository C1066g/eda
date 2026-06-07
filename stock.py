import yfinance as yf
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta

# 用自定义 session 避免限流
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

# 获取 AAPL 最近3个月数据
end = datetime.now()
start = end - timedelta(days=90)
df = yf.download("AAPL", start=start, end=end, session=session)

# 拍平 MultiIndex 列名
df.columns = [col[0] for col in df.columns]

# 画K线图
fig = go.Figure(data=go.Ohlc(
    x=df.index,
    open=df["Open"],
    high=df["High"],
    low=df["Low"],
    close=df["Close"],
    name="AAPL"
))

fig.update_layout(
    title="AAPL K线图",
    xaxis_title="日期",
    yaxis_title="价格 (USD)",
    template="plotly_dark",
    xaxis_rangeslider_visible=False,
)

fig.write_html("stock.html", auto_open=True)
