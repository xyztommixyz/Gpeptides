import json

import harness

ALL_OFF = {"cases": False, "events": False, "affiliate": False, "discord": False, "spin": False}


def _site(tmp_path, features):
    site = tmp_path / "site"
    site.mkdir()
    for f in ("products.json", "case.json"):
        (site / f).write_text((harness.site_dir() / f).read_text(encoding="utf-8"), encoding="utf-8")
    s = json.loads((harness.site_dir() / "site.json").read_text(encoding="utf-8"))
    s["features"] = features
    (site / "site.json").write_text(json.dumps(s), encoding="utf-8")
    return site


def test_cases_off_routes(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    c = app.app.test_client()
    assert c.get("/de/cases/").status_code == 404
    assert c.get("/case-model.json").status_code == 404
    assert 'class="no-cases' in c.get("/de/").get_data(as_text=True)


def test_cases_off_rejects_case_items(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    q = app.app.test_client().post("/api/quote", json={"items": [harness.CASE_ITEM], "country": "DE"}).get_json()
    assert q["lines"] == []


def test_affiliate_off(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    c = app.app.test_client()
    assert c.post("/api/code", json={"code": "TOM10"}).get_json()["valid"] is False
    q = c.post("/api/quote", json={"items": [{"slug": "bpc-157", "vi": 0, "qty": 1}], "country": "DE", "code": "TOM10"}).get_json()
    assert q["discount"] == 0


def _running_sale(app):
    import time
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO events(kind,title,starts_at,ends_at,published,pct,created_at) VALUES('sale','Test-Sale',?,?,1,20,?)",
                 (int(time.time()) - 60, int(time.time()) + 3600, int(time.time())))
    conn.commit()
    conn.close()


def test_events_on_shows_sale(tmp_path):
    app = harness.load_app(tmp_path)
    _running_sale(app)
    assert len(app.app.test_client().get("/api/events").get_json()["events"]) == 1


def test_events_off(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    _running_sale(app)
    c = app.app.test_client()
    assert c.get("/api/events").get_json()["events"] == []
    q = c.post("/api/quote", json={"items": [{"slug": "bpc-157", "vi": 0, "qty": 1}], "country": "DE"}).get_json()
    assert q["discount"] == 0 and q["subtotal"] == 3290


def test_all_on_has_no_classes(tmp_path):
    app = harness.load_app(tmp_path)
    assert app.feature_off_classes() == ""


def test_frontend_hides_switched_off_modules(tmp_path):
    import re
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    c = app.app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    assets = "".join(c.get(m.group(0)).get_data(as_text=True)
                     for m in re.finditer(r"/assets/app\.[0-9a-f]{12}\.(js|css)", page))
    for sel in (".no-cases [data-cases]", ".no-affiliate .code", ".no-discord .dc-btn"):
        assert sel in assets
    assert 'classList.contains("no-spin")' in assets
    admin = c.get("/admin/").get_data(as_text=True)
    assert 'class="no-cases no-events no-affiliate no-discord no-spin"' in admin
    assert '.no-events [data-view="events"]' in admin
