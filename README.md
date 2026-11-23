# Resort Price Tracker

A bespoke price-monitoring tool I built for a client who wanted to book a specific lakeside resort at the right price. It checks every available unit once a day, keeps a running history of prices, and emails an alert when a price drops. I built it as a forward-deployed product project, from a client's real need through a technical blocker to a working, handed-off product.

## Client goal

My client was planning a week-long stay and faced two options: check the resort's website by hand every day, or pay a travel agent to watch prices for them. Neither was a good use of their time or money.

Checking by hand meant filling out the resort's booking form for the stay dates every day, then scanning the price of every available condo (40 on a recent check) to spot any change. The implementation was meant to take that daily work off their plate entirely: one automated check of every unit, a running price history, and an email when a price drops or falls below their target.

## Discovery

What I did:

- Sat with the client's real problem and scoped it to what they needed: their stay dates, number of guests, preferred buildings, and what should trigger an alert.
- Tested whether existing AI tools could do the job. Every AI tool I tried said it couldn't be done: prices only appear after you fill out the resort's booking form, and the tools couldn't get past that step.

## Solutioning

Rather than accept that answer, I worked with GitHub Copilot to dig into the website's source. We found where the site exposes its pricing data behind the form, which let the tracker read prices directly and reliably.

What I did:

- Built the tracker to read the resort's availability feed directly, instead of trying to fill out the form.
- Used only Python's standard library, so nothing needs to be installed and there is less to maintain.
- Chose GitHub Actions to run the check once a day, with no server to maintain.
- Designed an alert email that:
  - Leads with the lowest price and how far it is below the client's target.
  - Highlights the client's preferred buildings in green, so their first-choice condos stand out.
  - Lists every condo with its price and what it was down from.
  - Links straight to current availability, with a reminder to check the price before booking.
  - Tells the client how to stop the alerts.

## Configuration and testing

What I did:

- Put everything the client might change in `config.json`: stay windows, guests, the target price and drop alerts. No code changes are needed for these.
- Set the alert level: an email goes out when any unit's price drops since the last check, or when a unit falls below the $1,500 total-stay target.
- Checked that everything private stays private: the email password, sending account and alert email address are stored as encrypted GitHub secrets and never appear in the code, data files or public repository. `email_to` stays `null` in the config for the same reason.
- Proved it worked by running it against the live site and checking the results before handing it over.

## Go-live

What I did:

- Turned on the daily schedule: the tracker checks every unit at 13:00 UTC (7:00 AM Central) and saves the updated history back to the repo.
- Tested alerts on my own inbox first, then switched them to the client.
- Handed the tracker over for the client to run on their own. With the client's approval, the repository was then made public.
- Next step: we are now building up the historical prices so AI price prediction can be layered on top.

### What the alert email looks like

<img width="1167" height="1208" alt="resort-alert-email" src="https://github.com/user-attachments/assets/a7f6423e-c7b2-485c-af46-6067b810a865" />


*Sample alert from November 22, 2026, showing the first condos in the list. The full email lists all 40 available condos. Email addresses are hidden.*

## Outcome

**Baseline (before):** The client had two options: fill out the booking form and scan dozens of condo prices by hand every day, or pay a travel agent to watch prices. Every AI tool tried said automated tracking couldn't be done. There was no price history to show what "normal" pricing looked like.

**Result (after):** Every available unit is checked automatically each morning, with no hand-checking and no travel agent. Every price is saved, building a baseline of normal pricing for the resort. The client gets one email with the lowest price, how it compares with their target, and their preferred condos highlighted.

**How it was measured:**

- GitHub Actions run history: one completed check per day.
- `price_history.csv`: every unit's price, saved at every check.
- The daily alert email itself. For example, the November 22, 2026 alert found the lowest price at $1,096, which is $404 below the client's $1,500 target, and showed 32 of 40 condos down in price since the previous check.

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

## Pricing history and the road to prediction

The tracker records every unit's price at every check. This shows what has already happened. It does not forecast what will happen.

We are now building up the price history so AI price prediction can be layered on top. Once enough history is in, the tracker can say not just "the price dropped" but "this is a good time to book."

## My role

I worked on this as a **forward deployed product manager**: I sat with the client's real problem, scoped it to what they needed, worked through a technical blocker every AI tool said couldn't be solved, shipped a working product, and handed it off.

## Built with

Python · GitHub Actions · GitHub Copilot
