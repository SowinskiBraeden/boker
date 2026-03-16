#!/usr/bin/env python3
from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

CSV_HEADERS = [
    "id",
    "created_at",
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
    session_date: str
    player_name: str
    event_type: str
    amount_cents: int
    note: str
    actor: str


VALID_EVENT_TYPES = {"buyin", "cashout", "note"}


def ensure_data_file(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        return

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()


def load_events(csv_path: Path) -> list[EventRow]:
    ensure_data_file(csv_path)

    events: list[EventRow] = []
    with csv_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            events.append(
                EventRow(
                    id=row["id"],
                    created_at=row["created_at"],
                    session_date=row["session_date"],
                    player_name=row["player_name"],
                    event_type=row["event_type"],
                    amount_cents=int(row["amount_cents"] or 0),
                    note=row.get("note", ""),
                    actor=row.get("actor", ""),
                )
            )

    events.sort(key=lambda event: (event["session_date"], event["created_at"], event["id"]))
    return events


def append_event(
    csv_path: Path,
    session_date: str,
    player_name: str,
    event_type: str,
    amount_cents: int,
    note: str,
    actor: str,
) -> EventRow:
    ensure_data_file(csv_path)

    normalized_type = event_type.strip().lower()
    if normalized_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")

    if normalized_type == "note":
        amount_cents = 0

    event = EventRow(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        session_date=session_date.strip(),
        player_name=player_name.strip(),
        event_type=normalized_type,
        amount_cents=amount_cents,
        note=note.strip(),
        actor=actor.strip(),
    )

    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writerow(event)

    return event
