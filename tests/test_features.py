"""Modul-Schalter (site.json "features") – laufen gegen den neutralen Test-Shop (tests/fixture_site)."""
import re
import time

import harness

ALL_ON = {"cases": True, "events": True, "affiliate": True, "discord": True, "spin": True}
ALL_OFF = {k: False for k in ALL_ON}
ITEM = {"slug": "alpha", "vi": 0, "qty": 1}  # 20,00 €


def _app(tmp_path, features):
    return harness.load_app(tmp_path, {"SITE_DIR": str(harness.fixture_copy(tmp_path, features))})


def _code(app, code="PART10"):
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,'Partner',NULL,10,10,1,1)", (code,))
    conn.commit()
    conn.close()


def _running_sale(app):
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO events(kind,title,starts_at,ends_at,published,pct,created_at) VALUES('sale','Test-Sale',?,?,1,20,?)",
                 (int(time.time()) - 60, int(time.time()) + 3600, int(time.time())))
    conn.commit()
    conn.close()


def test_cases_on_routes(tmp_path):
    c = _app(tmp_path, ALL_ON).app.test_client()
    assert c.get("/de/cases/").status_code == 200
    q = c.post("/api/quote", json={"items": [harness.CASE_ITEM], "country": "DE"}).get_json()
    assert len(q["lines"]) == 1


def test_cases_off_routes(tmp_path):
    c = _app(tmp_path, ALL_OFF).app.test_client()
    assert c.get("/de/cases/").status_code == 404
    assert c.get("/case-model.json").status_code == 404
    assert 'class="no-cases' in c.get("/de/").get_data(as_text=True)


def test_cases_off_rejects_case_items(tmp_path):
    c = _app(tmp_path, ALL_OFF).app.test_client()
    q = c.post("/api/quote", json={"items": [harness.CASE_ITEM], "country": "DE"}).get_json()
    assert q["lines"] == []


def test_affiliate_on(tmp_path):
    app = _app(tmp_path, ALL_ON)
    _code(app)
    c = app.app.test_client()
    assert c.post("/api/code", json={"code": "PART10"}).get_json()["valid"] is True


def test_affiliate_off(tmp_path):
    app = _app(tmp_path, ALL_OFF)
    _code(app)
    c = app.app.test_client()
    assert c.post("/api/code", json={"code": "PART10"}).get_json()["valid"] is False
    q = c.post("/api/quote", json={"items": [ITEM], "country": "DE", "code": "PART10"}).get_json()
    assert q["discount"] == 0
    assert c.get("/api/partner").status_code == 404


def test_spin_code_only_with_spin(tmp_path):
    on = _app(tmp_path / "on", ALL_ON).app.test_client()
    assert on.post("/api/code", json={"code": "SPIN10"}).get_json()["valid"] is True
    off = _app(tmp_path / "off", {**ALL_ON, "spin": False}).app.test_client()
    assert off.post("/api/code", json={"code": "SPIN10"}).get_json()["valid"] is False


def test_events_on_shows_sale(tmp_path):
    app = _app(tmp_path, ALL_ON)
    _running_sale(app)
    assert len(app.app.test_client().get("/api/events").get_json()["events"]) == 1


def test_events_off(tmp_path):
    app = _app(tmp_path, ALL_OFF)
    _running_sale(app)
    c = app.app.test_client()
    assert c.get("/api/events").get_json()["events"] == []
    q = c.post("/api/quote", json={"items": [ITEM], "country": "DE"}).get_json()
    assert q["discount"] == 0 and q["subtotal"] == 2000


def test_all_on_has_no_classes(tmp_path):
    assert _app(tmp_path, ALL_ON).feature_off_classes() == ""


def test_frontend_hides_switched_off_modules(tmp_path):
    c = _app(tmp_path, ALL_OFF).app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    assets = "".join(c.get(m.group(0)).get_data(as_text=True)
                     for m in re.finditer(r"/assets/app\.[0-9a-f]{12}\.(js|css)", page))
    for sel in (".no-cases [data-cases]", ".no-affiliate .code", ".no-discord .dc-btn"):
        assert sel in assets
    assert 'classList.contains("no-spin")' in assets
    admin = c.get("/admin/").get_data(as_text=True)
    assert 'class="no-cases no-events no-affiliate no-discord no-spin"' in admin
    assert '.no-events [data-view="events"]' in admin


def test_partner_short_name_from_site(tmp_path):
    c = _app(tmp_path, ALL_ON).app.test_client()
    page = c.get("/de/?full=1").get_data(as_text=True)
    admin = c.get("/admin/").get_data(as_text=True)
    assert "× Partner" in page and "Cases · Partner" in admin
    for body in (page, admin):
        assert not re.search(r"\bNexo\b", body)
