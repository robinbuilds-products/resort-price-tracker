
#!/usr/bin/env python3
"""Daily price check for every available unit at Point Pleasant Resort."""

import csv
import html
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


# The resort's unit codes are not its building numbers.
PREFERRED_UNITS_BY_BUILDING = {
    22: frozenset({"B14", "B15", "B16"}),
    23: frozenset({"B17", "B18", "B19"}),
    24: frozenset({"B20", "B21", "B22"}),
}


def is_preferred_unit(unit, preferred_buildings):
    """Match the complete condo code against the configured buildings."""

    unit_code = str(unit).strip().upper()
    return any(
        unit_code in PREFERRED_UNITS_BY_BUILDING.get(building, ())
        for building in preferred_buildings
    )


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

        if not below_target and not price_dropped:
            continue

        alerts.append(
            {
                "unit_id": row["unit_id"],
                "unit": row["unit"],
                "price": price,
                "old_price": (
                    old[1] if price_dropped else None
                ),
                "begin": window["begin"],
                "end": window["end"],
                "below_target": below_target,
                "preferred": is_preferred_unit(
                    row["unit"],
                    preferred_buildings,
                ),
            }
        )

    return alerts


def send_email(
    to_addr,
    alerts,
    alerts_cfg,
    site,
    location,
):
    """Create and send the Point Pleasant Resort price alert."""

    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    if not (host and user and password):
        print(
            "Email not sent: SMTP settings are not set."
        )

        for alert in alerts:
            preferred = (
                " [PREFERRED]"
                if alert["preferred"]
                else ""
            )

            print(
                f'{alert["unit"]}: '
                f'${alert["price"]:,.2f}'
                f'{preferred}'
            )

        return

    target = float(
        alerts_cfg.get("below_price", 0)
    )

    preferred_buildings = alerts_cfg.get(
        "preferred_buildings",
        []
    )

    preferred_label = ", ".join(
        str(number)
        for number in preferred_buildings
    )

    # Preferred condos first.
    # Within each group, lowest price first.
    sorted_alerts = sorted(
        alerts,
        key=lambda alert: (
            not alert["preferred"],
            alert["price"],
        ),
    )

    lowest = min(
        sorted_alerts,
        key=lambda alert: alert["price"],
    )

    savings = target - lowest["price"]

    subject = alerts_cfg.get(
        "email_subject",
        "Point Pleasant Resort: "
        "Preferred condos under $1,500",
    )

    # ---------------------------
    # Plain-text email
    # ---------------------------

    plain_lines = [
        f"{location} condo price alert",
        "",
        (
            f"We found {len(sorted_alerts)} condos "
            f"under your ${target:,.0f} target."
        ),
        "",
        (
            f'Lowest price: '
            f'${lowest["price"]:,.2f} '
            f'({lowest["unit"]})'
        ),
        (
            f'${savings:,.2f} below your target.'
        ),
        "",
        (
            "Preferred buildings: "
            f"{preferred_label}"
        ),
        "",
    ]

    for alert in sorted_alerts:
        preferred = (
            "PREFERRED - "
            if alert["preferred"]
            else ""
        )

        line = (
            f'{preferred}'
            f'{alert["unit"]}: '
            f'${alert["price"]:,.2f}'
        )

        if alert["old_price"] is not None:
            line += (
                " - down from "
                f'${alert["old_price"]:,.2f}'
            )

        plain_lines.append(line)

    plain_lines.extend(
        [
            "",
            f"Check availability: {site}",
            "",
            (
                "Prices and availability can change "
                "throughout the day."
            ),
            (
                "To stop these alerts, reply to this "
                "email and Robin will turn them off."
            ),
        ]
    )

    # ---------------------------
    # HTML condo rows
    # ---------------------------

    html_rows = []

    for alert in sorted_alerts:

        if alert["preferred"]:
            row_style = (
                "background:#E8F5E9;"
                "color:#176B2C;"
                "font-weight:700;"
            )

            badge = (
                '<span style="'
                'display:inline-block;'
                'background:#176B2C;'
                'color:#FFFFFF;'
                'font-size:11px;'
                'font-weight:700;'
                'padding:3px 7px;'
                'border-radius:10px;'
                'margin-left:7px;'
                '">'
                "PREFERRED"
                "</span>"
            )

        else:
            row_style = (
                "background:#FFFFFF;"
                "color:#222222;"
            )

            badge = ""

        price_change = ""

        if alert["old_price"] is not None:
            price_change = (
                '<div style="'
                'font-size:12px;'
                'color:#666666;'
                'margin-top:3px;'
                '">'
                "Down from "
                f'${alert["old_price"]:,.2f}'
                "</div>"
            )

        html_rows.append(
            f'<tr style="{row_style}">'
            '<td style="'
            'padding:12px;'
            'border-bottom:1px solid #E5E5E5;'
            '">'
            f'{html.escape(alert["unit"])}'
            f'{badge}'
            f'{price_change}'
            "</td>"
            '<td style="'
            'padding:12px;'
            'border-bottom:1px solid #E5E5E5;'
            'text-align:right;'
            'white-space:nowrap;'
            '">'
            f'${alert["price"]:,.2f}'
            "</td>"
            "</tr>"
        )

    date_range = (
        f'{html.escape(lowest["begin"])}'
        " to "
        f'{html.escape(lowest["end"])}'
    )

    # ---------------------------
    # HTML email
    # ---------------------------

    html_body = f"""\
<!doctype html>
<html lang="en">
<body style="
    margin:0;
    padding:0;
    background:#F4F5F7;
    font-family:Arial,Helvetica,sans-serif;
    color:#222222;
">
<div style="
    max-width:640px;
    margin:0 auto;
    padding:24px 16px;
">

<div style="
    background:#FFFFFF;
    border-radius:12px;
    padding:28px;
">

<div style="
    color:#666666;
    font-size:13px;
    font-weight:700;
    margin-bottom:8px;
">
CONDO PRICE ALERT
</div>

<h1 style="
    font-size:26px;
    line-height:1.25;
    margin:0 0 6px;
">
{html.escape(location)}
</h1>

<p style="
    margin:0 0 24px;
    color:#666666;
">
{date_range}
</p>

<div style="
    background:#EEF6FF;
    border-radius:10px;
    padding:20px;
    margin-bottom:20px;
">

<div style="
    color:#555555;
    font-size:13px;
">
LOWEST PRICE
</div>

<div style="
    font-size:32px;
    font-weight:700;
    margin:4px 0;
">
${lowest["price"]:,.2f}
</div>

<div style="
    color:#176B2C;
    font-weight:700;
">
${savings:,.2f} below your ${target:,.0f} target
</div>

</div>

<div style="
    background:#E8F5E9;
    border-left:4px solid #176B2C;
    padding:12px 14px;
    margin-bottom:20px;
">

<strong>
Preferred buildings: {html.escape(preferred_label)}
</strong>

<br>

<span style="
    color:#355C3B;
    font-size:13px;
">
Preferred condos are highlighted in green.
</span>

</div>

<table
    role="presentation"
    style="
        width:100%;
        border-collapse:collapse;
        margin-bottom:24px;
    "
>

<tr style="background:#F1F3F5;">

<th style="
    padding:10px 12px;
    text-align:left;
    font-size:13px;
    color:#555555;
">
Condo
</th>

<th style="
    padding:10px 12px;
    text-align:right;
    font-size:13px;
    color:#555555;
">
Price
</th>

</tr>

{''.join(html_rows)}

</table>

<div style="
    text-align:center;
    margin:24px 0;
">

<a
    href="{html.escape(site, quote=True)}"
    style="
        display:inline-block;
        background:#1769AA;
        color:#FFFFFF;
        text-decoration:none;
        font-weight:700;
        padding:13px 20px;
        border-radius:7px;
    "
>
Check current availability
</a>

</div>

<p style="
    color:#666666;
    font-size:13px;
    line-height:1.5;
">
Prices and availability can change throughout the day.
Check the current price before booking.
</p>

<p style="
    color:#666666;
    font-size:13px;
    line-height:1.5;
    margin-bottom:0;
">
To stop these alerts, reply to this email and Robin
will turn them off.
</p>

</div>
</div>
</body>
</html>
"""

    # ---------------------------
    # Send email
    # ---------------------------

    msg = EmailMessage()

    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    msg.set_content(
        "\n".join(plain_lines)
    )

    msg.add_alternative(
        html_body,
        subtype="html",
    )

    with smtplib.SMTP_SSL(
        host,
        int(
            os.environ.get("SMTP_PORT")
            or "465"
        ),
    ) as server:
        server.login(
            user,
            password,
        )

        server.send_message(msg)

    print("Alert email sent.")


def main():
    cfg = load_config()

    history_path = os.path.join(
        HERE,
        cfg["history_file"],
    )

    history = read_history(
        history_path
    )

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    new_rows = []
    all_alerts = []

    for window in cfg["stay_windows"]:

        data = fetch_prices(
            cfg["site"],
            window,
        )

        previous = previous_snapshot(
            history,
            window,
        )

        rows = build_rows(
            now,
            window,
            data,
            previous,
        )

        if not any(
            r["available"] == "yes"
            for r in rows
        ):
            print(
                "No units listed for "
                f"{window['begin']} "
                f"to {window['end']}."
            )

        all_alerts += find_alerts(
            rows,
            previous,
            cfg["alerts"],
            window,
        )

        new_rows += rows

    write_header = not os.path.exists(
        history_path
    )

    with open(
        history_path,
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        if write_header:
            writer.writeheader()

        writer.writerows(new_rows)

    print(
        f"Saved {len(new_rows)} rows "
        f"to {cfg['history_file']}"
    )

    if all_alerts:

        to_addr = os.environ.get("ALERT_EMAIL_TO", "").strip()

        if to_addr:
            send_email(
                to_addr,
                all_alerts,
                cfg["alerts"],
                cfg["site"],
                cfg.get(
                    "location",
                    "Point Pleasant Resort",
                ),
            )

        else:
            print(
                "Alerts found, but no "
                "email address is set."
            )


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
