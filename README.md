# Poker Portal

A small Flask app I put together for tracking our low-stakes hold'em nights without having to keep a spreadsheet open all the time.

The idea is pretty simple: public pages for stats and session history, plus a small admin area for recording buy-ins, cash-outs, paid amounts, and notes. The data sits in a CSV audit log, so everything is append-only and easy to follow later.

## What it does

- all-time leaderboard
- per-session pages
- per-player stat pages
- admin login for recording events
- open / closed session tracking
- payout tracking with `paid` events
- session and player charts
- CSV import / export from the admin page
- append-only `entries.csv` ledger instead of overwriting old rows

## Stack

Built with a pretty lightweight setup:

- Python
- Flask
- Jinja templates
- Chart.js
- plain CSS
- CSV event log for storage

## Ledger model

The app treats `data/entries.csv` as the source of truth.

Each row is an event, not a final snapshot. Instead of editing an old row, I append another one. That keeps rebuys, corrections, payouts, and session state changes visible in the log instead of hiding them behind edits.

Current event types:

- `buyin`
- `cashout`
- `paid`
- `note`
- `session_open`
- `session_close`

A few examples:

- another `buyin` for a rebuy
- another `cashout` if chip counts are corrected later
- a `paid` event when someone is actually settled up
- a `note` event for bookkeeping context
- `session_open` / `session_close` to mark whether a game night is still live

It is still just a small side project, but I wanted the event model to stay clean enough that the numbers are easy to trust and the history is easy to read back through.

## CSV format

Main file:

`data/entries.csv`

Header:

```csv
id,created_at,session_date,player_name,event_type,amount_cents,note,actor
```

Amounts are stored in cents to avoid floating-point issues.

## Running it locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Then open:

`http://127.0.0.1:8000`

## Environment values

The app reads these from `.env`:

- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Example:

```env
SECRET_KEY=change-this
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me
```

## Notes

A few choices here were deliberate:

- no database for now
- no user accounts, just one admin login
- public-facing stats pages, admin-only controls
- CSV backup before importing a replacement ledger

If I ever decide to take it further, the first real upgrade would probably be moving the storage layer to SQLite while keeping the rest of the app roughly the same.
