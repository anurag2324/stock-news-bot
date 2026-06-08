import requests
import yfinance as yf
import time
import os
from datetime import datetime
import pandas as pd
import numpy as np

# -------- CONFIG --------
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("GROUP_CHAT_ID") or os.getenv("CHAT_ID")
print("Loaded BOT_TOKEN:", "Yes" if BOT_TOKEN else "No")
print("Loaded CHAT_ID from GROUP_CHAT_ID or CHAT_ID:", "Yes" if CHAT_ID else "No")

# -------- LOAD SYMBOLS --------
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Stock_Above5k.csv')
df = pd.read_csv(csv_path)
symbols = df['SYMBOL'].tolist()
companies = df['COMPANY'].tolist()
market_caps = df['MARKET CAP'].tolist() if 'MARKET CAP' in df.columns else [None] * len(symbols)

# -------- FUNCTION TO CHECK CROSSOVER --------
MAX_RETRIES = 3
RETRY_DELAY = 10
BATCH_SIZE = 40
TELEGRAM_MAX_CHARS = 3900
company_by_symbol = dict(zip(symbols, companies))
market_cap_by_symbol = dict(zip(symbols, market_caps))
# New stricter filters
MIN_AVG_VOLUME = 100000
MIN_DAYS = 120
MAX_RESULTS = 20


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


def extract_volume_series(data, symbol):
    ticker = symbol + '.NS'
    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        tickers = data.columns.get_level_values(0)
        if ticker not in tickers:
            return None
        volume = data[ticker]['Volume']
    else:
        if 'Volume' not in data.columns:
            return None
        volume = data['Volume']

    if isinstance(volume, pd.DataFrame):
        if volume.shape[1] == 0:
            return None
        volume = volume.iloc[:, 0]

    return volume.dropna()


def evaluate_signals(close, short_span=20, long_span=50, hold_days=5):
    """Simple forward-test of EMA crossover signals over historical `close` series.
    Returns accuracy (fraction of signals that were profitable after `hold_days`) and average return.
    """
    if close is None or len(close) < max(long_span, hold_days) + 10:
        return None

    ema_short = close.ewm(span=short_span, adjust=False).mean()
    ema_long = close.ewm(span=long_span, adjust=False).mean()

    bullish = (ema_short > ema_long).astype(float)
    crossover = bullish.diff()

    signals_idx = crossover[(crossover == 1.0) | (crossover == -1.0)].index
    if signals_idx.empty:
        return {'accuracy': None, 'avg_return': None, 'signals': 0}

    profits = []
    for t in signals_idx:
        try:
            i = close.index.get_loc(t)
        except Exception:
            continue
        entry_price = close.iloc[i]
        exit_i = i + hold_days
        if exit_i >= len(close):
            continue
        exit_price = close.iloc[exit_i]
        ret = (exit_price - entry_price) / entry_price
        # For sell signals (-1), invert return to treat as correct if price fell
        if crossover.loc[t] == -1.0:
            ret = -ret
        profits.append(ret)

    if not profits:
        return {'accuracy': None, 'avg_return': None, 'signals': 0}

    profitable = sum(1 for p in profits if p > 0)
    accuracy = profitable / len(profits)
    avg_ret = float(np.mean(profits))
    return {'accuracy': float(accuracy), 'avg_return': avg_ret, 'signals': len(profits)}


def find_crossover(symbol, close, volume):
    if close is None or len(close) < MIN_DAYS:
        return None

    if volume is None or len(volume) == 0:
        return None

    # use average volume over the last 10-20 days for stability
    vol_window = 20 if len(volume) >= 20 else max(5, len(volume))
    avg_vol = volume.iloc[-vol_window:].mean()
    if avg_vol < MIN_AVG_VOLUME:
        return None

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    if len(close) < 2:
        return None

    bullish = (ema20 > ema50).astype(float)
    crossover = bullish.diff()
    last_cross = crossover.iloc[-1]

    reasons = []
    signal_type = None

    # Bullish cross: short EMA crosses above long EMA
    if last_cross == 1.0:
        # require price above EMA200 for trend confirmation
        if close.iloc[-1] > ema200.iloc[-1]:
            signal_type = 'buy'
            reasons.append('EMA20 crossed above EMA50')
            reasons.append('Price above EMA200')
        else:
            # if not above EMA200, weaken signal but still report as possible
            signal_type = 'buy'
            reasons.append('EMA20 crossed above EMA50 (below EMA200)')

    # Bearish cross: short EMA crosses below long EMA
    elif last_cross == -1.0:
        signal_type = 'sell'
        reasons.append('EMA20 crossed below EMA50')
        if close.iloc[-1] < ema200.iloc[-1]:
            reasons.append('Price below EMA200')

    if signal_type is None:
        return None

    # severity score: magnitude of crossover and distance from EMA50/EMA200
    pct_from_50 = abs(close.iloc[-1] - ema50.iloc[-1]) / ema50.iloc[-1]
    pct_from_200 = abs(close.iloc[-1] - ema200.iloc[-1]) / ema200.iloc[-1]
    score = float(max(pct_from_50, pct_from_200))

    # evaluate historical signal accuracy (quick forward-test)
    eval_stats = evaluate_signals(close)

    return {
        'symbol': symbol,
        'company': company_by_symbol.get(symbol, symbol),
        'market_cap': market_cap_by_symbol.get(symbol),
        'reasons': reasons,
        'avg_vol': int(avg_vol),
        'score': float(score),
        'last_price': float(close.iloc[-1]),
        'signal': signal_type,
        'eval': eval_stats,
    }


def download_batch(symbol_batch):
    tickers = [f"{sym}.NS" for sym in symbol_batch]
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            data = yf.download(tickers, period='1y', interval='1d', group_by='ticker', threads=False, progress=False)
            # if data is empty (some tickers delisted), continue — per-symbol extraction will skip missing symbols

            results = {}
            for symbol in symbol_batch:
                close = extract_close_series(data, symbol)
                volume = extract_volume_series(data, symbol)
                result = find_crossover(symbol, close, volume)
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
        return ["No Stock_Above5k stocks are near EMA20/50/200 recently."]

    messages = []
    current = ["Companies Near EMA 20/50/200:"]
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

print("Stock_Above5k stocks who are near to EMA20/50 or EMA200:")

# -------- BUILD MESSAGES --------
# sort by severity score and limit results to most relevant
sorted_results = sorted(results, key=lambda r: r.get('score', 0), reverse=True)
top_results = sorted_results[:MAX_RESULTS]

lines = []
for r in top_results:
    sym = r.get('symbol')
    name = r.get('company')
    sig = r.get('signal', '')
    price = r.get('last_price')
    eval_stats = r.get('eval') or {}
    acc = eval_stats.get('accuracy')
    avg_ret = eval_stats.get('avg_return')
    signals_count = eval_stats.get('signals') or 0

    acc_text = f"{acc:.2f}" if acc is not None else "N/A"
    avg_text = f"{avg_ret:.2%}" if avg_ret is not None else "N/A"

    lines.append(f"{name} ({sym}): {sig.upper()} @ {price:.2f} | acc={acc_text} avg={avg_text} signals={signals_count}")

if not lines:
    lines = ["No Stock_Above5k stocks matched stricter EMA filters today."]

messages = split_telegram_messages(lines)

# -------- SEND TO TELEGRAM --------
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    if not CHAT_ID:
        raise ValueError("No CHAT_ID configured")

    for msg in messages:
        try:
            print(f"Sending Telegram message to chat_id={CHAT_ID} with {len(msg)} chars")
            base_payload = {
                "chat_id": CHAT_ID,
                "text": msg,
                "disable_web_page_preview": True
            }
            # try with Markdown first, then fallback to plain text if Telegram can't parse entities
            md_payload = dict(base_payload)
            md_payload["parse_mode"] = "Markdown"

            response = requests.post(url, data=md_payload, timeout=10)
            if response.status_code == 200:
                print(f"✅ Sent successfully to {CHAT_ID} (Markdown)")
            else:
                resp_text = response.text or ""
                if "can't parse entities" in resp_text or "Can't find end of the entity" in resp_text:
                    # retry without parse mode
                    response2 = requests.post(url, data=base_payload, timeout=10)
                    if response2.status_code == 200:
                        print(f"✅ Sent successfully to {CHAT_ID} (plain)")
                    else:
                        print(f"❌ Telegram Error for {CHAT_ID} (plain):", response2.text)
                else:
                    print(f"❌ Telegram Error for {CHAT_ID}:", response.text)

        except Exception as e:
            print(f"❌ Script Error for {CHAT_ID}:", str(e))

except Exception as e:
    print("❌ Script Error:", str(e))
