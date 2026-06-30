#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, current_app, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

public_bp = Blueprint("public", __name__)


SEO_USE_CASES = {
    "free-poker-tracker": {
        "title": "Free Poker Tracker for Home Games",
        "meta": "A free poker tracker for home games: record sessions, buy-ins, cashouts, player stats, settlements, and league leaderboards.",
        "keywords": "free poker tracker, home poker tracker, poker session tracker, poker league tracker",
        "eyebrow": "Free poker tracker",
        "h1": "Track home poker without another spreadsheet.",
        "intro": "myboker gives home games one place to record sessions, buy-ins, cashouts, results, and standings. It is built for groups that want reliable records without turning game night into admin work.",
        "primary_cta": "Start tracking",
        "sections": [
            {
                "heading": "Built around the session",
                "body": "Open a session when the game starts, add ledger events during the night, then close it when the books are settled. Same-day games are sequenced automatically, so a busy night can still stay organized.",
            },
            {
                "heading": "Stats come from the records",
                "body": "Net profit, ROI, win rate, recent form, and leaderboard rank are calculated from the buy-ins and cashouts already in the ledger. No duplicate data entry is needed after the game.",
            },
            {
                "heading": "Private by default",
                "body": "Leagues start private. Owners can invite managers or viewers, and public pages are optional when a group wants to share results.",
            },
        ],
        "examples": [
            "Track buy-ins and re-buys while the game is running.",
            "Close a session with cash in, paid out, and open items visible.",
            "Rank regulars while keeping one-time guests provisional.",
        ],
        "faqs": [
            ("Is myboker free?", "Yes. myboker is free to use for home poker tracking."),
            ("Do players need accounts?", "No. Players can be tracked by display name. Only league members need accounts to manage or view private data."),
            ("Can I use it for multiple leagues?", "Yes. One account can create or manage multiple home poker leagues."),
        ],
        "related": ["poker-ledger", "poker-stats-tracker", "home-poker-league-tracker"],
    },
    "poker-ledger": {
        "title": "Poker Ledger for Buy-ins, Cashouts, and Settlements",
        "meta": "Use a poker ledger for home games to record buy-ins, cashouts, fronts, corrections, payouts, and settlement totals.",
        "keywords": "poker ledger, poker ledger tracker, poker buy in tracker, poker cashout tracker, poker settlement tracker",
        "eyebrow": "Poker ledger",
        "h1": "Keep every buy-in, cashout, and settlement in order.",
        "intro": "A good poker ledger should answer the basic money questions quickly: what came in, what went out, who is up, and what is still open. myboker keeps those records attached to each session.",
        "primary_cta": "Create a ledger",
        "sections": [
            {
                "heading": "Append instead of overwrite",
                "body": "Ledger events are kept as history. When someone makes a mistake, the fix is a new correction entry, not a silent edit that makes the old total impossible to explain.",
            },
            {
                "heading": "Settlement stays visible",
                "body": "Cash in, cashout, paid out, house holds, players owe house, and house owes players are shown from the same ledger events. That makes end-of-night cleanup easier.",
            },
            {
                "heading": "Export when you need it",
                "body": "League managers can export the raw ledger to CSV for backups, review, or migration.",
            },
        ],
        "examples": [
            "Add a buy-in, re-buy, cashout, front, payout, or correction.",
            "See open settlement items before closing a session.",
            "Export the raw ledger as CSV.",
        ],
        "faqs": [
            ("What does the poker ledger track?", "It tracks session events such as buy-ins, cashouts, fronts, repayments, payouts, corrections, and notes."),
            ("Can I fix mistakes?", "Yes. Mistakes are handled with correction entries so the ledger history stays clear."),
            ("Can I back up the ledger?", "Yes. Leagues can export ledger data as CSV."),
        ],
        "related": ["free-poker-tracker", "poker-profit-loss-tracker", "home-poker-league-tracker"],
    },
    "poker-stats-tracker": {
        "title": "Poker Stats Tracker for Home Game Leaderboards",
        "meta": "Track poker stats for home games: net profit, ROI, win rate, sessions played, recent form, rank movement, and league leaderboards.",
        "keywords": "poker stats tracker, poker leaderboard, poker win rate tracker, poker ROI tracker, home poker stats",
        "eyebrow": "Poker stats tracker",
        "h1": "Turn session results into useful poker stats.",
        "intro": "Stats are only useful when they come from clean records. myboker builds leaderboards and player summaries from the same ledger events your group enters on game night.",
        "primary_cta": "Track stats",
        "sections": [
            {
                "heading": "Rank the regulars",
                "body": "Set a minimum session count before a player is eligible for the ranked leaderboard. New players and guests can still appear without skewing the main standings.",
            },
            {
                "heading": "Use more than one stat",
                "body": "Sort by net profit, ROI, win rate, recent form, or sessions played. Different views help show who is running hot and who has been consistent over time.",
            },
            {
                "heading": "Filter by season",
                "body": "Create seasons and view standings for a specific period, while preserving the full league history.",
            },
        ],
        "examples": [
            "See net profit and ROI by player.",
            "Track win rate and recent form.",
            "Use eligibility rules to keep rankings fair.",
        ],
        "faqs": [
            ("Which poker stats are tracked?", "myboker tracks net, ROI, win rate, sessions played, recent form, rank movement, biggest wins, and biggest losses."),
            ("Can guests be excluded from rankings?", "Yes. Set a minimum sessions threshold so guests stay provisional until they qualify."),
            ("Can stats be filtered by season?", "Yes. Seasons let you view standings for a selected period."),
        ],
        "related": ["free-poker-tracker", "poker-profit-loss-tracker", "home-poker-league-tracker"],
    },
    "home-poker-league-tracker": {
        "title": "Home Poker League Tracker for Private Games",
        "meta": "Manage a home poker league with sessions, players, seasons, ledger records, private access, public result pages, and leaderboards.",
        "keywords": "home poker league tracker, poker league tracker, private poker league, poker league leaderboard",
        "eyebrow": "Home poker league tracker",
        "h1": "Run a home poker league without losing the history.",
        "intro": "A league is more than one session. myboker keeps players, seasons, sessions, ledger records, and standings together so your group can build a real history over time.",
        "primary_cta": "Start a league",
        "sections": [
            {
                "heading": "Players do not need accounts",
                "body": "Add players by display name and start tracking results. Accounts are for owners, managers, and viewers who need access to league data.",
            },
            {
                "heading": "Roles keep access simple",
                "body": "Owners control settings and membership, managers can run sessions, and viewers can inspect results without changing records.",
            },
            {
                "heading": "Public pages are optional",
                "body": "Keep a league private, or make selected results public when your group wants a shareable standings page.",
            },
        ],
        "examples": [
            "Invite a manager to run sessions.",
            "Group sessions into seasons.",
            "Share public league results only when you choose.",
        ],
        "faqs": [
            ("Can a league stay private?", "Yes. Leagues are private by default."),
            ("Can one account manage multiple leagues?", "Yes. One account can create and manage separate leagues."),
            ("Can I archive players?", "Yes. Archived players leave the active roster while preserving their history."),
        ],
        "related": ["free-poker-tracker", "poker-ledger", "poker-stats-tracker"],
    },
    "poker-profit-loss-tracker": {
        "title": "Poker Profit and Loss Tracker for Home Games",
        "meta": "Track poker profit and loss by player using buy-ins, cashouts, net results, ROI, win rate, and session history.",
        "keywords": "poker profit loss tracker, poker profit tracker, poker loss tracker, poker bankroll tracker, track poker winnings",
        "eyebrow": "Poker profit and loss tracker",
        "h1": "Know who is up, who is down, and why.",
        "intro": "Profit and loss tracking should come from the actual session records. myboker calculates player results from buy-ins, cashouts, and corrections instead of a separate summary sheet.",
        "primary_cta": "Track results",
        "sections": [
            {
                "heading": "Net results per session",
                "body": "Each player's invested amount, cashout, and net result are visible inside the session, with league totals updating automatically.",
            },
            {
                "heading": "Long-term player history",
                "body": "Player pages show cumulative results, win rate, result mix, and session history so the full record is easy to inspect.",
            },
            {
                "heading": "No payment processing",
                "body": "myboker records what happened at the table. It does not hold money, transfer funds, or get between your group and its own settlement process.",
            },
        ],
        "examples": [
            "Calculate net profit from buy-ins and cashouts.",
            "Compare ROI and win rate across players.",
            "Review a player's session-by-session history.",
        ],
        "faqs": [
            ("Does myboker track bankrolls?", "It tracks league and session results. It is not a personal bankroll app or payment processor."),
            ("How is profit calculated?", "Profit is based on cashout minus invested amount for each session, then aggregated over time."),
            ("Can I see losing sessions too?", "Yes. Losing, winning, and break-even sessions are preserved in player history."),
        ],
        "related": ["poker-ledger", "poker-stats-tracker", "free-poker-tracker"],
    },
}


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
    urls.extend(
        _sitemap_url(url_for("public.use_case", slug=slug), "0.8", "monthly")
        for slug in SEO_USE_CASES
    )

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


@public_bp.get("/<slug>")
def use_case(slug: str):
    page = SEO_USE_CASES.get(slug)
    if page is None:
        from flask import abort

        abort(404)
    related_pages = [(related_slug, SEO_USE_CASES[related_slug]) for related_slug in page["related"]]
    faq_schema = [
        {
            "@type": "Question",
            "name": question,
            "acceptedAnswer": {
                "@type": "Answer",
                "text": answer,
            },
        }
        for question, answer in page["faqs"]
    ]
    return render_template(
        "seo_use_case.html",
        slug=slug,
        page=page,
        related_pages=related_pages,
        faq_schema=faq_schema,
    )


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
