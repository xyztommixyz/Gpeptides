"""Läuft das Projekt in site/? (Kern-Test, unabhängig vom Projekt)"""
import json

import harness


def test_project_shop_runs(tmp_path):
    app = harness.load_app(tmp_path)
    s = json.loads((harness.site_dir() / "site.json").read_text(encoding="utf-8"))
    first = json.loads((harness.site_dir() / "products.json").read_text(encoding="utf-8"))["products"][0]["slug"]
    c = app.app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    assert s["name"] in page and "@@" not in page
    assert c.get(f"/de/{first}/").status_code == 200
    q = c.post("/api/quote", json={"items": [{"slug": first, "vi": 0, "qty": 1}], "country": "DE"}).get_json()
    assert q["lines"] and q["total"] > 0
