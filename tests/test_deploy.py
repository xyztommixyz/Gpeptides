"""Deploy: Preise kommen immer vom Server (core/deploy/keep_prices.py)."""
import importlib.util
import json

import harness

spec = importlib.util.spec_from_file_location("keep_prices", harness.ROOT / "core" / "deploy" / "keep_prices.py")
kp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kp)


def _data():
    return json.loads((harness.fixture_dir() / "products.json").read_text(encoding="utf-8"))


def test_server_prices_win_new_products_from_git():
    server, new = _data(), _data()
    server["products"][0]["variants"][0]["price"] = 18.5      # im Admin geändert
    server["cases"][0]["price"] = 25.0
    new["products"][0]["variants"][0]["price"] = 21.0         # in Git geändert -> wird ignoriert
    new["products"][0]["name"] = "Alpha neu"                  # Text aus Git bleibt
    new["products"][0]["variants"].append({"label": "50 mg", "price": 99.0})   # neue Variante: Preis aus Git
    new["products"].append({"slug": "neu", "name": "Neu", "variants": [{"label": "1 mg", "price": 5.0}]})
    notes = kp.keep_prices(server, new)
    assert len(notes) == 2
    assert new["products"][0]["variants"][0]["price"] == 18.5 and new["products"][0]["name"] == "Alpha neu"
    assert new["products"][0]["variants"][-1]["price"] == 99.0 and new["products"][-1]["variants"][0]["price"] == 5.0
    assert new["cases"][0]["price"] == 25.0


def test_main_without_server_file(tmp_path, capsys):
    new = tmp_path / "products.json"
    new.write_text(json.dumps(_data()), encoding="utf-8")
    before = new.read_text(encoding="utf-8")
    kp.main(str(tmp_path / "fehlt.json"), str(new))
    assert new.read_text(encoding="utf-8") == before
    assert "Preise aus Git" in capsys.readouterr().out
