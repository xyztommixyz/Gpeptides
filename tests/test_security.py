"""Sicherheits-Regeln: Dateien aus site/, Dev-Modus, Client-IP und Login-Limit, 2FA-Pflicht, Team-Ansicht im Konto."""
import time

from werkzeug.security import generate_password_hash

import harness

H = {"X-GP": "1"}
ALL_ON = {"cases": True, "events": True, "affiliate": True, "discord": True, "spin": True}


def _app(tmp_path, env=None, features=None):
    site = harness.fixture_copy(tmp_path, features)
    (site / "admins.json").write_text('{"Geheim": "scrypt:GEHEIMER-HASH"}', encoding="utf-8")
    (site / "thumbs").mkdir()
    (site / "thumbs" / "alpha.webp").write_bytes(b"RIFF0000WEBP")
    (site / "thumbs" / "manifest.json").write_text("{}", encoding="utf-8")
    (site / "thumbs" / "notiz.txt").write_text("intern", encoding="utf-8")
    return harness.load_app(tmp_path, {"SITE_DIR": str(site), **(env or {})})


def _admin(app, user="Chef", pw="pw-123456"):
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO admin_users(username,pw_hash,created_at,role,email) VALUES(?,?,?,?,?)",
                 (user, generate_password_hash(pw), 1, "owner", "team@example.test"))
    conn.commit()
    conn.close()
    return user, pw


def _customer(c, email):
    r = c.post("/api/auth/request", json={"email": email, "lang": "de"}, headers=H)
    c.get(r.get_json()["devLink"].replace("http://localhost:8000", ""))


# ---------------------------------------------------------------- Dateien aus site/
def test_site_dir_only_serves_thumbs_and_products(tmp_path):
    c = _app(tmp_path).app.test_client()
    for path in ("/thumbs/../admins.json", "/thumbs/%2e%2e/admins.json", "/thumbs/..%2fadmins.json",
                 "/thumbs/../site.json", "/thumbs/notiz.txt", "/admins.json"):
        r = c.get(path)
        assert r.status_code == 404, path
        assert b"GEHEIMER-HASH" not in r.data, path
    assert c.get("/thumbs/alpha.webp").status_code == 200
    assert c.get("/thumbs/manifest.json").status_code == 200
    assert c.get("/products.json").status_code == 200


# ---------------------------------------------------------------- Dev-Modus
def test_dev_mode_never_with_https(tmp_path):
    app = _app(tmp_path, {"BASE_URL": "https://shop.example.test", "SMTP_HOST": ""})
    assert app.DEV_MODE is False
    r = app.app.test_client().post("/api/auth/request", json={"email": "kunde@example.test"}, headers=H)
    assert r.status_code == 200
    assert "devLink" not in r.get_json()


def test_dev_mode_locally_without_smtp(tmp_path):
    assert _app(tmp_path).DEV_MODE is True


# ---------------------------------------------------------------- Client-IP und Login-Limit
def test_admin_login_limit_not_bypassed_by_spoofed_forwarded_for(tmp_path):
    app = _app(tmp_path)
    user, _ = _admin(app)
    c = app.app.test_client()
    codes = []
    for i in range(9):
        # der Angreifer setzt die erste Adresse selbst, der Proxy hängt die echte (letzte) an
        hdr = {**H, "X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"}
        codes.append(c.post("/admin/api/login", json={"user": "Unbekannt" + str(i), "password": "falsch"}, headers=hdr).status_code)
    assert codes[:8] == [401] * 8
    assert codes[8] == 429


def test_admin_login_limit_shared_across_workers(tmp_path):
    """Fehlversuche liegen in der DB, nicht im Speicher eines Workers."""
    app = _app(tmp_path)
    _admin(app)
    for _ in range(10):
        app.app.test_client().post("/admin/api/login", json={"user": "Chef", "password": "falsch"}, headers=H)
    app._hits.clear()  # anderer Worker: leerer Speicher
    r = app.app.test_client().post("/admin/api/login", json={"user": "Chef", "password": "pw-123456"}, headers=H)
    assert r.status_code == 429


# ---------------------------------------------------------------- 2FA-Pflicht
def test_2fa_required_blocks_admin_until_set_up(tmp_path):
    app = _app(tmp_path, {"ADMIN_2FA_REQUIRED": "1"})
    user, pw = _admin(app)
    c = app.app.test_client()
    assert c.post("/admin/api/login", json={"user": user, "password": pw}, headers=H).status_code == 200
    me = c.get("/admin/api/me").get_json()
    assert me["totp_required"] is True and me["totp"] is False
    r = c.get("/admin/api/overview")
    assert r.status_code == 403 and r.get_json()["error"] == "2fa_setup_required"
    assert c.post("/admin/api/affiliates", json={"code": "HACK90", "discount": 90}, headers=H).status_code == 403

    secret = c.post("/admin/api/2fa/setup", headers=H).get_json()["secret"].replace(" ", "")
    code = app.totp_at(secret, int(time.time() // 30))
    assert c.post("/admin/api/2fa/enable", json={"code": code}, headers=H).status_code == 200
    assert c.get("/admin/api/overview").status_code == 200

    r = c.post("/admin/api/2fa/disable", json={"password": pw, "code": code}, headers=H)
    assert r.status_code == 403 and r.get_json()["error"] == "2fa_required"


def test_2fa_required_by_default_only_with_https(tmp_path):
    assert _app(tmp_path).ADMIN_2FA_REQUIRED is False
    assert _app(tmp_path / "b", {"BASE_URL": "https://shop.example.test"}).ADMIN_2FA_REQUIRED is True


# ---------------------------------------------------------------- Team-Ansicht im Konto
def test_team_can_only_create_new_codes_within_limit(tmp_path):
    app = _app(tmp_path, {"ADMIN_EMAILS": "team@example.test"}, ALL_ON)
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES('PART10','Partner',NULL,10,10,1,1)")
    conn.commit()
    conn.close()
    c = app.app.test_client()
    _customer(c, "team@example.test")

    assert c.get("/api/team/affiliates").get_json()["max"] == 20
    r = c.post("/api/team/affiliates", json={"code": "NEU90", "discount": 90, "commission": 10}, headers=H)
    assert r.status_code == 400 and r.get_json()["error"] == "too_high"
    r = c.post("/api/team/affiliates", json={"code": "NEU15", "discount": 15, "commission": 10}, headers=H)
    assert r.status_code == 200
    # bestehende Codes nicht überschreibbar, auch ohne create_only vom Client
    r = c.post("/api/team/affiliates", json={"code": "PART10", "discount": 5, "commission": 5, "create_only": False}, headers=H)
    assert r.status_code == 409

    conn = app.sqlite3.connect(app.DB_PATH)
    assert conn.execute("SELECT discount_pct FROM affiliates WHERE code='PART10'").fetchone()[0] == 10
    conn.close()


def test_team_route_forbidden_for_normal_customers(tmp_path):
    app = _app(tmp_path, {"ADMIN_EMAILS": "team@example.test"}, ALL_ON)
    c = app.app.test_client()
    _customer(c, "kunde@example.test")
    assert c.post("/api/team/affiliates", json={"code": "NEU10", "discount": 10}, headers=H).status_code == 403


def test_admin_name_lock_does_not_lock_out_clean_ips(tmp_path):
    """10 Fehlversuche von verschiedenen IPs auf einen Namen sperren nicht den echten Admin von seiner eigenen IP aus."""
    app = _app(tmp_path)
    user, pw = _admin(app)
    c = app.app.test_client()
    for i in range(10):
        c.post("/admin/api/login", json={"user": user, "password": "falsch"}, headers={**H, "X-Forwarded-For": f"198.51.100.{i}"})
    r = c.post("/admin/api/login", json={"user": user, "password": "falsch"}, headers={**H, "X-Forwarded-For": "198.51.100.1"})
    assert r.status_code == 429  # IP mit eigenen Fehlversuchen bleibt gesperrt
    r = c.post("/admin/api/login", json={"user": user, "password": pw}, headers={**H, "X-Forwarded-For": "192.0.2.50"})
    assert r.status_code == 200


def test_token_api_off_when_2fa_required(tmp_path):
    app = _app(tmp_path, {"ADMIN_2FA_REQUIRED": "1", "ADMIN_TOKEN": "t" * 40}, ALL_ON)
    c = app.app.test_client()
    auth = {"Authorization": "Bearer " + "t" * 40}
    assert c.post("/api/admin/affiliates", json={"code": "TOKEN90", "discount": 90}, headers=auth).status_code == 401
    assert c.post("/api/admin/orders/X-1", json={"status": "paid"}, headers=auth).status_code == 401


def test_token_api_uses_affiliate_limits(tmp_path):
    app = _app(tmp_path, {"ADMIN_TOKEN": "t" * 40}, ALL_ON)
    r = app.app.test_client().post("/api/admin/affiliates", json={"code": "TOKEN150", "discount": 150, "commission": -5},
                                   headers={"Authorization": "Bearer " + "t" * 40})
    assert r.status_code == 200
    conn = app.sqlite3.connect(app.DB_PATH)
    assert conn.execute("SELECT discount_pct, commission_pct FROM affiliates WHERE code='TOKEN150'").fetchone() == (90.0, 0.0)
    conn.close()
