#!/usr/bin/env python3
"""Daily price check for every available unit at Point Pleasant Resort."""

import csv
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage


HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    "checked_at",
    "stay_begin",
    "stay_end",
    "adults",
    "children",
    "unit_id",
    "unit",
    "available",
    "price",
    "currency",
]


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

    url = (
        site.rstrip("/")
        + "/rcapi/item/avail/search?"
        + urllib.parse.urlencode(params)
    )

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "price-tracker/1.0 (personal use)"
        },
    )

    last_error = None

    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(5)

    raise RuntimeError(
        f"Could not read the price feed: {last_error}"
    )


def read_history(path):
    if not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def previous_snapshot(history, window):
    """Return the most recent earlier check for this stay window."""

    rows = [
        r
        for r in history
        if r["stay_begin"] == window["begin"]
        and r["stay_end"] == window["end"]
        and str(r["adults"]) == str(window["adults"])
        and str(r["children"]) == str(window["children"])
    ]

    if not rows:
        return {}

    latest = max(r["checked_at"] for r in rows)

    return {
        r["unit_id"]: (r["unit"], float(r["price"]))
        for r in rows
        if r["checked_at"] == latest
        and r["available"] == "yes"
        and r["price"]
    }


def build_rows(now, window, data, previous):
    rows = []
    seen = set()

    for item in data:
        for p in item.get("prices", []):
            unit_id = str(item.get("eid"))
            seen.add(unit_id)

            rows.append(
                {
                    "checked_at": now,
                    "stay_begin": window["begin"],
                    "stay_end": window["end"],
                    "adults": window["adults"],
                    "children": window["children"],
                    "unit_id": unit_id,
                    "unit": item.get("name", ""),
                    "available": "yes",
                    "price": p.get("p", ""),
                    "currency": p.get("c", "USD"),
                }
            )

            # One price per unit for a stay window.
            break

    # Record units that were previously available but are gone now.
    for unit_id, (name, _price) in previous.items():
        if unit_id not in seen:
            rows.append(
                {
                    "checked_at": now,
                    "stay_begin": window["begin"],
                    "stay_end": window["end"],
                    "adults": window["adults"],
                    "children": window["children"],
                    "unit_id": unit_id,
                    "unit": name,
                    "available": "no",
                    "price": "",
                    "currency": "",
                }
            )

    return rows


def get_building_number(unit):
    """Get the number portion of a unit name, such as 22 from A22."""

    match = re.search(r"\d+", str(unit))

    if not match:
        return None

    return int(match.group())


def is_preferred_unit(unit, preferred_buildings):
    """Check whether the condo is in a preferred building."""

    building = get_building_number(unit)
    return building in preferred_buildings


def find_alerts(rows, previous, alerts_cfg, window):
    """Find condos that meet the user's alert criteria."""

    alerts = []

    below = alerts_cfg.get("below_price")
    on_drop = alerts_cfg.get(
        "alert_on_drop_since_last_check"
    )

    preferred_buildings = set(
        alerts_cfg.get("preferred_buildings", [])
    )

    for row in rows:
        if row["available"] != "yes":
            continue

        if not row["price"]:
            continue

        price = float(row["price"])

        old = previous.get(row["unit_id"])

        below_target = (
            below is not None
            and price < float(below)
        )

        price_dropped = bool(
            on_drop
            and old
            and price < old[1]
        )

        if not below_target and not price_
