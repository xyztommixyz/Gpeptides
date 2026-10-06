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
