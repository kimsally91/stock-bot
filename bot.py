import os, sys, time, requests
import pandas as pd
import FinanceDataReader as fdr

TOKEN = os.getenv("BOT_TOKEN")

WATCH_LIST = {}
ALERTED_VOLUME = {}
CACHE = {}
last_update_id = 0
last_watch_check = 0

CACHE_SECONDS = 60
WATCH_CHECK_SECONDS = 60

print("① 종목 데이터 로드 중...")

try:
    stock_df = fdr.StockListing("KRX")[["Code", "Name"]].copy()
    etf_df = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].copy()
    etf_df.rename(columns={"Symbol": "Code"}, inplace=True)
    stocks = pd.concat([stock_df, etf_df], ignore_index=True)
    stocks["CleanName"] = stocks["Name"].str.replace(" ", "").str.lower()
    print(f"▶ 총 {len(stocks):,}개 종목 로드 완료")
except Exception as e:
    print(f"데이터 로드 실패: {e}")
    sys.exit()


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        data["reply_markup"] = reply_markup

    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=data)


def get_df(code):
    now = time.time()

    if code in CACHE:
        saved_time, saved_df = CACHE[code]
        if now - saved_time < CACHE_SECONDS:
            return saved_df

    df = fdr.DataReader(code)
    CACHE[code] = (now, df)
    return df


def calc(df):
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()
    df["VMA20"] = df["Volume"].rolling(20).mean()

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI"] = 100 - (100 / (1 + rs))

    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = exp1 - exp2
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    return df


def clean(text):
    t = text.strip().replace(" ", "").lower()
    t = t.replace("코덱스", "kodex").replace("코덱", "kodex")
    t = t.replace("타이거", "tiger").replace("라이즈", "rise")
    t = t.replace("에스케이", "sk").replace("엘지", "lg").replace("지에스", "gs")
    return t


def generate_report(code, name):
    try:
        df = get_df(code)

        if df.empty or len(df) < 60:
            return f"❌ {name} 데이터 부족"

        df = calc(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close = int(latest["Close"])
        prev_close = int(prev["Close"])
        rate = ((close - prev_close) / prev_close) * 100

        volume = int(latest["Volume"])
        volume_mult = volume / (latest["VMA20"] if latest["VMA20"] > 0 else 1)

        ma5, ma20, ma60 = latest["MA5"], latest["MA20"], latest["MA60"]
        rsi = latest["RSI"]
        macd, signal = latest["MACD"], latest["Signal"]

        high20 = df["High"].rolling(20).max().iloc[-1]
        low20 = df["Low"].rolling(20).min().iloc[-1]

        if ma5 > ma20 > ma60:
            trend = "강세 📈"
            ribbon = "정배열"
        elif ma5 < ma20 < ma60:
            trend = "약세 📉"
            ribbon = "역배열"
        else:
            trend = "탐색중 🔄"
            ribbon = "밀집"

        rsi_status = "과열 🔥" if rsi > 70 else "과매도 🧊" if rsi < 30 else "정상 ⚪"
        macd_status = "골든 🚀" if macd > signal else "데드 📉"
        whale = "🐳 감지" if volume_mult > 2.5 and rate > 3 else "특이 없음"

        target = int(max(high20, close * 1.1))
        stop = int(ma60 if close > ma20 else low20)

        return f"""
📋 *[{name}] 한눈에 리포트*

💰 현재가: {close:,}원 ({rate:+.2f}%)
🔥 거래량: 평균 대비 {volume_mult:.1f}배
🐳 세력 흔적: {whale}

📈 추세: {trend}
🎗 리본: {ribbon}
📊 RSI: {rsi:.1f} ({rsi_status})
📉 MACD: {macd_status}

🛡 생명선: {int(ma20):,}원
🎯 목표가: {target:,}원
⚠️ 손절가: {stop:,}원

🔗 https://finance.naver.com/item/main.naver?code={code}
"""

    except Exception as e:
        return f"❌ [{name}] 분석 에러: {e}"


def check_volume_spike(code, name):
    try:
        df = get_df(code)

        if df.empty or len(df) < 25:
            return None

        df = calc(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close = int(latest["Close"])
        prev_close = int(prev["Close"])
        rate = ((close - prev_close) / prev_close) * 100

        volume = int(latest["Volume"])
        volume_mult = volume / (latest["VMA20"] if latest["VMA20"] > 0 else 1)

        if volume_mult >= 3 and rate >= 2:
            return f"""
🚨 *거래량 급증 포착*

📌 종목: {name}
💰 현재가: {close:,}원 ({rate:+.2f}%)
🔥 거래량: 평균 대비 {volume_mult:.1f}배

🤖 의견:
거래량이 크게 붙었습니다.
추격보다 눌림/돌파 안착 확인!
"""
        return None

    except Exception as e:
        print(f"거래량 감시 에러: {name} / {e}")
        return None


print("② 빠른 버전 주식 비서 봇 시작!")


while True:
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=3"
        res = requests.get(url).json()

        for update in res.get("result", []):
            last_update_id = update["update_id"]

            if "callback_query" in update:
                callback = update["callback_query"]
                chat_id = callback["message"]["chat"]["id"]
                data = callback["data"]

                requests.post(
                    f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                    json={"callback_query_id": callback["id"]},
                )

                if data.startswith("ALERT_TOGGLE:"):
                    _, code, name = data.split(":")

                    if chat_id not in WATCH_LIST:
                        WATCH_LIST[chat_id] = {}

                    if code in WATCH_LIST[chat_id]:
                        del WATCH_LIST[chat_id][code]
                        send_message(chat_id, f"🔕 [{name}] 알림 해제")
                    else:
                        WATCH_LIST[chat_id][code] = {"name": name}
                        send_message(chat_id, f"🔔 [{name}] 알림 등록")

                    continue

                code, name = data.split(":")
                msg = generate_report(code, name)

                is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]
                btn = "🔕 알림 해제" if is_watched else "🔔 알림 등록"

                send_message(
                    chat_id,
                    msg,
                    {"inline_keyboard": [[{"text": btn, "callback_data": f"ALERT_TOGGLE:{code}:{name}"}]]},
                )

            elif "message" in update and "text" in update["message"]:
                chat_id = update["message"]["chat"]["id"]
                text = update["message"]["text"].strip()

                search_text = clean(text)
                match = stocks[stocks["CleanName"].str.contains(search_text, case=False, na=False)]

                if match.empty:
                    send_message(chat_id, f"❓ '{text}' 종목을 못 찾았어")

                elif len(match) == 1:
                    code = match.iloc[0]["Code"]
                    name = match.iloc[0]["Name"]

                    msg = generate_report(code, name)

                    is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]
                    btn = "🔕 알림 해제" if is_watched else "🔔 알림 등록"

                    send_message(
                        chat_id,
                        msg,
                        {"inline_keyboard": [[{"text": btn, "callback_data": f"ALERT_TOGGLE:{code}:{name}"}]]},
                    )

                else:
                    match = match.head(10)
                    keyboard = []

                    for _, row in match.iterrows():
                        keyboard.append([{"text": row["Name"], "callback_data": f"{row['Code']}:{row['Name']}"}])

                    send_message(
                        chat_id,
                        f"🔍 *'{text}' 검색 결과*\n원하는 종목 선택!",
                        {"inline_keyboard": keyboard},
                    )

        now = time.time()

        if now - last_watch_check >= WATCH_CHECK_SECONDS:
            last_watch_check = now

            for chat_id, items in WATCH_LIST.items():
                for code, info in items.items():
                    name = info["name"]
                    today = str(pd.Timestamp.today().date())
                    key = f"{chat_id}_{code}_{today}"

                    if key in ALERTED_VOLUME:
                        continue

                    msg = check_volume_spike(code, name)

                    if msg:
                        send_message(chat_id, msg)
                        ALERTED_VOLUME[key] = True

    except Exception as e:
        print(f"루프 에러: {e}")

    time.sleep(2)


from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Stock Bot Running!"

def run():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run).start()
