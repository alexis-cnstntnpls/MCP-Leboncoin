import tempfile
from unittest.mock import MagicMock
from lbc_mcp.database import Database
from lbc_mcp.monitor import CollectorService


def test_monitor_cycle_detects_events():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = Database(tmp.name)
        db.add_watchlist("Watch Test", query="Test Item")

        fake_ad = MagicMock()
        fake_ad.id = 999
        fake_ad.subject = "Test Item"
        fake_ad.price = 50.0
        fake_ad.first_publication_date = "2026-11-16T12:00:00"
        fake_ad.location.city = "Lyon"
        fake_ad.location.zipcode = "69001"
        fake_ad.location.department_name = "Rhone"
        fake_ad.location.region_name = "Rhone-Alpes"
        fake_ad.location.lat = 45.75
        fake_ad.location.lng = 4.85
        fake_ad.category_name = "Informatique"
        fake_ad.url = "https://www.leboncoin.fr/ad/999"
        fake_ad.attributes = {}
        fake_ad.body = "Description test"
        fake_ad.images = []
        fake_ad.status = "active"
        fake_ad.expiration_date = None
        fake_ad.has_phone = False
        fake_ad.favorites = 0
        fake_ad._user_id = "user-123"

        fake_search = MagicMock()
        fake_search.ads = [fake_ad]

        mock_gateway = MagicMock()
        mock_gateway.search_page.return_value = fake_search

        collector = CollectorService(db=db, gateway=mock_gateway)
        res = collector.run_cycle()

        assert res["scanned"] == 1
        assert len(res["events"]) == 1
        assert res["events"][0]["event"] == "new"
        assert res["events"][0]["ad_id"] == 999
