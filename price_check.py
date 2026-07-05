"""
PUS-AKL price tracker v5 (SerpApi Google Flights)
- Outbound: 2026-12-24 AND 2026-12-25 / Return: 2027-01-05
- Pax: 3 adults + 1 child
- Airlines tracked: Singapore Airlines (SQ), China Airlines (CI)
- The day's cheapest combo is drilled down to seller-level deal prices
  (Expedia / Gotogate / Trip.com etc.)
- Daily email via Gmail; auto-stops after 2026-07-31 (KST)
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
DEPART_DATES = ["2026-12-24", "2026-12-25"]   # 출발일 후보 (원하면 추가/삭제)
RETURN_DATE = "2027-01-05"
ADULTS = 3
CHILDREN = 1
AIRLINES = {"SQ": "싱가포르항공", "CI": "중화항공"}  # 항공편명 코드로 매칭

HISTORY_FILE = "price_history.json"


def base_params(depart_date):
    return {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": depart_date,
        "return_date": RETURN_DATE,
        "adults": ADULTS,
        "children": CHILDREN,
        "currency": "KRW",
        "hl": "ko",
        "gl": "kr",
        "type": "1",  # round trip
        "deep_search": "true",
        "api_key": os.environ["SERPAPI_KEY"],
    }


def serpapi_get(params):
    resp = requests.get("https://serpapi.com/search.json", params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


def search_outbound(depart_date):
    data = serpapi_get(base_params(depart_date))
    return data.get("best_flights", []) + data.get("other_flights", [])


def airline_code_of(option):
    """Return airline code (e.g. 'SQ') if ALL segments share it, else None."""
    segments = option.get("flights", [])
    if not segments:
        return None
    codes = set()
    for seg in segments:
        fn = seg.get("flight_number", "").strip()  # e.g. "SQ 607"
        codes.add(fn.split(" ")[0] if fn else "?")
    return codes.pop() if len(codes) == 1 else None


def summarize_option(option):
    lines = []
    for seg in option.get("flights", []):
        dep = seg.get("departure_airport", {})
        arr = seg.get("arrival_airport", {})
        lines.append(
            f"  {dep.get('id', '?')} {dep.get('time', '')} -> "
            f"{arr.get('id', '?')} {arr.get('time', '')} "
            f"({seg.get('airline', '')} {seg.get('flight_number', '')})"
        )
    return lines


def get_booking_deals(depart_date, outbound_option):
    """Drill down: pick cheapest matching return flight, then fetch seller prices.
    Costs 2 extra API calls. Returns (return_option, deals list) or (None, [])."""
    dep_token = outbound_option.get("departure_token")
    if not dep_token:
        return None, []

    # step 1: return flights for this outbound
    p = base_params(depart_date)
    p["departure_token"] = dep_token
    data = serpapi_get(p)
    returns = data.get("best_flights", []) + data.get("other_flights", [])
    returns = [r for r in returns if r.get("price") and r.get("booking_token")]
    if not returns:
        return None, []
    returns.sort(key=lambda r: r["price"])
    ret = returns[0]

    # step 2: booking options (seller deals)
    p = base_params(depart_date)
    p["booking_token"] = ret["booking_token"]
    data = serpapi_get(p)
    deals = []
    for bo in data.get("booking_options", []):
        block = bo.get("together") or bo
        seller = block.get("book_with")
        price = block.get("price")
        if seller and price:
            deals.append((price, seller))
    deals.sort()
    return ret, deals


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

    # today: {"12/24 SQ": {"airline", "price", "lines", "date", "option"}, ...}
    today = {}
    for dep_date in DEPART_DATES:
        options = search_outbound(dep_date)
        short_date = dep_date[5:].replace("-", "/")
        for code, name in AIRLINES.items():
            matched = [o for o in options if airline_code_of(o) == code and o.get("price")]
            if matched:
                matched.sort(key=lambda o: o["price"])
                best = matched[0]
                today[f"{short_date} {code}"] = {
                    "airline": name,
                    "price": best["price"],
                    "lines": summarize_option(best),
                    "date": dep_date,
                    "option": best,
                }

    if not today:
        send_email(
            f"[PUS-AKL] {now:%m/%d} 조회 결과 없음",
            "오늘은 SQ/CI 단독 여정 운임이 조회되지 않았습니다.",
        )
        return

    # drill into the day's cheapest combo for seller-level deal prices
    best_key, best_info = min(today.items(), key=lambda kv: kv[1]["price"])
    deal_section = ""
    deal_price = None
    try:
        ret, deals = get_booking_deals(best_info["date"], best_info["option"])
        if deals:
            deal_price, deal_seller = deals[0]
            top = "\n".join(f"  {seller}: {price:,}원" for price, seller in deals[:5])
            ret_lines = "\n".join(summarize_option(ret)) if ret else ""
            deal_section = (
                f"\n\n▶ 특가 확인 ({best_key} {best_info['airline']} 기준)\n"
                f"  가장 저렴한 판매처: {deal_seller} {deal_price:,}원\n"
                f"{top}\n"
                f"  [귀국편]\n{ret_lines}"
            )
    except Exception as e:
        deal_section = f"\n\n▶ 특가 조회 실패: {e}"

    history = load_history()
    prev_entry = history[-1] if history else None
    prev_prices = prev_entry.get("prices", {}) if prev_entry else {}

    record = {
        "date": now.strftime("%Y-%m-%d"),
        "prices": {k: v["price"] for k, v in today.items()},
    }
    if deal_price:
        record["best_deal"] = {"key": best_key, "price": deal_price}
    history.append(record)
    save_history(history)

    def period_min(key):
        vals = [
            (h["prices"][key], h["date"])
            for h in history
            if isinstance(h.get("prices"), dict) and key in h["prices"]
        ]
        return min(vals) if vals else None

    sections = []
    for key in sorted(today.keys()):
        info = today[key]
        price = info["price"]
        prev = prev_prices.get(key)
        if prev:
            diff = price - prev
            arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "―")
            change = f"전일 대비 {arrow} {abs(diff):,}원"
        else:
            change = "첫 조회"
        pm = period_min(key)
        min_line = f"기간 최저 {pm[0]:,}원 ({pm[1]})" if pm else ""
        sections.append(
            f"■ {key} 출발 · {info['airline']}\n"
            f"  최저가: {price:,}원  ({change}, {min_line})\n"
            + "\n".join(info["lines"])
        )

    headline_price = deal_price if deal_price else best_info["price"]
    body = (
        f"부산-오클랜드 왕복 (성인 3, 아동 1) / 귀국 {RETURN_DATE}\n"
        f"오늘의 최저 조합: {best_key} {best_info['airline']} {best_info['price']:,}원"
        + (f" (특가 {deal_price:,}원)" if deal_price else "")
        + "\n\n"
        + "\n\n".join(sections)
        + deal_section
        + f"\n\n* Google Flights 기준 가격입니다.\n* 조회 시각: {now:%Y-%m-%d %H:%M} KST"
    )
    subject = f"[PUS-AKL] {now:%m/%d} 최저 {headline_price:,}원 ({best_key} {best_info['airline']})"
    send_email(subject, body)
    print(f"Sent. Best: {best_key} {headline_price:,} KRW")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
