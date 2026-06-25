#!/usr/bin/env python3
from __future__ import annotations

from flask import current_app
from flask_mail import Message

from .extensions import mail


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
    mail.send(msg)


def send_league_invite(to_email: str, league_name: str, invite_url: str, invited_by_email: str) -> None:
    msg = Message(
        subject=f"You've been invited to manage {league_name} on myboker.org",
        recipients=[to_email],
        body=(
            f"{invited_by_email} has invited you to join {league_name} as a manager on myboker.org.\n\n"
            f"Accept your invitation:\n\n"
            f"{invite_url}\n\n"
            f"This link expires in 7 days. You'll need a myboker.org account with this email address to accept."
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    mail.send(msg)
