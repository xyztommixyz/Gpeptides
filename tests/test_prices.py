"""Admin „Preise & Versand“ – läuft gegen den neutralen Test-Shop (tests/fixture_site)."""
import json

from werkzeug.security import generate_password_hash

import harness

ALL_ON = {"cases": True, "events": True, "affiliate": True, "discord": True, "spin": True}
H = harness.H


def _setup(tmp_path, features=ALL_ON):
    site = harness.fixture_copy(tmp_path, features)
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site), "FREE_SHIPPING_FROM": "0"})
    app.send_mail = lambda *a, **kw: None
    conn = app.sqlite3.connect(app.DB_PATH)
    for name, role in (("Tester", "owner"), ("NexoTest", "nexo")):
        conn.execute("INSERT OR REPLACE INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?)",
                     (name, generate_password_hash(harness.ADMIN_PW), 1, role))
    conn.commit()
    conn.close()
    return app, site


def _login(app, user):
    c = app.app.test_client()
    assert c.post("/admin/api/login", json={"user": user, "password": harness.ADMIN_PW}, headers=H).status_code == 200
    return c


def test_owner_changes_product_price_and_shipping(tmp_path):
    app, site = _setup(tmp_path)
    c = _login(app, "Tester")
    r = c.post("/admin/api/prices", json={"prices": [{"slug": "alpha", "vi": 0, "price": "22,50"}],
                                          "shipping": {"ship_de": "3.50", "free_from": "50"}}, headers=H)
    assert r.status_code == 200 and r.get_json()["changed"] == 3
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    assert data["products"][0]["variants"][0]["price"] == 22.5
    assert list((tmp_path / "bk" / "products").iterdir())  # Sicherheitskopie vor der Änderung
    q = c.post("/api/quote", json={"items": [{"slug": "alpha", "vi": 0, "qty": 1}], "country": "DE"}).get_json()
    assert q["subtotal"] == 2250 and q["shipping"] == 350 and q["freeFrom"] == 5000
    q = c.post("/api/quote", json={"items": [{"slug": "alpha", "vi": 0, "qty": 3}], "country": "DE"}).get_json()
    assert q["shipping"] == 0
    assert c.get("/api/config").get_json()["shipping"]["DE"] == 350
    log = c.get("/admin/api/prices").get_json()["log"]
    assert len(log) == 3 and all(x["who"] == "Tester" for x in log)


def test_invalid_price_rejected(tmp_path):
    app, site = _setup(tmp_path)
    c = _login(app, "Tester")
    before = (site / "products.json").read_text(encoding="utf-8")
    for bad in ("0,10", "abc", "nan", "inf"):
        r = c.post("/admin/api/prices", json={"prices": [{"slug": "alpha", "vi": 0, "price": bad}]}, headers=H)
        assert r.status_code == 400, bad
    assert (site / "products.json").read_text(encoding="utf-8") == before


def test_partner_only_case_price(tmp_path):
    app, site = _setup(tmp_path)
    c = _login(app, "NexoTest")
    view = c.get("/admin/api/prices").get_json()
    assert view["case"]["slug"] == "test-case" and "products" not in view and "shipping" not in view
    assert c.post("/admin/api/prices", json={"prices": [{"slug": "alpha", "vi": 0, "price": "1"}]}, headers=H).status_code == 403
    assert c.post("/admin/api/prices", json={"shipping": {"ship_de": "0"}}, headers=H).status_code == 403
    r = c.post("/admin/api/prices", json={"case_price": "24,99"}, headers=H)
    assert r.status_code == 200 and r.get_json()["changed"] == 1
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    assert data["cases"][0]["price"] == 24.99


def test_no_case_price_without_cases_module(tmp_path):
    app, site = _setup(tmp_path, {**ALL_ON, "cases": False})
    c = _login(app, "Tester")
    assert c.get("/admin/api/prices").get_json()["case"] is None
    r = c.post("/admin/api/prices", json={"case_price": "30"}, headers=H)
    assert r.status_code == 200 and r.get_json()["changed"] == 0
