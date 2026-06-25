# Boker

A Flask web app for tracking low-stakes poker nights. Multiple leagues, per-player stats, session history, leaderboards, and a full double-entry ledger — without keeping a spreadsheet open.

## Features

- User accounts with registration and login
- Create and manage multiple leagues
- Invite league members by email with role-based access (owner / manager / viewer)
- Public or private league visibility
- Per-session event ledger (buy-ins, cashouts, fronts, rollovers, payouts)
- All-time leaderboard with rank tracking and eligibility thresholds
- Per-player stat pages with session history and charts
- Open / closed session tracking
- Debt tracking: fronts, repayments, and write-offs
- CSV export of any league ledger
- CSV import for migrating historical data
- Rate limiting and CSRF protection

## Stack

- Python 3 / Flask
- SQLAlchemy + Flask-Migrate (SQLite for local dev, PostgreSQL in production)
- Jinja2 templates
- Chart.js
- Plain CSS

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/SowinskiBraeden/boker
cd boker
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
SECRET_KEY=replace-this-with-a-long-random-string
```

The other values can be left as defaults for local development. See the [Environment variables](#environment-variables) section for the full list.

### 4. Initialize the database

```bash
flask --app app db upgrade
```

This creates `data/boker-dev.sqlite3` and applies all migrations. Run this again whenever you pull new migrations.

### 5. Run the development server

```bash
flask --app app run
```

Then open `http://127.0.0.1:5000` and register an account.

## Environment variables

All variables are read from `.env` at startup. Copy `.env.example` as a starting point.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | `change-this-before-deploying` | Flask session signing key. Use a long random string in production. |
| `DATABASE_URL` | No | `sqlite:///data/boker-dev.sqlite3` | SQLAlchemy connection URL. For production use a `postgresql+psycopg://` URL. |
| `FLASK_ENV` | No | _(unset)_ | Set to `production` to enable secure cookie flags. |
| `APP_BASE_URL` | No | `http://localhost:5000` | Base URL used when generating links in email (invite, password reset). |
| `MAIL_SERVER` | No | _(empty)_ | SMTP server hostname. Email features are disabled if left blank. |
| `MAIL_PORT` | No | `587` | SMTP port. |
| `MAIL_USE_TLS` | No | `true` | Set to `false` to disable STARTTLS. |
| `MAIL_USERNAME` | No | _(empty)_ | SMTP username / API key. |
| `MAIL_PASSWORD` | No | _(empty)_ | SMTP password / API key secret. |
| `MAIL_DEFAULT_SENDER` | No | `noreply@myboker.org` | From address on outgoing mail. |
| `FLASK_DEBUG` | No | `0` | Set to `1` to enable the Flask reloader and debugger. |

## Running tests

```bash
python -m pytest tests/
```

Or with the standard library runner:

```bash
python -m unittest discover tests/
```

## Production deployment

### Database

Set `DATABASE_URL` to a PostgreSQL connection string:

```env
DATABASE_URL=postgresql+psycopg://user:password@host/dbname
```

`psycopg` (v3) is already in `requirements.txt`.

After deploying, run migrations:

```bash
flask --app app db upgrade
```

### Environment

Set `FLASK_ENV=production` to enable:
- `Secure` flag on the session cookie
- `SameSite=Strict` cookie policy
- HTTPS preferred URL scheme

Generate a strong secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### WSGI

Run with a production WSGI server (gunicorn, uWSGI, etc.) rather than the Flask dev server:

```bash
gunicorn "app:app"
```

## Ledger model

Each event in the ledger is an append-only row. Nothing is edited or deleted — corrections are new rows. This keeps the full history readable.

### Event types

| Event | Description |
|---|---|
| `buyin` | Player buys chips. Counts as poker investment and real cash in. |
| `front` | House fronts chips to a player. Counts as poker investment; cash is owed back. |
| `cashout` | Gross chip result at end of session. Not cash movement — sets the payout claim. |
| `paid_out` | Cash physically paid out to a player. Settles the payout claim. |
| `rollover_out` | Player carries winnings into the next session instead of being paid. Settles source session without cash movement. |
| `rollover_in` | Carried funds enter play in the destination session. Counts as investment without new cash in. |
| `payout_carry_in` | Prior-session credit applied to a later payout. Increases the payout due without counting as investment. |
| `debt_repayment` | Player repays a front outside of poker. Counts as real cash in; reduces the receivable. |
| `writeoff` | Front is forgiven. Resolves the receivable without cash. |
| `note` | Free-text bookkeeping note. No financial effect. |
| `session_open` | Marks a session as live. |
| `session_close` | Marks a session as closed. |

Legacy ledgers may contain `paid`, `front_collected`, or `front_writeoff` — the app reads these as aliases for `paid_out`, `debt_repayment`, and `writeoff`.

### Accounting summary

- **Poker investment** = `buyin + front + rollover_in`
- **Poker net** = `cashout − investment`
- **Real cash in** = `buyin + debt_repayment`
- **Real cash out** = `paid_out`
- **Rollover-out** settles a session without cash leaving the book
- **Writeoff** resolves a receivable without cash coming in

## CSV format

Each league's ledger can be exported and re-imported as CSV.

Header:

```
id,created_at,session_id,session_date,player_name,event_type,amount_cents,note,actor
```

Amounts are stored in cents (integer) to avoid floating-point rounding.

Import validates headers, event types, session references, and player names before writing anything. Rows with a matching `id` are skipped so re-importing a previous export is safe.
