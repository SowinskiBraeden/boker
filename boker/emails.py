#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import socket

from flask import current_app
from flask_mail import Message

from .extensions import mail


class MailNotConfiguredError(RuntimeError):
    pass


@contextmanager
def _mail_socket_timeout() -> Iterator[None]:
    timeout = current_app.config.get("MAIL_SEND_TIMEOUT")
    if timeout is None:
        yield
        return

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(float(timeout))
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _send(msg: Message) -> None:
    if not str(current_app.config.get("MAIL_SERVER", "")).strip():
        raise MailNotConfiguredError("MAIL_SERVER is not configured.")

    with _mail_socket_timeout():
        mail.send(msg)


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
    _send(msg)


def send_email_verification(to_email: str, verify_url: str) -> None:
    msg = Message(
        subject="Verify your myboker.org email address",
        recipients=[to_email],
        body=(
            f"Thanks for signing up for myboker.org!\n\n"
            f"Please verify your email address by clicking the link below:\n\n"
            f"{verify_url}\n\n"
            f"This link expires in 24 hours. If you did not create an account, you can ignore this email."
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send(msg)


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
    _send(msg)
