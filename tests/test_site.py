import json
import sys

import harness
import pytest

sys.path.insert(0, str(harness.server_dir()))
import shopsite as shop_site  # noqa: E402


def test_load_gpeptides():
    s = shop_site.load(str(harness.site_dir()))
    assert s["name"] == "GPeptides"
    assert s["id"] == "gpeptides"
    assert shop_site.feature(s, "cases") is True


def test_tokens_and_apply():
    s = shop_site.load(str(harness.site_dir()))
    t = shop_site.tokens(s)
    assert t["SHOP_UPPER"] == "GPEPTIDES" and t["DOMAIN_UPPER"] == "GPEPTIDES.NET"
    assert shop_site.apply("© @@SHOP@@ · name@@@DOMAIN@@", s) == "© GPeptides · name@gpeptides.net"
    with pytest.raises(KeyError):
        shop_site.apply("@@UNBEKANNT@@", s)


def test_defaults_for_minimal_site(tmp_path):
    (tmp_path / "site.json").write_text(json.dumps({"id": "demo", "name": "Demo Labs", "short": "DL",
                                                    "domain": "demo.example"}), encoding="utf-8")
    s = shop_site.load(str(tmp_path))
    assert s["cookiePrefix"] == "demo" and s["orderPrefix"] == "DL"
    assert shop_site.feature(s, "cases") is False
    assert s["mailFrom"] == "Demo Labs <no-reply@demo.example>"


def test_admins_missing_file(tmp_path):
    assert shop_site.admins(str(tmp_path)) == {}


def test_admins_file(tmp_path):
    (tmp_path / "admins.json").write_text('{"Anna": {"hash": "scrypt:x", "role": "owner"}}', encoding="utf-8")
    assert shop_site.admins(str(tmp_path)) == {"Anna": {"hash": "scrypt:x", "role": "owner"}}


def test_no_admins_file_starts(tmp_path, capsys):
    site = tmp_path / "site"
    site.mkdir()
    for f in ("site.json", "products.json"):
        (site / f).write_text((harness.site_dir() / f).read_text(encoding="utf-8"), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    assert app.app.test_client().get("/robots.txt").status_code == 200
    assert "admins.json" in capsys.readouterr().out


def test_cli_hash_password(tmp_path, monkeypatch, capsys):
    app = harness.load_app(tmp_path)
    import getpass
    from werkzeug.security import check_password_hash
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "geheim-12345")
    app.cli(["hash-password"])
    h = capsys.readouterr().out.strip().splitlines()[-1]
    assert check_password_hash(h, "geheim-12345")


def _products():
    return json.loads((harness.site_dir() / "products.json").read_text(encoding="utf-8"))["products"]


def test_product_block_matches_reference():
    ref = (harness.site_dir() / "golden" / "products_block.js").read_text(encoding="utf-8")
    s = shop_site.load(str(harness.site_dir()))
    core = (harness.ROOT / "core" / "public" / "index.html").read_text(encoding="utf-8")
    i = core.index("const P = [\n"); j = core.index("\n", core.index("const BUNDLES=", i))
    p = _products()
    got = shop_site.apply(core[i:j], s, {"PRODUCT_ROWS": shop_site.product_rows(p),
                                         "PRODUCT_EXTRA": shop_site.product_extra(p),
                                         "PRODUCT_BUNDLES": shop_site.product_bundles(p)})
    assert got == ref


def test_no_placeholder_leaks(tmp_path):
    app = harness.load_app(tmp_path)
    c = app.app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    bodies = [page, c.get("/de/?full=1").get_data(as_text=True), c.get("/admin/").get_data(as_text=True),
              c.get("/i18n/en.json").get_data(as_text=True)]
    import re
    for m in re.finditer(r"/assets/app\.[0-9a-f]{12}\.(js|css)", page):
        bodies.append(c.get(m.group(0)).get_data(as_text=True))
    bodies.append(app.tr("en", "home_title"))
    for b in bodies:
        assert "@@" not in b


def _site_copy(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    for f in ("site.json", "products.json", "case.json"):
        (site / f).write_text((harness.site_dir() / f).read_text(encoding="utf-8"), encoding="utf-8")
    return site


def test_texts_override(tmp_path):
    site = _site_copy(tmp_path)
    (site / "texts.json").write_text(json.dumps({"server": {"de": {"home_title": "Mein Titel"}}}), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    assert "<title>Mein Titel</title>" in app.app.test_client().get("/de/").get_data(as_text=True)


def test_broken_texts_json_ignored(tmp_path, capsys):
    site = _site_copy(tmp_path)
    (site / "texts.json").write_text("{kaputt", encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    assert app.app.test_client().get("/de/").status_code == 200
    assert "[TEXTS]" in capsys.readouterr().out


def test_invoice_uses_site_name(tmp_path):
    site = _site_copy(tmp_path)
    s = json.loads((site / "site.json").read_text(encoding="utf-8"))
    s["name"] = "Demo Labs"
    (site / "site.json").write_text(json.dumps(s), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    from werkzeug.security import generate_password_hash
    conn = app.sqlite3.connect(app.DB_PATH)
    conn.execute("INSERT INTO admin_users(username,pw_hash,created_at,role) VALUES('T',?,1,'owner')", (generate_password_hash("pw-1234567890"),))
    conn.commit()
    conn.close()
    c = app.app.test_client()
    o = c.post("/api/orders", headers=harness.H, json={"items": [{"slug": "bpc-157", "vi": 0, "qty": 1}], "address": harness.ADDR_DE,
                                                        "method": "prepayment", "acceptTerms": True, "acceptResearch": True}).get_json()
    c.post("/admin/api/login", json={"user": "T", "password": "pw-1234567890"}, headers=harness.H)
    c.post(f"/admin/api/orders/{o['order']}/status", json={"status": "paid"}, headers=harness.H)
    pdf = harness._pdf_text(c.get(f"/admin/api/orders/{o['order']}/invoice.pdf").get_data())
    assert "Demo Labs" in pdf and "GPeptides" not in pdf
