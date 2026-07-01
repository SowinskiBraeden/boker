# myboker.org

Free web app for running home-poker leagues without rebuilding the same spreadsheet every game night.

myboker.org is now split into two main surfaces:

- a public site for discovery, SEO use-case pages, help, privacy, terms, and optional public league search
- an account-based league app where owners and managers track players, sessions, ledgers, seasons, stats, and settlements

## Public Site

The public site presents myboker as a free poker tracker, poker ledger, stats tracker, and profit/loss tracker for home games.

Current public pages and endpoints:

- `/` - overhauled landing page with structured data, feature sections, app previews, and account CTAs
- `/explore` - search public leagues by name without exposing a full public directory
- `/help`, `/privacy`, `/terms` - support and legal pages
- `/robots.txt` and `/sitemap.xml` - crawler rules and sitemap entries
- SEO use-case pages:
  - `/free-poker-tracker`
  - `/poker-ledger`
  - `/poker-stats-tracker`
  - `/home-poker-league-tracker`
  - `/poker-profit-loss-tracker`

Leagues are private by default. Public discovery and public league pages only apply when a league owner enables public visibility.

## League App

The logged-in app is account-based and league-based. League owners can create and configure leagues, invite members, transfer ownership, and decide whether league results are public. Managers can run league operations, and viewers can inspect league data without changing records.

Core features:

- account signup, login, email verification, password reset, and account settings
- league creation, invitations, ownership transfer, member roles, and archival
- player roster management with archived/reactivated players
- seasons with manual management and auto-assignment
- session creation, open/close workflow, same-day session sequencing, and session summaries
- append-only ledger events with void/correction support
- settlement views for cash in, paid out, house holds, players owe house, and house owes players
- dashboards, player pages, leaderboards, charts, rank movement, ROI, win rate, recent form, and provisional player handling
- CSV import/export for league ledgers
- site-admin tooling under `/internal`

myboker records poker results and settlement state. It does not process payments, hold funds, or replace a league's own settlement process.

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
- `boker/routes/public.py` defines the public site, SEO use-case pages, sitemap, robots file, and public league search.
- `boker/routes/account.py`, `boker/routes/leagues.py`, and `boker/routes/internal.py` define account, league, and internal admin workflows.
- `templates/` contains the Jinja views, including the landing page and league app screens.
- `static/` contains CSS, favicon assets, icons, and the web manifest.
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

For local development, omit `DATABASE_URL` to use the default SQLite database at `data/boker-dev.sqlite3`.

## Environment Values

The app reads these from `.env`. Use `.env.example` for local development and `.env.production.example` as the production checklist.

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

`APP_BASE_URL` is used for canonical URLs, sitemap URLs, email links, and other absolute public URLs.

For public deployments, set `APP_ENV=production`. Production mode enables secure cookies and refuses to start with the development `SECRET_KEY` or any SQLite database. Use PostgreSQL for `DATABASE_URL`, install dependencies from `requirements.txt`, then run:

```bash
flask --app app db upgrade
```

Set `RATELIMIT_STORAGE_URI` to a shared backend such as Redis so login and signup limits are enforced across processes.

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

Site admins can review platform stats, users, and leagues under `/internal`.
