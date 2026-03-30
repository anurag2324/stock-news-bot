import feedparser
import requests
import yfinance as yf
import time
import os
from datetime import datetime

# -------- CONFIG --------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = [
    os.getenv("PERSONAL_CHAT_ID"),
    os.getenv("GROUP_CHAT_ID")
]


# -------- SYMBOLS WITH EMOJIS --------
symbols = {
    "📊 S&P 500 (SPX)": "^GSPC",
    "📊 Nasdaq (NDQ)": "^IXIC",
    "📊 Dow Jones (DJI)": "^DJI",
    "⚡ Volatility Index (VIX)": "^VIX",

    "🏢 Apple (AAPL)": "AAPL",
    "🏢 Tesla (TSLA)": "TSLA",
    "🏢 Netflix (NFLX)": "NFLX",

    "🛢️ Crude Oil (USOIL)": "CL=F",
    "🥇 Gold (GOLD)": "GC=F",
    "🥈 Silver (SILVER)": "SI=F"
}

# -------- FETCH MARKET DATA --------
def get_last_two_days_data(ticker):
    try:
        data = yf.download(ticker, period="7d", interval="1d", progress=False)

        if data.empty:
            return None, None

        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        data = data.dropna()

        if len(data) < 2:
            return None, None

        c1 = data["Close"].iloc[-1].item()
        c2 = data["Close"].iloc[-2].item()

        return c1, c2

    except:
        return None, None

# -------- FORMAT CHANGE --------
def format_change(curr, prev):
    change = curr - prev
    percent = (change / prev) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f} ({sign}{percent:.2f}%)"

# -------- TREND EMOJI --------
def get_trend_emoji(change):
    if change > 0:
        return "🟢📈"
    elif change < 0:
        return "🔴📉"
    else:
        return "🟡➖"

# -------- MARKET ANALYSIS --------
def generate_market_analysis(summary_dict):
    try:
        spx = summary_dict.get("📊 S&P 500 (SPX)", 0)
        ndq = summary_dict.get("📊 Nasdaq (NDQ)", 0)
        vix = summary_dict.get("⚡ Volatility Index (VIX)", 0)
        oil = summary_dict.get("🛢️ Crude Oil (USOIL)", 0)
        gold = summary_dict.get("🥇 Gold (GOLD)", 0)

        analysis = "\n📊 Market Insight:\n"

        if spx > 0 and ndq > 0:
            analysis += "🟢 Bullish sentiment in US markets.\n"
        elif spx < 0 and ndq < 0:
            analysis += "🔴 Bearish sentiment in US markets.\n"
        else:
            analysis += "🟡 Mixed signals across indices.\n"

        if vix > 0:
            analysis += "⚠️ Volatility rising — expect swings.\n"
        else:
            analysis += "✅ Volatility stable.\n"

        if oil > 0:
            analysis += "🛢️ Oil up — positive for energy stocks.\n"
        else:
            analysis += "🛢️ Oil down — inflation relief.\n"

        if gold > 0:
            analysis += "🥇 Gold rising — risk-off mood.\n"
        else:
            analysis += "🥇 Gold falling — risk-on mood.\n"

        return analysis

    except:
        return "\n📊 Market Insight not available\n"

# -------- BUILD MARKET SUMMARY --------
market_summary = []
summary_changes = {}

for name, ticker in symbols.items():
    try:
        c1, c2 = get_last_two_days_data(ticker)

        if c1 and c2:
            change_pct = ((c1 - c2) / c2) * 100
            summary_changes[name] = change_pct

            trend = get_trend_emoji(change_pct)
            change_text = format_change(c1, c2)

            market_summary.append(f"{trend} {name}: {c1:.2f} | {change_text}")
        else:
            market_summary.append(f"⚠️ {name}: No Data")

        time.sleep(1)

    except:
        market_summary.append(f"❌ {name}: Error")

market_message = (
    "📊 *US Market Summary*\n"
    "_% Change from yesterday to today_\n\n"
    + "\n".join(market_summary)
)

# -------- MARKET ANALYSIS --------
analysis_text = generate_market_analysis(summary_changes)

# -------- FETCH NEWS --------
urls = [
    "https://news.google.com/rss/search?q=india+stock+market",
    "https://news.google.com/rss/search?q=crude+oil+price",
    "https://news.google.com/rss/search?q=defence+india",
    "https://news.google.com/rss/search?q=earnings+india+stocks"
]

keywords = ["order", "deal", "earnings", "profit", "crude", "war", "contract"]

filtered_news = []
seen = set()

def get_sector(title):
    if "defence" in title:
        return "DEFENCE"
    elif "crude" in title or "oil" in title:
        return "OIL"
    elif "solar" in title or "ev" in title:
        return "EV"
    return "GENERAL"

for url in urls:
    feed = feedparser.parse(url)
    for entry in feed.entries:
        title = entry.title.lower()

        if any(k in title for k in keywords):
            if entry.title not in seen:
                sector = get_sector(title)
                news_item = f"[{sector}] {entry.title}\n{entry.link}"
                filtered_news.append(news_item)
                seen.add(entry.title)

top_news = filtered_news[:5]

if not top_news:
    news_message = "No major tradeable news today."
else:
    news_message = "\n\n".join(top_news)

# -------- FINAL MESSAGE --------
final_message = (
    f"📢 Market Update ({datetime.now().strftime('%d-%b %H:%M')})\n\n"
    + market_message
    + analysis_text
    + "\n\n📰 *Top News:*\n\n"
    + news_message
)

# -------- SEND TO TELEGRAM --------
url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


for cid in CHAT_ID:
    requests.post(url, data={
        "chat_id": cid,
        "text": final_message,
        "parse_mode": "Markdown",
		"disable_web_page_preview": True
    })

print("✅ News + Market sent successfully!")
