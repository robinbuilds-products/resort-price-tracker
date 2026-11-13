# Resort Price Tracker

A bespoke price-monitoring tool I built for a client who wanted to book a specific lakeside resort at the right price. It checks every available unit once a day, keeps a running history of prices, and emails an alert when a price drops.

## The problem

My client was planning a week-long stay and faced two options: check the resort's website by hand every day, or pay a travel agent to watch prices for them. Neither was a good use of their time or money.

## Discovery and the blocker

Every AI tool I tried said this couldn't be done. Prices only appear after you fill out the resort's booking form, and the tools couldn't get past that step.

Rather than accept that, I worked with GitHub Copilot to dig into the website's source. We found where the site exposes its pricing data behind the form, which let the tracker read prices directly and reliably.

## What I delivered

- **A daily source of truth:** every unit's price for the client's stay dates is checked automatically each morning.
- **A price history:** each check is saved, building a baseline of what "normal" pricing looks like for that resort.
- **Email alerts:** the client is notified when any unit drops in price or falls below their target.
- **Full handoff:** I proved it worked, then handed it over for the client to run on their own.

The result: no more daily manual checks, and no need to hire a travel agent.

## My role

I worked on this as a **forward deployed product manager**: I sat with the client's real problem, scoped it to what they needed, pushed through a technical blocker, shipped a working product, and handed it off.

## How it works

- `check_prices.py` reads the resort's availability feed for each stay window, compares it to the last check, and saves the results to `price_history.csv`.
- A GitHub Actions workflow (`.github/workflows/daily-price-check.yml`) runs the check every day at 13:00 UTC and saves the updated history back to the repo.
- Alerts are sent by email when a price drops since the last check or falls below the set limit.

It uses only Python's standard library. Nothing needs to be installed.

## Setup

**1. Set your stay and alert preferences in `config.json`:**

| Setting | What it does |
|---|---|
| `stay_windows` | The dates and number of guests to check |
| `below_price` | Alert when a unit's total stay price falls below this amount |
| `alert_on_drop_since_last_check` | Alert whenever a price drops from the previous check |
| `email_to` | Leave as `null` and use the `ALERT_EMAIL_TO` secret instead, to keep your address private |

**2. Add these repository secrets** under Settings → Secrets and variables → Actions:

| Secret | What it is |
|---|---|
| `SMTP_HOST` | Your email provider's SMTP server |
| `SMTP_PORT` | Usually `465` |
| `SMTP_USER` | The email account that sends alerts |
| `SMTP_PASSWORD` | That account's app password |
| `ALERT_EMAIL_TO` | Where alerts should be sent |

**3. Run it** from the Actions tab with **Run workflow**, or let it run on its daily schedule.

## What's next

Once enough price history builds up, I plan to explore AI-based price prediction, so the tracker can say not just "the price dropped" but "this is a good time to book."

## Built with

Python · GitHub Actions · GitHub Copilot
