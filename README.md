# Poker Portal

A small server-rendered poker ledger app for low-stakes no-limit hold'em nights.

## Stack

- Python
- Flask
- Jinja templates
- Chart.js
- Append-only CSV event ledger

## Stuff is does

- All-time leaderboard
- Session archive
- Per player stat pages
- Admin only login for adding ledger events
- Append only `entries.csv` audit trail
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

## Default environment values

The app reads these environment variables:

- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
