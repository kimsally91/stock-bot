import os, sys, time, requests
import pandas as pd
import FinanceDataReader as fdr
from flask import Flask
from threading import Thread

TOKEN = os.getenv("BOT_TOKEN")

WATCH_LIST = {}
ALERTED_VOLUME = {}
CACHE = {}

last_update_id = 0
last_watch_check = 0

CACHE_SECONDS = 60
WATCH_CHECK_SECONDS = 300
ALERT_COOLDOWN = 600

TOP_N = 10

print("① 종목 데이터 로드 중...")

try:
    stock_df = fdr.StockListing("KRX")[["Code", "Name", "Marcap"]].copy()

    etf_df = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].copy()
    etf_df.rename(columns={"Symbol": "Code"}, inplace=True)
    etf_df["Marcap"] = 0

    stocks = pd.concat([stock_df, etf_df], ignore_index=True)
    stocks["CleanName"] = stocks["Name"].str.replace(" ", "").str.lower()

    print(f"▶ 총 {len(stocks):,}개 종목 로드 완료")

except Exception as e:
    print(f"데이터 로드 실패: {e}")
    sys.exit()


app = Flask("")

@app.route("/")
def home():
    return "Stock Bot Running!"

def run():
    app.run(host="0.0.0.0", port=10000)

Thread(target=run).start()


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

        ma5 = latest["MA5"]
        ma20 = latest["MA20"]
        ma60 = latest["MA60"]

        rsi = latest["RSI"]
        macd = latest["MACD"]
        signal = latest["Signal"]

        high20 = df["High"].rolling(20).max().iloc[-2]
        low20 = df["Low"].rolling(20).min().iloc[-2]

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
        whale = "🐳 감지" if volume_mult > 2 and rate > 1.5 else "특이 없음"

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


def check_signal(code, name):
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

        high20 = df["High"].rolling(20).max().iloc[-2]
        ma20 = latest["MA20"]
        rsi = latest["RSI"]

        if volume_mult >= 2 and rate >= 1.5:
            return f"""
🚨 *거래량 급증 포착*

📌 종목: {name}
💰 현재가: {close:,}원 ({rate:+.2f}%)
🔥 거래량: 평균 대비 {volume_mult:.1f}배

🤖 의견:
초기 수급 붙는 중.
눌림/돌파 체크!
"""

        if close > high20:
            return f"""
🚀 *전고 돌파 감지*

📌 종목: {name}
💰 현재가: {close:,}원
🔥 20일 고점 돌파 시도

🤖 의견:
단타 수급 집중 가능성!
"""

        if close < ma20:
            return f"""
📉 *생명선 이탈*

📌 종목: {name}
💰 현재가: {close:,}원
🛡 생명선: {int(ma20):,}원

🤖 의견:
단기 추세 약화 주의!
"""

        if rsi >= 75:
            return f"""
🔥 *RSI 과열*

📌 종목: {name}
💰 현재가: {close:,}원
📊 RSI: {rsi:.1f}

🤖 의견:
단기 과열 구간.
추격매수 주의!
"""

        return None

    except Exception as e:
        print(f"감시 에러: {name} / {e}")
        return None


def get_marketcap_top10():
    try:
        krx = fdr.StockListing("KRX")
        krx = krx[["Code", "Name", "Marcap"]]
        krx = krx.sort_values(by="Marcap", ascending=False)
        return krx.head(TOP_N)
    except Exception as e:
        print(f"시총10 추출 실패: {e}")
        return pd.DataFrame()


def get_hot10_stocks():
    try:
        base = fdr.StockListing("KRX")
        base = base[["Code", "Name", "Marcap"]]
        base = base.sort_values(by="Marcap", ascending=False).head(150)

        hot_list = []

        for _, row in base.iterrows():
            try:
                code = row["Code"]
                name = row["Name"]

                df = get_df(code)

                if df.empty or len(df) < 20:
                    continue

                latest = df.iloc[-1]
                prev = df.iloc[-2]

                close = latest["Close"]
                prev_close = prev["Close"]
                volume = latest["Volume"]

                if prev_close <= 0:
                    continue

                rate = ((close - prev_close) / prev_close) * 100
                trade_value = close * volume

                score = trade_value * max(rate, 0)

                hot_list.append({
                    "code": code,
                    "name": name,
                    "rate": rate,
                    "trade_value": trade_value,
                    "score": score
                })

            except:
                continue

        hot_df = pd.DataFrame(hot_list)

        if hot_df.empty:
            return hot_df

        hot_df = hot_df.sort_values(by="score", ascending=False)
        return hot_df.head(TOP_N)

    except Exception as e:
        print(f"핫10 추출 실패: {e}")
        return pd.DataFrame()


print("② 단타 비서 봇 시작!")


while True:
    try:
        url = (
            f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            f"?offset={last_update_id + 1}&timeout=3"
        )

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
                    {
                        "inline_keyboard": [[
                            {
                                "text": btn,
                                "callback_data": f"ALERT_TOGGLE:{code}:{name}"
                            }
                        ]]
                    }
                )

            elif "message" in update and "text" in update["message"]:
                chat_id = update["message"]["chat"]["id"]
                text = update["message"]["text"].strip()

                if text in ["시총10", "탑10"]:
                    top10 = get_marketcap_top10()

                    if top10.empty:
                        send_message(chat_id, "❌ 시총10 데이터를 못 가져왔어")
                        continue

                    msg = "🏢 *시가총액 TOP10*\n\n"
                    rank = 1

                    for _, row in top10.iterrows():
                        marcap_jo = int(row["Marcap"] / 1000000000000)
                        msg += f"{rank}. {row['Name']} - {marcap_jo:,}조\n"
                        rank += 1

                    send_message(chat_id, msg)
                    continue

                if text == "핫10":
                    hot10 = get_hot10_stocks()

                    if hot10.empty:
                        send_message(chat_id, "❌ 핫10 데이터를 못 가져왔어")
                        continue

                    msg = "🔥 *오늘 핫한 TOP10*\n\n"
                    rank = 1

                    for _, row in hot10.iterrows():
                        rate = row["rate"]
                        trade_value = int(row["trade_value"] / 100000000)
                        msg += f"{rank}. {row['name']} ({rate:+.2f}%) - {trade_value:,}억\n"
                        rank += 1

                    msg += "\n💡 거래대금 + 상승률 기준"
                    send_message(chat_id, msg)
                    continue

                search_text = clean(text)

                match = stocks[
                    stocks["CleanName"].str.contains(
                        search_text,
                        case=False,
                        na=False
                    )
                ]

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
                        {
                            "inline_keyboard": [[
                                {
                                    "text": btn,
                                    "callback_data": f"ALERT_TOGGLE:{code}:{name}"
                                }
                            ]]
                        }
                    )

                else:
                    match = match.head(10)
                    keyboard = []

                    for _, row in match.iterrows():
                        keyboard.append([
                            {
                                "text": row["Name"],
                                "callback_data": f"{row['Code']}:{row['Name']}"
                            }
                        ])

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
                    key = f"{chat_id}_{code}"

                    now_time = time.time()

                    if key in ALERTED_VOLUME:
                        last_alert = ALERTED_VOLUME[key]

                        if now_time - last_alert < ALERT_COOLDOWN:
                            continue

                    msg = check_signal(code, name)

                    if msg:
                        send_message(chat_id, msg)
                        ALERTED_VOLUME[key] = time.time()

    except Exception as e:
        print(f"루프 에러: {e}")

    time.sleep(2)
