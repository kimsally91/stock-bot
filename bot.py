import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import FinanceDataReader as fdr

TOKEN = os.getenv("BOT_TOKEN")

print("① 주식/ETF 데이터 로드 중...")

try:
    stock_df = fdr.StockListing("KRX")[["Code", "Name"]].copy()
    etf_df = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].copy()
    etf_df.rename(columns={"Symbol": "Code"}, inplace=True)

    stocks = pd.concat([stock_df, etf_df], ignore_index=True)
    stocks["CleanName"] = stocks["Name"].str.replace(" ", "").str.lower()

    print(f"▶ 총 {len(stocks):,}개 종목 로드 완료!")

except Exception as e:
    print(f"데이터 로드 실패: {e}")
    sys.exit()


WATCH_LIST = {}
ALERTED_VOLUME = {}
last_update_id = 0


def calculate_indicators(df):
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


def clean_and_convert_text(text):
    t = text.strip().replace(" ", "").lower()
    t = t.replace("코덱스", "kodex").replace("코덱", "kodex")
    t = t.replace("타이거", "tiger").replace("라이즈", "rise")
    t = t.replace("에스케이", "sk").replace("엘지", "lg").replace("지에스", "gs")
    return t


def generate_report(code, real_name):
    try:
        df = fdr.DataReader(code)

        if df.empty or len(df) < 60:
            return f"❌ {real_name} 데이터가 부족해서 분석할 수 없습니다."

        df = calculate_indicators(df)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close_val = int(latest["Close"])
        prev_close = int(prev["Close"])
        chg_rate = ((close_val - prev_close) / prev_close) * 100

        volume = int(latest["Volume"])
        vma20 = latest["VMA20"] if latest["VMA20"] > 0 else 1
        volume_mult = volume / vma20

        ma5 = latest["MA5"]
        ma20 = latest["MA20"]
        ma60 = latest["MA60"]
        rsi = latest["RSI"]
        macd = latest["MACD"]
        signal = latest["Signal"]

        high20 = df["High"].rolling(20).max().iloc[-1]
        low20 = df["Low"].rolling(20).min().iloc[-1]

        if ma5 > ma20 > ma60:
            trend_status = "강세 📈"
            ribbon = "정배열"
        elif ma5 < ma20 < ma60:
            trend_status = "약세 📉"
            ribbon = "역배열"
        else:
            trend_status = "탐색중 🔄"
            ribbon = "이평선 밀집"

        macd_status = "골든크로스 🚀" if macd > signal else "데드크로스 📉"

        if rsi > 70:
            rsi_status = "과열 🔥"
        elif rsi < 30:
            rsi_status = "과매도 🧊"
        else:
            rsi_status = "정상 ⚪"

        target_price = int(max(high20, close_val * 1.10))
        stop_loss = int(ma60 if close_val > ma20 else low20)

        whale_trace = "🐳 감지" if volume_mult > 2.5 and chg_rate > 3 else "특이 없음"

        msg = f"""
📋 *[{real_name}] 한눈에 시황 리포트*
📅 기준일: {str(latest.name).split()[0]}
━━━━━━━━━━━━━━

💰 현재가: {close_val:,}원 ({chg_rate:+.2f}%)
🔥 거래량: 평균 대비 {volume_mult:.1f}배
🐳 세력 흔적: {whale_trace}

📈 추세: {trend_status}
🎗 리본: {ribbon}
📊 RSI: {rsi:.1f} ({rsi_status})
📉 MACD: {macd_status}

🛡 생명선: {int(ma20):,}원
🎯 목표가: {target_price:,}원
⚠️ 손절가: {stop_loss:,}원

🔗 [네이버 증권 보기](https://finance.naver.com/item/main.naver?code={code})
"""
        return msg

    except Exception as e:
        return f"❌ [{real_name}] 분석 중 에러 발생: {e}"


def check_volume_spike(code, real_name):
    try:
        df = fdr.DataReader(code)

        if df.empty or len(df) < 25:
            return None

        df = calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        close_val = int(latest["Close"])
        prev_close = int(prev["Close"])
        chg_rate = ((close_val - prev_close) / prev_close) * 100

        volume = int(latest["Volume"])
        vma20 = latest["VMA20"] if latest["VMA20"] > 0 else 1
        volume_mult = volume / vma20

        if volume_mult >= 3 and chg_rate >= 2:
            msg = f"""
🚨 거래량 급증 포착

📌 종목: {real_name}
💰 현재가: {close_val:,}원 ({chg_rate:+.2f}%)
🔥 거래량: 평균 대비 {volume_mult:.1f}배
🧾 거래량: {volume:,}주

🤖 의견:
거래량이 평소보다 크게 붙었습니다.
추격매수보다는 눌림/돌파 안착 확인이 좋습니다.
"""
            return msg

        return None

    except Exception as e:
        print(f"거래량 감시 에러: {real_name} / {e}")
        return None


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json=data,
    )


print("② 주식 비서 봇 가동 시작!")


while True:
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
        res = requests.get(url).json()

        if "result" in res:
            for update in res["result"]:
                last_update_id = update["update_id"]

                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback["message"]["chat"]["id"]
                    callback_data = callback["data"]

                    requests.post(
                        f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": callback["id"]},
                    )

                    if callback_data.startswith("ALERT_TOGGLE:"):
                        _, code, real_name = callback_data.split(":")

                        if chat_id not in WATCH_LIST:
                            WATCH_LIST[chat_id] = {}

                        if code in WATCH_LIST[chat_id]:
                            del WATCH_LIST[chat_id][code]
                            send_message(chat_id, f"🔕 [{real_name}] 실시간 알림 해제!")
                        else:
                            WATCH_LIST[chat_id][code] = {"name": real_name}
                            send_message(chat_id, f"🔔 [{real_name}] 실시간 알림 등록!")

                        continue

                    code, real_name = callback_data.split(":")
                    msg = generate_report(code, real_name)

                    is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]
                    btn_text = "🔕 실시간 알림 해제" if is_watched else "🔔 실시간 알림 등록"

                    reply_markup = {
                        "inline_keyboard": [
                            [{"text": btn_text, "callback_data": f"ALERT_TOGGLE:{code}:{real_name}"}]
                        ]
                    }

                    send_message(chat_id, msg, reply_markup)
                    continue

                if "message" in update and "text" in update["message"]:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"]["text"].strip()

                    search_text = clean_and_convert_text(text)
                    match = stocks[stocks["CleanName"].str.contains(search_text, case=False, na=False)]

                    if match.empty:
                        send_message(chat_id, f"❓ '{text}' 종목이나 ETF를 찾지 못했습니다.")

                    elif len(match) == 1:
                        code = match.iloc[0]["Code"]
                        real_name = match.iloc[0]["Name"]

                        msg = generate_report(code, real_name)

                        is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]
                        btn_text = "🔕 실시간 알림 해제" if is_watched else "🔔 실시간 알림 등록"

                        reply_markup = {
                            "inline_keyboard": [
                                [{"text": btn_text, "callback_data": f"ALERT_TOGGLE:{code}:{real_name}"}]
                            ]
                        }

                        send_message(chat_id, msg, reply_markup)

                    else:
                        match = match.head(10)
                        inline_keyboard = []

                        for _, row in match.iterrows():
                            inline_keyboard.append(
                                [{"text": row["Name"], "callback_data": f"{row['Code']}:{row['Name']}"}]
                            )

                        msg = f"🔍 *'{text}' 관련 종목 검색 결과 ({len(match)}개)*\n원하시는 종목을 아래 버튼에서 선택해 주세요!"

                        send_message(
                            chat_id,
                            msg,
                            {"inline_keyboard": inline_keyboard},
                        )

        # 🔥 등록 종목 거래량 급증 자동 감시
        for chat_id, items in WATCH_LIST.items():
            for code, info in items.items():
                real_name = info["name"]
                alert_key = f"{chat_id}_{code}_{pd.Timestamp.today().date()}"

                msg = check_volume_spike(code, real_name)

                if msg and alert_key not in ALERTED_VOLUME:
                    send_message(chat_id, msg)
                    ALERTED_VOLUME[alert_key] = True

    except Exception as e:
        print(f"루프 에러: {e}")

    time.sleep(10)
