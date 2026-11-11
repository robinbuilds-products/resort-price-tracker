#!/usr/bin/env python3
"""Daily price check for every available unit at a resort.

Reads settings from config.json, asks the resort's availability feed for each
stay window, appends one row per unit to a history CSV, and (optionally) emails
an alert when prices drop. Uses only Python's standard library.
"""
import csv
import json
import os
import smtplib
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["checked_at", "stay_begin", "stay_end", "adults", "children",
          "unit_id", "unit", "available", "price", "currency"]


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def fetch_prices(site, window):
    params = {
        "rcav[begin]": window["begin"],
        "rcav[end]": window["end"],
        "rcav[adult]": str(window["adults"]),
        "rcav[child]": str(window["children"]),
        "rcav[coupon]": "",
    }
    url = site.rstrip("/") + "/rcapi/item/avail/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "price-tracker/1.0 (personal use)"})
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network hiccup or bad response
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"Could not read the price feed: {last_error}")


def read_history(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def previous_snapshot(history, window):
    """Most recent earlier check for this window: {unit_id: (unit, price)}."""
    rows = [r for r in history
            if r["stay_begin"] == window["begin"] and r["stay_end"] == window["end"]
            and str(r["adults"]) == str(window["adults"])
            and str(r["children"]) == str(window["children"])]
    if not rows:
        return {}
    latest = max(r["checked_at"] for r in rows)
    return {r["unit_id"]: (r["unit"], float(r["price"]))
            for r in rows if r["checked_at"] == latest and r["available"] == "yes" and r["price"]}


def build_rows(now, window, data, previous):
    rows, seen = [], set()
    for item in data:
        for p in item.get("prices", []):
            unit_id = str(item.get("eid"))
            seen.add(unit_id)
            rows.append({
                "checked_at": now, "stay_begin": window["begin"], "stay_end": window["end"],
                "adults": window["adults"], "children": window["children"],
                "unit_id": unit_id, "unit": item.get("name", ""), "available": "yes",
                "price": p.get("p", ""), "currency": p.get("c", "USD"),
            })
            break  # one price per unit for a stay window
    # Units that were available last time but are gone now (likely booked)
    for unit_id, (name, _price) in previous.items():
        if unit_id not in seen:
            rows.append({
                "checked_at": now, "stay_begin": window["begin"], "stay_end": window["end"],
                "adults": window["adults"], "children": window["children"],
                "unit_id": unit_id, "unit": name, "available": "no",
                "price": "", "currency": "",
            })
    return rows


def find_alerts(rows, previous, alerts_cfg, window):
    messages = []
    below = alerts_cfg.get("below_price")
    on_drop = alerts_cfg.get("alert_on_drop_since_last_check")
    for r in rows:
        if r["available"] != "yes":
            continue
        price = float(r["price"])
        label = f'{r["unit"]} ({window["begin"]} to {window["end"]})'
        if below is not None and price < float(below):
            messages.append(f"{label}: ${price:,.2f} is below your ${float(below):,.2f} limit")
        old = previous.get(r["unit_id"])
        if on_drop and old and price < old[1]:
            messages.append(f"{label}: dropped from ${old[1]:,.2f} to ${price:,.2f}")
    return messages


def send_email(to_addr, lines):
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and user and password):
        print("Email not sent: SMTP settings are not set. Alert text:")
        print("\n".join(lines))
        return
    msg = EmailMessage()
    msg["Subject"] = f"Resort price alert: {len(lines)} update(s)"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content("\n".join(lines))
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT") or "465")) as server:
        server.login(user, password)
        server.send_message(msg)
    print(f"Alert email sent to {to_addr}")


def main():
    cfg = load_config()
    history_path = os.path.join(HERE, cfg["history_file"])
    history = read_history(history_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_rows, all_alerts = [], []

    for window in cfg["stay_windows"]:
        data = fetch_prices(cfg["site"], window)
        previous = previous_snapshot(history, window)
        rows = build_rows(now, window, data, previous)
        if not any(r["available"] == "yes" for r in rows):
            print(f"No units listed for {window['begin']} to {window['end']}; check the feed if this is unexpected.")
        all_alerts += find_alerts(rows, previous, cfg["alerts"], window)
        new_rows += rows

    write_header = not os.path.exists(history_path)
    with open(history_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    print(f"Saved {len(new_rows)} rows to {cfg['history_file']}")

    if all_alerts:
        to_addr = cfg["alerts"].get("email_to")
        if to_addr:
            send_email(to_addr, all_alerts)
        else:
            print("Alerts found, but no email address is set yet:")
            print("\n".join(all_alerts))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
