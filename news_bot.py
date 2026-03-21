import feedparser
import requests

import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

urls = [
    "https://news.google.com/rss/search?q=india+stock+market",
    "https://news.google.com/rss/search?q=crude+oil+price",
    "https://news.google.com/rss/search?q=defence+india",
    "https://news.google.com/rss/search?q=earnings+india+stocks"
]

keywords = ["order", "deal", "earnings", "profit", "crude", "war", "contract"]

# -------- FETCH NEWS --------
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

# -------- LIMIT NEWS --------
top_news = filtered_news[:5]

if not top_news:
    message = "No major tradeable news today."
else:
    message = "\n\n".join(top_news)

# -------- SEND TO TELEGRAM --------
url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
requests.post(url, data={"chat_id": CHAT_ID, "text": message})

print("News sent successfully!")