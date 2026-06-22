---
name: project-overview
description: Flask poker ledger app — design system, tech stack, key files
metadata:
  type: project
---

Flask/Jinja app: poker session tracker and leaderboard. Append-only CSV event ledger (`data/entries.csv`).

**Design system (Graphite + Violet):** Implemented June 2026.
- `static/css/tokens.css` — all CSS custom properties (--accent: #9b8cf0 violet, not orange)
- `static/css/style.css` — component classes: .panel, .stat, .tbl, .badge, .segmented, .btn, .feed, etc.
- Fonts: Spectral (display), Hanken Grotesk (UI), IBM Plex Mono (numbers/labels)

**Pages:** leaderboard, sessions, session_detail, player_detail, admin_dashboard, admin_login.

**Key patterns:**
- Leaderboard has Eligible/All/Recent segmented control; `ELIGIBLE_MIN_SESSIONS = 3` in app.py
- Session detail has Compact/Full toggle for the table (`col-acct` class, `.is-full` on table)
- Chart.js colors: leaderboard uses CHART_PALETTE from template JS; bars use `net_tone()` from stats.py
- `--text-muted` and `--line` CSS vars kept as backward compat for Chart.js JS reads
- `.venv/bin/python` is the Python runtime

**Data model:** EventRow CSV → SessionEntry → SessionSummary, PlayerStats (via stats.py). No DB.

**Why:** Design ported from "Poker Ledger.dc.html" prototype spec per handoff document.
