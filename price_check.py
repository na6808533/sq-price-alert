"""
Singapore Airlines PUS-AKL price tracker (SerpApi Google Flights version)
- Route: PUS -> AKL (2026-12-25), AKL -> PUS (2027-01-05)
- Pax: 3 adults + 1 child
- Runs daily via GitHub Actions, emails price via Gmail
- Auto-stops after 2026-07-31 (KST)
"""

import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))
END_DATE = datetime(2026, 7, 31, 23, 59, tzinfo=KST)

ORIGIN = "PUS"
DESTINATION = "AKL"
DEPART_DATE = "2026-12-25"
RETURN_DATE = "2027-01-05"
ADULTS = 3
CHILDREN = 1
AIRLINE_NAME = "Singapore"  # match "Singapore Airlines"

HISTORY_FILE = "price_history.json"


def search_google_flights():
    params = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": DEPART_DATE,
        "return_date": RETURN_DATE,
        "adults": ADULTS,
        "children": CHILDREN,
        "currency": "KRW",
        "hl": "ko",
        "type": "1",  # round trip
        "api_key": os.environ["SERPAPI_KEY"],
    }
    resp = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    options = data.get("best_flights", []) + data.get("other_flights", [])
    return options


def is_singapore_airlines(option):
    segments = option.get("flights", [])
    if not segments:
        return False
    return all(AIRLINE_NAME.lower() in seg.get("airline", "").lower() for seg in segments)


def summarize_option(option):
    price = option.get("price")
    lines = []
    for seg in option.get("flights", []):
        dep = seg.get("departure_airport", {})
        arr = seg.get("arrival_airport", {})
        lines.append(
            f"{dep.get('id', '?')} {dep.get('time', '')} -> "
            f"{arr.get('id', '?')} {arr.get('time', '')} "
            f"({seg.get('airline', '')} {seg.get('flight_number', '')})"
        )
    return price, lines


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def send_email(subject, body):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [r.strip() for r in os.environ["RECIPIENT_EMAIL"].split(",") if r.strip()]

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, recipients, msg.as_string())


def main():
    now = datetime.now(KST)
    if now > END_DATE:
        print("Tracking period ended (2026-07-31). Skipping.")
        return

    options = search_google_flights()
    sq_options = [o for o in options if is_singapore_airlines(o) and o.get("price")]

    if not sq_options:
        # fall back: cheapest overall so the email is still useful
        priced = [o for o in options if o.get("price")]
        if not priced:
            send_email(
                f"[SQ PUS-AKL] {now:%m/%d} 조회 결과 없음",
                "오늘은 해당 날짜의 운임이 조회되지 않았습니다.",
            )
            return
        priced.sort(key=lambda o: o["price"])
        price, lines = summarize_option(priced[0])
        note = "(싱가포르항공 단독 여정이 없어 전체 최저가 기준)"
    else:
        sq_options.sort(key=lambda o: o["price"])
        price, lines = summarize_option(sq_options[0])
        note = ""

    history = load_history()
    prev = history[-1]["price"] if history else None
    history.append({"date": now.strftime("%Y-%m-%d"), "price": price})
    save_history(history)

    if prev:
        diff = price - prev
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "―")
        change_line = f"전일 대비: {arrow} {abs(diff):,}원 (어제 {prev:,}원)"
    else:
        change_line = "첫 조회입니다."

    min_rec = min(history, key=lambda h: h["price"])

    body = (
        f"싱가포르항공 부산-오클랜드 왕복 (성인 3, 아동 1) {note}\n"
        f"출발 {DEPART_DATE} / 귀국 {RETURN_DATE}\n\n"
        f"오늘 최저가: {price:,}원\n"
        f"{change_line}\n"
        f"추적 기간 최저: {min_rec['price']:,}원 ({min_rec['date']})\n\n"
        f"[여정]\n" + "\n".join(lines) + "\n\n"
        f"* Google Flights 기준 가격입니다.\n"
        f"* 조회 시각: {now:%Y-%m-%d %H:%M} KST"
    )
    subject = f"[SQ PUS-AKL] {now:%m/%d} 최저가 {price:,}원 " + (
        "▼하락" if prev and price < prev else ("▲상승" if prev and price > prev else "")
    )
    send_email(subject.strip(), body)
    print(f"Sent. Price: {price:,} KRW")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
