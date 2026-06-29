#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, current_app, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

public_bp = Blueprint("public", __name__)


def _absolute_url(path: str) -> str:
    base_url = current_app.config.get("APP_BASE_URL", "https://myboker.org").rstrip("/")
    return f"{base_url}{path}"


def _sitemap_url(path: str, priority: str, changefreq: str = "weekly") -> str:
    return (
        "  <url>\n"
        f"    <loc>{xml_escape(_absolute_url(path))}</loc>\n"
        f"    <lastmod>{date.today().isoformat()}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        "  </url>"
    )


@public_bp.get("/")
def home():
    return render_template("landing.html")


@public_bp.get("/robots.txt")
def robots_txt():
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /internal/",
            "Disallow: /account/",
            "Sitemap: " + _absolute_url(url_for("public.sitemap_xml")),
            "",
        ]
    )
    return Response(body, mimetype="text/plain")


@public_bp.get("/sitemap.xml")
def sitemap_xml():
    urls = [
        _sitemap_url(url_for("public.home"), "1.0", "weekly"),
        _sitemap_url(url_for("public.explore"), "0.8", "daily"),
        _sitemap_url(url_for("public.help"), "0.7", "monthly"),
        _sitemap_url(url_for("public.privacy"), "0.3", "yearly"),
        _sitemap_url(url_for("public.terms"), "0.3", "yearly"),
    ]

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


@public_bp.get("/help")
def help():
    return render_template("support.html")


@public_bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@public_bp.get("/terms")
def terms():
    return render_template("terms.html")


@public_bp.get("/explore")
def explore():
    from boker.auth import is_logged_in
    from boker.db import database_extensions_available
    from boker.league_repositories import league_counts, list_public_leagues

    q = request.args.get("q", "").strip()
    leagues = []
    counts = {}
    if q and database_extensions_available():
        try:
            leagues = list_public_leagues(q)
            counts = {league.id: league_counts(league.id) for league in leagues}
        except SQLAlchemyError as exc:
            from boker.db import db

            db.session.rollback()
            current_app.logger.warning("Explore public league search failed: %s", exc.__class__.__name__)
    return render_template("explore.html", leagues=leagues, counts=counts, q=q, has_searched=bool(q))
