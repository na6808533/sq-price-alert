"""
Singapore Airlines PUS-AKL price tracker
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
CARRIER = "SQ"  # Singapore Airlines
CURRENCY = "KRW"

HISTORY_FILE = "price_history.json"

AMADEUS_BASE = "https://api.amadeus.com"  # production. test env: https://test.api.amadeus.com


def get_amadeus_token():
    resp = requests.post(
        f"{AMADEUS_BASE}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AMADEUS_CLIENT_ID"],
            "client_secret": os.environ["AMADEUS_CLIENT_SECRET"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_flights(token):
    params = {
        "originLocationCode": ORIGIN,
        "destinationLocationCode": DESTINATION,
        "departureDate": DEPART_DATE,
        "returnDate": RETURN_DATE,
        "adults": ADULTS,
        "children": CHILDREN,
        "currencyCode": CURRENCY,
        "includedAirlineCodes": CARRIER,
        "max": 20,
    }
    resp = requests.get(
        f"{AMADEUS_BASE}/v2/shopping/flight-offers",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def summarize_offer(offer):
    total = float(offer["price"]["grandTotal"])
    itineraries = []
    for itin in offer["itineraries"]:
        segs = itin["segments"]
        dep = segs[0]["departure"]
        arr = segs[-1]["arrival"]
        stops = len(segs) - 1
        itineraries.append(
            f"{dep['iataCode']} {dep['at'][5:16].replace('T', ' ')} -> "
            f"{arr['iataCode']} {arr['at'][5:16].replace('T', ' ')} "
            f"(경유 {stops}회, {itin['duration'].replace('PT', '').lower()})"
        )
    return total, itineraries


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

    token = get_amadeus_token()
    offers = search_flights(token)

    if not offers:
        send_email(
            f"[SQ PUS-AKL] {now:%m/%d} 조회 결과 없음",
            "오늘은 해당 조건(SQ, 12/25 출발, 1/5 귀국)의 운임이 조회되지 않았습니다.",
        )
        return

    # Cheapest offer
    offers.sort(key=lambda o: float(o["price"]["grandTotal"]))
    total, itineraries = summarize_offer(offers[0])

    history = load_history()
    prev = history[-1]["price"] if history else None
    history.append({"date": now.strftime("%Y-%m-%d"), "price": total})
    save_history(history)

    if prev:
        diff = total - prev
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "―")
        change_line = f"전일 대비: {arrow} {abs(diff):,.0f}원 (어제 {prev:,.0f}원)"
    else:
        change_line = "첫 조회입니다."

    min_rec = min(history, key=lambda h: h["price"])

    body = (
        f"싱가포르항공 부산-오클랜드 왕복 (성인 3, 아동 1)\n"
        f"출발 {DEPART_DATE} / 귀국 {RETURN_DATE}\n\n"
        f"오늘 최저가: {total:,.0f}원\n"
        f"{change_line}\n"
        f"추적 기간 최저: {min_rec['price']:,.0f}원 ({min_rec['date']})\n\n"
        f"[여정]\n" + "\n".join(itineraries) + "\n\n"
        f"* Amadeus GDS 기준 가격으로, 싱가포르항공 홈페이지 가격과 다를 수 있습니다.\n"
        f"* 조회 시각: {now:%Y-%m-%d %H:%M} KST"
    )
    subject = f"[SQ PUS-AKL] {now:%m/%d} 최저가 {total:,.0f}원 " + (
        "▼하락" if prev and total < prev else ("▲상승" if prev and total > prev else "")
    )
    send_email(subject.strip(), body)
    print(f"Sent. Price: {total:,.0f} KRW")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
