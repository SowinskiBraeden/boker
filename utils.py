#!/usr/bin/env python3
"""Formatting, sorting, and classification helpers shared across the app."""
from __future__ import annotations

from datetime import datetime

from markupsafe import Markup

from models import SessionEntry, SessionSummary

BREAK_EVEN_TOLERANCE_CENTS = 100


def cents_to_dollars(cents: int) -> Markup:
    value = cents / 100
    return Markup(f'<span class="currency-symbol">$</span>{value:,.2f}')


def safe_date_label(raw_date: str) -> str:
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return raw_date


def session_sequence_number(session_id: str, session_date: str) -> int:
    suffix = session_id.strip().replace(f"{session_date.strip()}-", "", 1)

    if session_id.strip() == session_date.strip():
        return 1
    if suffix.isdigit():
        return int(suffix)
    if suffix.lower().startswith("s") and suffix[1:].isdigit():
        return int(suffix[1:])
    return 9999


def session_display_suffix(session_id: str, session_date: str) -> str:
    suffix = session_id.strip().replace(f"{session_date.strip()}-", "", 1)

    if session_id.strip() == session_date.strip():
        return ""
    if suffix.isdigit():
        return f"S{int(suffix)}"
    if suffix.lower().startswith("s") and suffix[1:].isdigit():
        return f"S{int(suffix[1:])}"
    return suffix


def session_chart_label(session: SessionSummary) -> str:
    suffix = session_display_suffix(session.session_id, session.session_date)
    date_label = safe_date_label(session.session_date)
    return f"{date_label} · {suffix}" if suffix else date_label


def session_label(session: SessionSummary) -> str:
    return session_chart_label(session)


def session_sort_key(session: SessionSummary) -> tuple[str, int, str, str]:
    session_id = session.session_id.strip()
    session_date = session.session_date.strip()
    return (
        session_date,
        session_sequence_number(session_id, session_date),
        session.opened_at,
        session_id,
    )


def entry_sort_key(entry: SessionEntry) -> tuple[str, int, str]:
    return (
        entry.session_date,
        session_sequence_number(entry.session_id, entry.session_date),
        entry.session_id,
    )


def net_result_bucket(value_cents: int) -> str:
    if value_cents > BREAK_EVEN_TOLERANCE_CENTS:
        return "win"
    if value_cents < -BREAK_EVEN_TOLERANCE_CENTS:
        return "loss"
    return "even"
