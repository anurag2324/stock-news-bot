import requests
import yfinance as yf
import time
import os
from datetime import datetime
import pandas as pd

# -------- CONFIG --------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = [os.getenv("GROUP_CHAT_ID")]

# -------- LOAD SYMBOLS --------
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'EQUITY_L.csv')
df = pd.read_csv(csv_path)
symbols = df['SYMBOL'].tolist()
companies = df['COMPANY'].tolist()

# -------- FUNCTION TO CHECK CROSSOVER --------
MAX_RETRIES = 3
RETRY_DELAY = 10
BATCH_SIZE = 40
TELEGRAM_MAX_CHARS = 3900
company_by_symbol = dict(zip(symbols, companies))


def extract_close_series(data, symbol):
    ticker = symbol + '.NS'
    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        tickers = data.columns.get_level_values(0)
        if ticker not in tickers:
            return None
        close = data[ticker]['Close']
    else:
        if 'Close' not in data.columns:
            return None
        close = data['Close']

    if isinstance(close, pd.DataFrame):
        if close.shape[1] == 0:
            return None
        close = close.iloc[:, 0]

    return close.dropna()


def find_crossover(symbol, close):
    if close is None or len(close) < 200:
        return None

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    if len(close) < 2:
        return None

    crossed = []
    if close.iloc[-2] >= ema20.iloc[-2] and close.iloc[-1] < ema20.iloc[-1]:
        crossed.append('EMA20')
    if close.iloc[-2] >= ema50.iloc[-2] and close.iloc[-1] < ema50.iloc[-1]:
        crossed.append('EMA50')
    if close.iloc[-2] >= ema200.iloc[-2] and close.iloc[-1] < ema200.iloc[-1]:
        crossed.append('EMA200')

    if crossed:
        return {'symbol': symbol, 'company': company_by_symbol.get(symbol, symbol), 'crossed': crossed}
    return None


def download_batch(symbol_batch):
    tickers = [f"{sym}.NS" for sym in symbol_batch]
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            data = yf.download(tickers, period='1y', interval='1d', group_by='ticker', threads=False, progress=False)
            if data is None or data.empty:
                return {}

            results = {}
            for symbol in symbol_batch:
                close = extract_close_series(data, symbol)
                result = find_crossover(symbol, close)
                if result:
                    results[symbol] = result
            return results
        except Exception as exc:
            attempt += 1
            err_text = str(exc)
            print(f"Batch error (attempt {attempt}) for {symbol_batch[:3]}...: {err_text}")
            if 'Too Many Requests' in err_text or 'rate limit' in err_text.lower():
                time.sleep(RETRY_DELAY * attempt)
                continue
            return {}
    return {}


def split_telegram_messages(lines):
    if not lines:
        return ["No companies crossed below EMA recently."]

    messages = []
    current = ["Companies that crossed below EMA recently:"]
    current_len = len(current[0]) + 2

    for line in lines:
        line_text = f"{line}"
        if current_len + len(line_text) + 1 > TELEGRAM_MAX_CHARS:
            messages.append("\n".join(current))
            current = ["Companies that crossed below EMA recently:", line_text]
            current_len = len(current[0]) + len(line_text) + 2
        else:
            current.append(line_text)
            current_len += len(line_text) + 1

    if current:
        messages.append("\n".join(current))
    return messages


# -------- PROCESS SYMBOLS --------
results = []
for start in range(0, len(symbols), BATCH_SIZE):
    batch = symbols[start:start + BATCH_SIZE]
    batch_results = download_batch(batch)
    results.extend(batch_results.values())
    time.sleep(1)

# -------- BUILD MESSAGES --------
lines = [f"**{r['company']}** ({r['symbol']}): {', '.join(r['crossed'])}" for r in results]
messages = split_telegram_messages(lines)

# -------- SEND TO TELEGRAM --------
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    if not CHAT_ID:
        raise ValueError("No CHAT_ID configured")

    for msg in messages:
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True
                },
                timeout=10,
            )

            if response.status_code == 200:
                print(f"✅ Sent successfully to {CHAT_ID}")
            else:
                print(f"❌ Telegram Error for {CHAT_ID}:", response.text)

        except Exception as e:
            print(f"❌ Script Error for {CHAT_ID}:", str(e))

except Exception as e:
    print("❌ Script Error:", str(e))