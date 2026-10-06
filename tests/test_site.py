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
