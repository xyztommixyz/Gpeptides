"""Gewinnspiel an Partner-Codes knüpfen – läuft gegen den neutralen Test-Shop (tests/fixture_site)."""
import time

from werkzeug.security import generate_password_hash

import harness

ALL_ON = {"cases": True, "events": True, "affiliate": True, "discord": True, "spin": True}
H = harness.H
ITEMS = [{"slug": "alpha", "vi": 0, "qty": 1}]


def _setup(tmp_path, features=ALL_ON):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(harness.fixture_copy(tmp_path, features))})
    app.send_mail = lambda *a, **kw: None
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT OR REPLACE INTO admin_users(username,pw_hash,created_at,role) VALUES('Tester',?,1,'owner')",
                 (generate_password_hash(harness.ADMIN_PW),))
    for code in ("INFLU10", "OTHER10"):
        conn.execute("INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,?,NULL,10,10,1,1)", (code, code.title()))
    conn.commit()
    conn.close()
    adm = app.app.test_client()
    assert adm.post("/admin/api/login", json={"user": "Tester", "password": harness.ADMIN_PW}, headers=H).status_code == 200
    return app, adm


def _order(app, email, code=None):
    c = app.app.test_client()
    r = c.post("/api/orders", headers=H, json={"items": ITEMS, "address": {**harness.ADDR_DE, "email": email}, "code": code,
                                               "method": "prepayment", "acceptTerms": True, "acceptResearch": True, "lang": "de"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["order"]


def _giveaway(adm, codes, source="orders"):
    t = time.time()
    fmt = lambda x: time.strftime("%Y-%m-%dT%H:%M", time.localtime(x))
    r = adm.post("/admin/api/events", headers=H, json={"kind": "giveaway", "title": "Code-Gewinnspiel", "starts": fmt(t - 3600), "ends": fmt(t + 86400),
                                                       "published": True, "terms": "1. Test", "source": source, "paid_only": False, "codes": codes})
    assert r.status_code == 200, r.get_json()
    return next(e for e in adm.get("/admin/api/events").get_json()["events"] if e["title"] == "Code-Gewinnspiel")


def test_only_orders_with_code_are_tickets(tmp_path):
    app, adm = _setup(tmp_path)
    with_code = _order(app, "a@example.test", "influ10")
    _order(app, "b@example.test", "OTHER10")
    _order(app, "c@example.test")
    ev = _giveaway(adm, ["influ10", "GIBTESNICHT"])
    assert ev["codes"] == ["INFLU10"]           # unbekannte Codes fallen weg, Schreibweise egal
    tk = adm.get(f"/admin/api/events/{ev['id']}/tickets").get_json()["tickets"]
    assert [x["order_id"] for x in tk] == [with_code] and tk[0]["code"] == "INFLU10"
    pub = app.app.test_client().get("/api/events?lang=de").get_json()
    assert pub["events"][0]["codes"] == ["INFLU10"]
    csv = adm.get(f"/admin/api/events/{ev['id']}/tickets?csv=1").get_data(as_text=True)
    assert "INFLU10" in csv and "Code" in csv.splitlines()[0]


def test_without_codes_all_orders_count(tmp_path):
    app, adm = _setup(tmp_path)
    for i, code in enumerate(("INFLU10", None, "OTHER10")):
        _order(app, f"k{i}@example.test", code)
    ev = _giveaway(adm, [])
    assert ev["codes"] == [] and ev["entries"] == 3


def test_codes_ignored_without_affiliate_module(tmp_path):
    app, adm = _setup(tmp_path, {**ALL_ON, "affiliate": False})
    _order(app, "a@example.test")
    ev = _giveaway(adm, ["INFLU10"])
    assert ev["codes"] == [] and ev["entries"] == 1
