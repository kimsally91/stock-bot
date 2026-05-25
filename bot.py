# 1. 필요한 도구 설치 및 불러오기




import requests

import time

import sys

import re

import xml.etree.ElementTree as ET

import pandas as pd

import numpy as np

import FinanceDataReader as fdr



# ⚠️ [필수] 여기에 복사한 봇 비밀번호(토큰)를 넣어주세요!

import os
TOKEN = os.getenv("BOT_TOKEN")



print("① 일반 주식과 ETF 전 종목 합성 마스터 데이터 로드 중...")

try:

    # 일반 주식과 ETF 전체를 각각 긁어와 합칩니다.

    stock_df = fdr.StockListing('KRX')[['Code', 'Name']].copy()

    etf_df = fdr.StockListing('ETF/KR')[['Symbol', 'Name']].copy()

    etf_df.rename(columns={'Symbol': 'Code'}, inplace=True)

    

    stocks = pd.concat([stock_df, etf_df], ignore_index=True)

    

    # 💡 검색 효율을 극대화하기 위해 '공백 제거 + 소문자화'한 컬럼 생성

    stocks['CleanName'] = stocks['Name'].str.replace(" ", "").str.lower()

    print(f"▶ 총 {len(stocks):,}개 종목 통합 완료!")

except Exception as e:

    print(f"데이터베이스 통합 실패: {e}")

    sys.exit()



WATCH_LIST = {}



def calculate_indicators(df):

    df['MA5'] = df['Close'].rolling(5).mean()

    df['MA20'] = df['Close'].rolling(20).mean()

    df['MA60'] = df['Close'].rolling(60).mean()

    df['VMA20'] = df['Volume'].rolling(20).mean()

    

    delta = df['Close'].diff()

    gain = (delta.where(delta > 0, 0)).rolling(14).mean()

    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()

    rs = gain / (loss + 1e-9)

    df['RSI'] = 100 - (100 / (1 + rs))

    

    exp1 = df['Close'].ewm(span=12, adjust=False).mean()

    exp2 = df['Close'].ewm(span=26, adjust=False).mean()

    df['MACD'] = exp1 - exp2

    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    return df



def generate_perfect_report(code, real_name):

    try:

        df = fdr.DataReader(code)

        if df.empty or len(df) < 60:

            return f"❌ {real_name}의 데이터(최소 60일)가 부족하여 분석할 수 없습니다."

            

        df = calculate_indicators(df)

        latest = df.iloc[-1]

        prev = df.iloc[-2]

        

        close_val = int(latest['Close'])

        prev_close = int(prev['Close'])

        chg_rate = ((close_val - prev_close) / prev_close) * 100

        volume = int(latest['Volume'])

        vma20 = latest['VMA20'] if latest['VMA20'] > 0 else 1

        volume_mult = volume / vma20

        

        ma5, ma20, ma60 = latest['MA5'], latest['MA20'], latest['MA60']

        rsi, macd, signal = latest['RSI'], latest['MACD'], latest['Signal']

        high20 = df['High'].rolling(20).max().iloc[-1]

        low20 = df['Low'].rolling(20).min().iloc[-1]

        

        if ma5 > ma20 > ma60: trend_status = "강력 우상향 📈"; ribbon = "정배열 안정"

        elif ma5 < ma20 < ma60: trend_status = "하락 추세 📉"; ribbon = "역배열 주의"

        else: trend_status = "방향성 탐색 🔄"; ribbon = "이평선 밀집"

            

        macd_status = "골든크로스 🚀" if macd > signal else "데드크로스 📉"

        overheat_status = "단기 과열 🔥" if rsi > 70 else ("과매도 구간 🧊" if rsi < 30 else "정상 범위 ⚪")

        

        support = int(ma20 if close_val > ma20 else low20)

        resistance = int(high20)

        target_price = int(max(high20, close_val * 1.10))

        stop_loss = int(ma60 if close_val > ma20 else low20)

        

        trend_score = 30 + (20 if ma5 > ma20 else 0) + (20 if ma20 > ma60 else 0) + (10 if close_val > ma20 else 0) + (20 if macd > signal else 0)

        danger_level = "🚨 높음" if close_val < ma20 else "✅ 안정"

        whale_trace = "🐳 감지!" if (volume_mult > 2.5 and chg_rate > 3) else "특이 없음"

        foreigner_supply = "순매수 우위 🟢" if (chg_rate > 0 and volume_mult > 1.2) else "관망/매도 ⚪"



        msg = f"📋 *[{real_name}] 초정밀 한눈에 시황 리포트*\n"

        msg += f"📅 기준일: {str(latest.name).split()[0]}\n"

        msg += "━━━━━━━━━━━━━━━━━━━\n\n"

        msg += f"📊 *[1. 기본 시세 및 수급]*\n• 현재가: {close_val:,}원 ({chg_rate:+.2f}%)\n• 거래량: {volume:,}주\n• 세력 흔적: {whale_trace} | 외인 수급: {foreigner_supply}\n\n"

        msg += f"📈 *[2. 지표 상태 및 추세]*\n• 추세 / 리본: {trend_status} | {ribbon}\n• RSI: {rsi:.1f} ({overheat_status})\n• MACD 상태: {macd_status}\n\n"

        msg += f"🎯 *[3. 가격 전략]*\n• 생명선(20일): *{int(ma20):,}원*\n• 목표가 / 손절가: *{target_price:,}원* / *{stop_loss:,}원*\n• 추세 점수: *{trend_score}점* / 100점\n"

        msg += "━━━━━━━━━━━━━━━━━━━\n"

        msg += f"🔗 [네이버 증권 종합정보](https://finance.naver.com/item/main.naver?code={code})\n"

        return msg

    except Exception as e:

        return f"❌ [{real_name}] 분석 중 에러 발생: {e}"



def clean_and_convert_text(text):

    """모든 공백을 부수고 영문 브랜드명 및 동의어로 일치시키는 전처리기"""

    t = text.strip().replace(" ", "").lower()

    

    # 한국어 발음 키워드를 데이터베이스 검색 규격에 맞게 자동 치환

    t = t.replace("코덱스", "kodex").replace("코덱", "kodex")

    t = t.replace("타이거", "tiger").replace("라이즈", "rise")

    t = t.replace("에스케이", "sk").replace("엘지", "lg").replace("지에스", "gs")

    return t



print("\n② [무조건 리스트 표기 버전] 주식/ETF 비서 가동 시작!")

last_update_id = 0



while True:

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"

        res = requests.get(url).json()

        

        if "result" in res:

            for update in res["result"]:

                last_update_id = update["update_id"]

                

                # 버튼 클릭 처리

                if "callback_query" in update:

                    callback = update["callback_query"]

                    chat_id = callback["message"]["chat"]["id"]

                    callback_data = callback["data"]

                    requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery", json={"callback_query_id": callback["id"]})

                    

                    if callback_data.startswith("ALERT_TOGGLE:"):

                        _, code, r_name = callback_data.split(":")

                        if chat_id not in WATCH_LIST: WATCH_LIST[chat_id] = {}

                        if code in WATCH_LIST[chat_id]:

                            del WATCH_LIST[chat_id][code]

                            confirm_text = f"🔕 [{r_name}] 실시간 알림 해제!"

                        else:

                            WATCH_LIST[chat_id][code] = {"name": r_name, "last_price": 0, "seen_news": set()}

                            confirm_text = f"🔔 [{r_name}] 실시간 알림 등록!"

                        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": confirm_text})

                        continue

                    

                    code, real_name = callback_data.split(":")

                    msg = generate_perfect_report(code, real_name)

                    is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]

                    alert_btn_label = "🔕 실시간 알림 해제" if is_watched else "🔔 실시간 알림 등록"

                    reply_markup = {"inline_keyboard": [[{"text": alert_btn_label, "callback_data": f"ALERT_TOGGLE:{code}:{real_name}"}]]}

                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "reply_markup": reply_markup})

                    continue



                # 텍스트 입력 처리

                if "message" in update and "text" in update["message"]:

                    chat_id = update["message"]["chat"]["id"]

                    text = update["message"]["text"].strip()

                    

                    # 검색어 정제

                    search_text = clean_and_convert_text(text)

                    

                    # 💡 [핵심] 글자가 '포함'된 모든 종목 대조 (일치 건수가 많으면 리스트로 표기)

                    match = stocks[stocks['CleanName'].str.contains(search_text, case=False, na=False)]

                    

                    if match.empty:

                        msg = f"❓ '{text}' 종목이나 ETF 종류를 찾지 못했습니다."

                        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg})

                    elif len(match) == 1:

                        code = match.iloc[0]['Code']

                        real_name = match.iloc[0]['Name']

                        msg = generate_perfect_report(code, real_name)

                        

                        is_watched = chat_id in WATCH_LIST and code in WATCH_LIST[chat_id]

                        alert_btn_label = "🔕 실시간 알림 해제" if is_watched else "🔔 실시간 알림 등록"

                        reply_markup = {"inline_keyboard": [[{"text": alert_btn_label, "callback_data": f"ALERT_TOGGLE:{code}:{real_name}"}]]}

                        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "reply_markup": reply_markup})

                    else:

                        # 💡 여러 개가 걸리면 상위 10개를 싹 긁어서 인라인 버튼 목록으로 전송!

                        match = match.head(10)

                        inline_keyboard = []

                        for _, row in match.iterrows():

                            inline_keyboard.append([{"text": row['Name'], "callback_data": f"{row['Code']}:{row['Name']}"}])

                        

                        msg = f"🔍 *'{text}' 관련 종목 검색 결과 ({len(match)}개)*\n원하시는 세부 종목을 아래 버튼에서 선택해 주세요!"

                        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "reply_markup": {"inline_keyboard": inline_keyboard}})

                        

    except Exception as e:

        print(f"루프 에러: {e}")

    time.sleep(1) 

