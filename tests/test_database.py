import tempfile
from lbc_mcp.database import Database


def test_database_record_and_price_drop():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = Database(tmp.name)
        
        # 1. Enregistrement initial
        ad1 = {"id": 100, "title": "Test GPU", "price": 400.0, "city": "Paris"}
        res1 = db.record_ad(ad1)
        assert res1["event"] == "new"
        assert res1["price"] == 400.0

        # 2. Re-visite meme prix
        res2 = db.record_ad(ad1)
        assert res2["event"] == "seen"

        # 3. Baisse de prix
        ad2 = {"id": 100, "title": "Test GPU", "price": 320.0, "city": "Paris"}
        res3 = db.record_ad(ad2)
        assert res3["event"] == "price_drop"
        assert res3["old_price"] == 400.0
        assert res3["new_price"] == 320.0
        assert res3["drop_pct"] == 20.0

        # 4. Historique
        history = db.get_price_history(100)
        assert history is not None
        assert history["current_price"] == 320.0
        assert history["first_price"] == 400.0
        assert history["max_price"] == 400.0
        assert history["min_price"] == 320.0
        assert len(history["history"]) == 2

        # 5. Deals
        deals = db.get_recent_deals(min_drop_pct=10.0)
        assert len(deals) == 1
        assert deals[0]["id"] == 100
        assert deals[0]["price_drop_pct"] == 20.0


def test_database_watchlist():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = Database(tmp.name)
        w_id = db.add_watchlist("NAS", query="QNAP", price_max=200, departments=["69", "75"])
        assert w_id > 0

        items = db.list_watchlist()
        assert len(items) == 1
        assert items[0]["name"] == "NAS"
        assert items[0]["query"] == "QNAP"
        assert items[0]["departments"] == ["69", "75"]

        db.set_watchlist_active(w_id, False)
        assert len(db.list_watchlist(active_only=True)) == 0
        assert len(db.list_watchlist(active_only=False)) == 1
