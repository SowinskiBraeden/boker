# Poker Portal

A small server-rendered poker ledger app for low-stakes no-limit hold'em nights.

## Stack

- Python
- Flask
- Jinja templates
- Chart.js
- Custom CSS
- Append-only CSV event ledger

## What this MVP does

- Public all-time leaderboard
- Public session archive
- Public per-player stat pages
- Admin-only login for adding ledger events
- Append-only `entries.csv` audit trail
- Buy-ins, cash-outs, note-only events, and correction events using negative amounts
- Cumulative profit chart and player charts

## Ledger model

The app treats the CSV as an append-only audit trail.

Each row is one event:

- `buyin`
- `cashout`
- `note`

This means you do not edit old rows when something changes. Instead, you append:

- another buy-in row for a rebuy
- another cash-out row if they cash more later
- a negative amount to correct a mistaken buy-in or cash-out
- a `note` row for bookkeeping context

## CSV format

`data/entries.csv`

```csv
id,created_at,session_date,player_name,event_type,amount_cents,note,actor
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export $(grep -v '^#' .env | xargs)
python app.py
```

Open:

- public site: `http://127.0.0.1:5000/leaderboard`
- admin login: `http://127.0.0.1:5000/admin/login`

## Default environment values

The app reads these environment variables:

- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

If you do not set them, the app falls back to insecure defaults for local development only.

## Suggested next steps

- Add session filters like last 5, 10, 20, all
- Add player color editing
- Add export/import tools
- Add session status like open and closed
- Replace CSV storage with SQLite later without changing the page layer
- Add reverse proxy deployment with Caddy or Nginx

## Deploy notes

For a private home-hosted deployment, I would run this behind Caddy or Nginx and set real environment variables instead of using defaults.
