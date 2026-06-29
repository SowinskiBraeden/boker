# myboker.org

Flask app for running home-poker leagues without keeping a spreadsheet open all night.

The current app is account-based and league-based. League owners/managers record sessions and ledger events, viewers can inspect public-facing league data, and site-admin access is reserved for internal tooling.

## What It Does

- account signup, login, and email verification
- league creation, invitations, ownership transfer, and member roles
- player, season, session, and ledger management per league
- append-only ledger events with void/correction support
- public/private league visibility
- leaderboards, charts, dashboard stats, and session summaries
- CSV import/export for league ledgers

## Stack

- Python
- Flask
- SQLAlchemy / Flask-Migrate
- Jinja templates
- Chart.js
- plain CSS

## Project Layout

- `app.py` is the deployment entrypoint for `flask --app app` and Gunicorn.
- `boker/` contains the Flask application package, routes, models, services, repositories, and config.
- `templates/` and `static/` contain Jinja views and public assets.
- `migrations/` contains Alembic migrations for database deploys.
- `tests/` contains the committed regression suite.

## Ledger Model

Each ledger row is an event, not a final snapshot. Corrections are made by appending or voiding events, so the history remains auditable.

Current event types:

- `buyin`
- `front`
- `debt_repayment`
- `writeoff`
- `cashout`
- `paid_out`
- `rollover_in`
- `payout_carry_in`
- `rollover_out`
- `note`
- `session_open`
- `session_close`

Accounting keeps poker results separate from banker cashflow:

- poker investment is `buyin + front + rollover_in`
- poker net is `cashout - poker investment`
- real cash in is `buyin + debt_repayment`
- real cash out is `paid_out`
- `rollover_out` settles the source session without counting as cash out
- `rollover_in` enters play in the destination session without counting as cash in
- `payout_carry_in` records prior-session value carried into a later payout without counting as poker investment or cash in
- `writeoff` resolves a receivable without counting as cash in

Older imports may still contain `paid`, `front_collected`, or `front_writeoff`; those are read as aliases for `paid_out`, `debt_repayment`, and `writeoff`.

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Then open:

`http://127.0.0.1:5000`

## Environment Values

The app reads these from `.env`:

- `SECRET_KEY`
- `APP_ENV`
- `DATABASE_URL`
- `APP_BASE_URL`
- `RATELIMIT_STORAGE_URI`
- `MAIL_SERVER`
- `MAIL_PORT`
- `MAIL_USE_TLS`
- `MAIL_USE_SSL`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`

For public deployments, set `APP_ENV=production`. Production mode enables secure cookies and refuses to start with the development `SECRET_KEY`. Set `RATELIMIT_STORAGE_URI` to a shared backend such as Redis so login and signup limits are enforced across processes.

## Site Admin Access

Internal admin access uses normal database-backed accounts, not hardcoded `.env` credentials.

Grant access:

```bash
flask --app app grant-site-admin user@example.com
```

Revoke access:

```bash
flask --app app revoke-site-admin user@example.com
```

The old single-password `/admin` system has been removed.
