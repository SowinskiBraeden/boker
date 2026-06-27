#!/usr/bin/env python3
from __future__ import annotations

import socket

from flask import current_app
from flask_mail import Message

from extensions import mail


def _mail_send_suppressed() -> bool:
    state = current_app.extensions.get("mail")
    return bool(getattr(state, "suppress", False))


def _send_message(msg: Message) -> None:
    if not _mail_send_suppressed() and not current_app.config.get("MAIL_SERVER"):
        raise RuntimeError("Mail server is not configured.")

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(float(current_app.config.get("MAIL_TIMEOUT", 5)))
    try:
        mail.send(msg)
    finally:
        socket.setdefaulttimeout(previous_timeout)


def send_password_reset(to_email: str, reset_url: str) -> None:
    msg = Message(
        subject="Reset your myboker.org password",
        recipients=[to_email],
        body=(
            f"You requested a password reset for your myboker.org account.\n\n"
            f"Click the link below to set a new password:\n\n"
            f"{reset_url}\n\n"
            f"This link expires in 1 hour. If you did not request this, you can ignore this email."
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)


def send_league_invite(to_email: str, league_name: str, invite_url: str, invited_by_email: str, role: str) -> None:
    role_label = role.strip().lower() if role else "member"
    msg = Message(
        subject=f"You've been invited to join {league_name} on myboker.org",
        recipients=[to_email],
        body=(
            f"{invited_by_email} has invited you to join {league_name} as a {role_label} on myboker.org.\n\n"
            f"Accept your invitation:\n\n"
            f"{invite_url}\n\n"
            f"This link expires in 7 days. You'll need a myboker.org account with this email address to accept."
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)
