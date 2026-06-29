#!/usr/bin/env python3
from __future__ import annotations

from html import escape
import socket

from flask import current_app
from flask_mail import Message

from boker.extensions import mail


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


def _html_email(title: str, intro: str, cta_label: str | None = None, cta_url: str | None = None, code: str | None = None, note: str | None = None) -> str:
    app_url = current_app.config.get("APP_BASE_URL", "https://myboker.org").rstrip("/")
    cta_html = ""
    if cta_label and cta_url:
        cta_html = f"""
        <tr>
          <td style="padding:8px 32px 24px;">
            <a href="{escape(cta_url)}" style="display:inline-block;background:#9b8cf0;color:#12101e;text-decoration:none;font:700 14px Arial,sans-serif;padding:12px 18px;border-radius:6px;">{escape(cta_label)}</a>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 24px;color:#7c8294;font:400 12px/1.6 Arial,sans-serif;">
            If the button does not work, copy and paste this link:<br>
            <a href="{escape(cta_url)}" style="color:#b8aff8;word-break:break-all;">{escape(cta_url)}</a>
          </td>
        </tr>
        """

    code_html = ""
    if code:
        code_html = f"""
        <tr>
          <td style="padding:4px 32px 24px;">
            <div style="display:inline-block;letter-spacing:6px;font:800 34px/1.1 Arial,sans-serif;color:#f5f7fb;background:#151925;border:1px solid #32394a;border-radius:8px;padding:14px 18px;">{escape(code)}</div>
          </td>
        </tr>
        """

    note_html = ""
    if note:
        note_html = f"""
        <tr>
          <td style="padding:0 32px 28px;color:#a3a8b8;font:400 14px/1.6 Arial,sans-serif;">{escape(note)}</td>
        </tr>
        """

    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#0f172a;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0f172a;margin:0;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#202129;border:1px solid #313442;border-radius:10px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 10px;">
                <table role="presentation" cellspacing="0" cellpadding="0">
                  <tr>
                    <td width="32" height="32" style="background:#1e1533;border:1px solid #3d3260;border-radius:7px;text-align:center;vertical-align:middle;font-size:15px;color:#9b8cf0;font-family:Arial,sans-serif;">&#9830;</td>
                    <td style="padding-left:10px;vertical-align:middle;font:700 17px/1 Arial,sans-serif;color:#f5f7fb;letter-spacing:-0.3px;">myboker<span style="color:#9b8cf0;">.org</span></td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px 8px;">
                <h1 style="margin:0;color:#f5f7fb;font:800 24px/1.25 Arial,sans-serif;">{escape(title)}</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 22px;color:#c6cad6;font:400 15px/1.6 Arial,sans-serif;">{escape(intro)}</td>
            </tr>
            {code_html}
            {cta_html}
            {note_html}
            <tr>
              <td style="padding:18px 32px 26px;border-top:1px solid #32394a;color:#7c8294;font:400 12px/1.6 Arial,sans-serif;">
                This email was sent by <a href="{escape(app_url)}" style="color:#b8aff8;text-decoration:none;">myboker.org</a>. If you did not request this, you can safely ignore it.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_password_reset(to_email: str, reset_url: str) -> None:
    body = (
        f"You requested a password reset for your myboker.org account.\n\n"
        f"Reset your password:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour. If you did not request this, you can ignore this email."
    )
    msg = Message(
        subject="Reset your myboker.org password",
        recipients=[to_email],
        body=body,
        html=_html_email(
            "Reset your password",
            "We received a request to reset the password for your myboker.org account.",
            cta_label="Reset password",
            cta_url=reset_url,
            note="This link expires in 1 hour.",
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)


def send_temporary_password(to_email: str, temporary_password: str) -> None:
    body = (
        "A temporary password was created for your myboker.org account.\n\n"
        f"Temporary password:\n\n{temporary_password}\n\n"
        "Sign in with this password, then change it from account settings."
    )
    msg = Message(
        subject="Temporary myboker.org password",
        recipients=[to_email],
        body=body,
        html=_html_email(
            "Temporary password",
            "A site administrator created a temporary password for your myboker.org account.",
            code=temporary_password,
            note="Sign in with this password, then change it from account settings.",
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)


def send_email_verification_code(to_email: str, code: str) -> None:
    body = (
        "Verify your myboker.org account with this code:\n\n"
        f"{code}\n\n"
        "This code expires in 15 minutes. If you did not create an account, you can ignore this email."
    )
    msg = Message(
        subject="Your myboker.org verification code",
        recipients=[to_email],
        body=body,
        html=_html_email(
            "Verify your email",
            "Enter this verification code to finish creating your myboker.org account.",
            code=code,
            note="This code expires in 15 minutes. Do not share it with anyone.",
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)


def send_league_invite(to_email: str, league_name: str, invite_url: str, invited_by_email: str, role: str) -> None:
    role_label = role.strip().lower() if role else "member"
    body = (
        f"{invited_by_email} has invited you to join {league_name} as a {role_label} on myboker.org.\n\n"
        f"Accept your invitation:\n\n"
        f"{invite_url}\n\n"
        f"This link expires in 7 days. You'll need a myboker.org account with this email address to accept."
    )
    msg = Message(
        subject=f"You've been invited to join {league_name} on myboker.org",
        recipients=[to_email],
        body=body,
        html=_html_email(
            "You have a league invite",
            f"{invited_by_email} invited you to join {league_name} as a {role_label}.",
            cta_label="Accept invite",
            cta_url=invite_url,
            note="This invitation link expires in 7 days.",
        ),
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )
    _send_message(msg)
