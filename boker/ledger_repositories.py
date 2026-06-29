#!/usr/bin/env python3
from __future__ import annotations

from boker.db import db

if db is None:  # pragma: no cover - imported only when DB dependencies exist.
    raise RuntimeError("Database dependencies are not installed.")

from boker.db_models import (  # noqa: E402
    CANONICAL_EVENT_TYPES,
    LedgerEvent,
    Player,
    PokerSession,
    User,
    canonical_event_type,
)
from boker.storage import EventRow  # noqa: E402


def session_event_ref(session: PokerSession) -> str:
    return f"{session.session_date.isoformat()}-{session.sequence_on_date:02d}"


def append_ledger_event(
    league_id: str,
    session_id: str,
    event_type: str,
    amount_cents: int,
    created_by_user_id: str,
    player_id: str | None = None,
    note: str | None = None,
    legacy_event_id: str | None = None,
    legacy_player_name: str | None = None,
) -> LedgerEvent:
    canonical_type = canonical_event_type(event_type)
    if canonical_type not in CANONICAL_EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")

    if canonical_type in {"note", "session_open", "session_close"}:
        amount_cents = 0

    if player_id is None and canonical_type not in {"note", "session_open", "session_close"}:
        raise ValueError(f"Event type {canonical_type} requires a player.")

    event = LedgerEvent(
        league_id=league_id,
        session_id=session_id,
        player_id=player_id,
        event_type=canonical_type,
        amount_cents=amount_cents,
        note=note.strip() if note else None,
        created_by_user_id=created_by_user_id,
        legacy_event_id=legacy_event_id,
        legacy_player_name=legacy_player_name,
    )
    db.session.add(event)
    return event


def list_ledger_events_for_league(league_id: str) -> list[LedgerEvent]:
    return (
        LedgerEvent.query.filter_by(league_id=league_id, voided_at=None)
        .order_by(LedgerEvent.created_at.asc(), LedgerEvent.id.asc())
        .all()
    )


def list_ledger_events_for_session(league_id: str, session_id: str) -> list[LedgerEvent]:
    return (
        LedgerEvent.query.filter_by(
            league_id=league_id,
            session_id=session_id,
            voided_at=None,
        )
        .order_by(LedgerEvent.created_at.asc(), LedgerEvent.id.asc())
        .all()
    )


def _event_row(event: LedgerEvent, session: PokerSession, player: Player | None, user: User | None) -> EventRow:
    return EventRow(
        id=event.id,
        created_at=event.created_at.isoformat() if event.created_at else "",
        session_id=session_event_ref(session),
        session_date=session.session_date.isoformat(),
        player_name=(player.display_name if player is not None else event.legacy_player_name or ""),
        event_type=event.event_type,
        amount_cents=event.amount_cents,
        note=event.note or "",
        actor=user.email if user is not None else "",
        voided_at=event.voided_at.isoformat() if event.voided_at else "",
        void_reason=event.void_reason or "",
    )


def list_all_event_rows_for_league(league_id: str) -> list[EventRow]:
    """All events including voided — for display feeds only, not accounting."""
    rows = (
        db.session.query(LedgerEvent, PokerSession, Player, User)
        .join(
            PokerSession,
            (PokerSession.league_id == LedgerEvent.league_id)
            & (PokerSession.id == LedgerEvent.session_id),
        )
        .outerjoin(
            Player,
            (Player.league_id == LedgerEvent.league_id)
            & (Player.id == LedgerEvent.player_id),
        )
        .outerjoin(User, User.id == LedgerEvent.created_by_user_id)
        .filter(LedgerEvent.league_id == league_id)
        .order_by(
            PokerSession.session_date.asc(),
            PokerSession.sequence_on_date.asc(),
            LedgerEvent.created_at.asc(),
            LedgerEvent.id.asc(),
        )
        .all()
    )
    return [_event_row(event, session, player, user) for event, session, player, user in rows]


def void_ledger_event(event_id: str, league_id: str, user_id: str, reason: str) -> LedgerEvent:
    from datetime import datetime, timezone
    event = LedgerEvent.query.filter_by(id=event_id, league_id=league_id).first()
    if event is None:
        raise ValueError("Event not found.")
    if event.voided_at is not None:
        raise ValueError("Event is already voided.")
    event.voided_at = datetime.now(timezone.utc)
    event.voided_by_user_id = user_id
    event.void_reason = reason.strip() or "Voided by owner."
    return event


def list_event_rows_for_league(league_id: str) -> list[EventRow]:
    rows = (
        db.session.query(LedgerEvent, PokerSession, Player, User)
        .join(
            PokerSession,
            (PokerSession.league_id == LedgerEvent.league_id)
            & (PokerSession.id == LedgerEvent.session_id),
        )
        .outerjoin(
            Player,
            (Player.league_id == LedgerEvent.league_id)
            & (Player.id == LedgerEvent.player_id),
        )
        .outerjoin(User, User.id == LedgerEvent.created_by_user_id)
        .filter(
            LedgerEvent.league_id == league_id,
            LedgerEvent.voided_at.is_(None),
        )
        .order_by(
            PokerSession.session_date.asc(),
            PokerSession.sequence_on_date.asc(),
            LedgerEvent.created_at.asc(),
            LedgerEvent.id.asc(),
        )
        .all()
    )
    return [_event_row(event, session, player, user) for event, session, player, user in rows]


def list_all_event_rows_for_session(league_id: str, session_id: str) -> list[EventRow]:
    """All events for a session including voided — for display only, not accounting."""
    rows = (
        db.session.query(LedgerEvent, PokerSession, Player, User)
        .join(
            PokerSession,
            (PokerSession.league_id == LedgerEvent.league_id)
            & (PokerSession.id == LedgerEvent.session_id),
        )
        .outerjoin(
            Player,
            (Player.league_id == LedgerEvent.league_id)
            & (Player.id == LedgerEvent.player_id),
        )
        .outerjoin(User, User.id == LedgerEvent.created_by_user_id)
        .filter(
            LedgerEvent.league_id == league_id,
            LedgerEvent.session_id == session_id,
        )
        .order_by(LedgerEvent.created_at.asc(), LedgerEvent.id.asc())
        .all()
    )
    return [_event_row(event, session, player, user) for event, session, player, user in rows]


def list_event_rows_for_session(league_id: str, session_id: str) -> list[EventRow]:
    rows = (
        db.session.query(LedgerEvent, PokerSession, Player, User)
        .join(
            PokerSession,
            (PokerSession.league_id == LedgerEvent.league_id)
            & (PokerSession.id == LedgerEvent.session_id),
        )
        .outerjoin(
            Player,
            (Player.league_id == LedgerEvent.league_id)
            & (Player.id == LedgerEvent.player_id),
        )
        .outerjoin(User, User.id == LedgerEvent.created_by_user_id)
        .filter(
            LedgerEvent.league_id == league_id,
            LedgerEvent.session_id == session_id,
            LedgerEvent.voided_at.is_(None),
        )
        .order_by(LedgerEvent.created_at.asc(), LedgerEvent.id.asc())
        .all()
    )
    return [_event_row(event, session, player, user) for event, session, player, user in rows]
