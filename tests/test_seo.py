import tempfile
import unittest
from pathlib import Path

from app import create_app
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
        self.assertIn("Free Home Poker Tracker, Ledger & League Leaderboards", html)
        self.assertIn('name="description"', html)
        self.assertIn("Track home poker sessions, buy-ins, cashouts, settlements", html)
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


if __name__ == "__main__":
    unittest.main()
