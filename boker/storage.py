#!/usr/bin/env python3
from __future__ import annotations

from typing import TypedDict

CSV_HEADERS = [
    "id",
    "created_at",
    "session_id",
    "session_date",
    "player_name",
    "event_type",
    "amount_cents",
    "note",
    "actor",
]


class EventRow(TypedDict):
    id: str
    created_at: str
    session_id: str
    session_date: str
    player_name: str
    event_type: str
    amount_cents: int
    note: str
    actor: str
    voided_at: str
    void_reason: str
