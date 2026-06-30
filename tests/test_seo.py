import tempfile
import unittest
from pathlib import Path

from app import create_app
from boker.auth import hash_password
from boker.db import db


class SeoTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "APP_BASE_URL": "https://myboker.org",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self.tmpdir.cleanup()

    def test_landing_page_has_search_metadata(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Free Poker Tracker, Ledger, Stats & Profit/Loss App", html)
        self.assertIn('name="description"', html)
        self.assertIn("free poker tracker and poker ledger for home games", html)
        self.assertIn("My Boker", html)
        self.assertIn("poker profit or loss", html)
        self.assertIn('rel="canonical" href="https://myboker.org/"', html)
        self.assertIn('application/ld+json', html)

    def test_robots_txt_allows_public_crawling_and_points_to_sitemap(self):
        response = self.client.get("/robots.txt")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/plain")
        self.assertIn("Allow: /", body)
        self.assertIn("Disallow: /internal/", body)
        self.assertIn("Disallow: /account/", body)
        self.assertIn("Sitemap: https://myboker.org/sitemap.xml", body)

    def test_sitemap_xml_lists_public_static_pages(self):
        response = self.client.get("/sitemap.xml")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/xml")
        self.assertIn("<loc>https://myboker.org/</loc>", body)
        self.assertIn("<loc>https://myboker.org/explore</loc>", body)
        self.assertIn("<loc>https://myboker.org/help</loc>", body)

    def test_explore_requires_search_before_showing_public_leagues(self):
        with self.app.app_context():
            from boker.db_models import League, User

            owner = User(email="owner@example.com", password_hash=hash_password("password123"))
            db.session.add(owner)
            db.session.flush()
            league = League(
                name="Friday Night Poker",
                slug="friday-night-poker",
                public_key="friday1",
                created_by_user_id=owner.id,
                visibility="public",
            )
            db.session.add(league)
            db.session.commit()

        default_response = self.client.get("/explore")
        default_html = default_response.get_data(as_text=True)
        search_response = self.client.get("/explore?q=Friday")
        search_html = search_response.get_data(as_text=True)
        sitemap_response = self.client.get("/sitemap.xml")
        sitemap_xml = sitemap_response.get_data(as_text=True)

        self.assertEqual(default_response.status_code, 200)
        self.assertIn("Enter a league name to search", default_html)
        self.assertNotIn("Friday Night Poker", default_html)
        self.assertEqual(search_response.status_code, 200)
        self.assertIn("Friday Night Poker", search_html)
        self.assertNotIn("/l/friday-night-poker-friday1", sitemap_xml)

    def test_explore_search_handles_missing_database_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing-tables.sqlite3"
            app = create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
                }
            )
            client = app.test_client()

            response = client.get("/explore?q=Friday")

            with app.app_context():
                db.session.remove()
                db.engine.dispose()

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("No public leagues found", html)


if __name__ == "__main__":
    unittest.main()
