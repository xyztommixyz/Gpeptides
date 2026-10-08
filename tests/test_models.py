"""Eigene 3D-Modelle je Produkt: Auslieferung aus site/models/, Feld "model" in products.json und Seite, Umwandlung aus GLB."""
import base64
import importlib.util
import json
import struct
from array import array

import harness

MODEL = {"version": 1, "parts": [], "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}}


def _app(tmp_path, model_for="alpha"):
    site = harness.fixture_copy(tmp_path)
    (site / "models").mkdir()
    (site / "models" / "alpha.json").write_text(json.dumps(MODEL), encoding="utf-8")
    (site / "models" / "notiz.txt").write_text("intern", encoding="utf-8")
    (site / "admins.json").write_text('{"Geheim": "scrypt:GEHEIMER-HASH"}', encoding="utf-8")
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    for p in data["products"]:
        if p["slug"] == model_for:
            p["model"] = "/models/alpha.json"
        if p["slug"] == "beta":
            p["model"] = "https://fremd.example/x.json"  # fremde Domain: darf nicht in die Seite
    (site / "products.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return harness.load_app(tmp_path, {"SITE_DIR": str(site)}), site


def test_model_file_served_with_long_cache(tmp_path):
    app, _ = _app(tmp_path)
    r = app.app.test_client().get("/models/alpha.json")
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    assert json.loads(r.data) == MODEL
    assert "max-age=604800" in r.headers["Cache-Control"]


def test_model_paths_strict(tmp_path):
    app, _ = _app(tmp_path)
    c = app.app.test_client()
    for path in ("/models/../admins.json", "/models/%2e%2e/admins.json", "/models/..%2fadmins.json",
                 "/models/notiz.txt", "/models/fehlt.json", "/models/a/b.json", "/models/ALPHA.json",
                 "/models/../site.json"):
        r = c.get(path)
        assert r.status_code == 404, path
        assert b"GEHEIMER-HASH" not in r.data, path


def test_model_field_passed_to_products_json_and_page(tmp_path):
    app, _ = _app(tmp_path)
    c = app.app.test_client()
    prods = {p["slug"]: p for p in c.get("/products.json").get_json()["products"]}
    assert prods["alpha"]["model"] == "/models/alpha.json"
    page = c.get("/de/?full=1").get_data(as_text=True)
    assert '{slug:"alpha",' in page and 'model:"/models/alpha.json"' in page
    assert "fremd.example" not in page  # ungültige Adresse wird nicht übernommen
    assert page.count('model:"') == 1


def test_product_only_in_products_json(tmp_path):
    """Ein Produkt, das nach dem Erzeugen der Seite dazukommt (z. B. aus einem fremden Admin), steht in /products.json
    mit Modell; die Seite ergänzt es dann selbst (syncProducts)."""
    app, site = _app(tmp_path)
    c = app.app.test_client()
    assert c.get("/de/").status_code == 200  # Seite einmal erzeugt
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    data["products"].append({"slug": "gamma-neu", "name": "Gamma", "cls": "Testpeptid", "variants": [{"label": "5 mg", "price": 19.9}],
                             "purity": "≥98 %", "accent": "#22AA88", "tags": ["single"], "model": "/models/alpha.json"})
    (site / "products.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    prods = {p["slug"]: p for p in c.get("/products.json").get_json()["products"]}
    assert prods["gamma-neu"]["model"] == "/models/alpha.json"
    assert c.get("/de/gamma-neu/").status_code == 200


def test_product_rows_model():
    import sys
    sys.path.insert(0, str(harness.server_dir()))
    import shopsite
    base = {"slug": "x", "name": "X", "cls": "K", "variants": [{"label": "5 mg", "price": 1}]}
    assert "model:" not in shopsite.product_rows([base])
    assert 'model:"/models/x.json?v=2"' in shopsite.product_rows([{**base, "model": "/models/x.json?v=2"}])
    for bad in ("//fremd.example/x.json", "https://fremd.example/x.json", "/models/../site.json", "/models/x.js",
                "javascript:alert(1)", "/models/x.json\n", 5):
        assert "model:" not in shopsite.product_rows([{**base, "model": bad}]), bad


# ---------------------------------------------------------------- Umwandlung GLB -> Modell
def _converter():
    spec = importlib.util.spec_from_file_location("glb_to_model", harness.ROOT / "core" / "tools" / "glb_to_model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _glb(normals=True, node=None, **doc_over):
    """Kleine GLB-Datei: ein Quadrat (2 Dreiecke) mit einem Material."""
    pos = array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]).tobytes()
    nrm = array("f", [0, 0, 1] * 4).tobytes()
    idx = array("H", [0, 1, 2, 0, 2, 3]).tobytes() + b"\0\0"  # auf 4 Byte auffüllen
    binary = pos + nrm + idx
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 48}, {"buffer": 0, "byteOffset": 48, "byteLength": 48},
             {"buffer": 0, "byteOffset": 96, "byteLength": 12}]
    attrs = {"POSITION": 0}
    if normals:
        attrs["NORMAL"] = 1
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [node or {"mesh": 0}],
           "meshes": [{"primitives": [{"attributes": attrs, "indices": 2, "material": 0}]}],
           "materials": [{"name": "Lack", "pbrMetallicRoughness": {"baseColorFactor": [0.25, 0.5, 1.0, 1.0],
                                                                  "metallicFactor": 0.0, "roughnessFactor": 0.3}}],
           "buffers": [{"byteLength": len(binary)}], "bufferViews": views,
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
                         {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5123, "count": 6, "type": "SCALAR"}]}
    doc.update(doc_over)
    doc = {k: v for k, v in doc.items() if v is not None}
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _floats(b64):
    return array("f", base64.b64decode(b64)).tolist()


def test_glb_converter_roundtrip(tmp_path):
    conv = _converter()
    src = tmp_path / "quad.glb"
    src.write_bytes(_glb(node={"mesh": 0, "translation": [10, 0, 0], "scale": [2, 2, 2]}))
    out = tmp_path / "models" / "quad.json"
    assert conv.main([str(src), str(out)]) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    assert m["version"] == 1 and m["triangles"] == 2 and len(m["parts"]) == 1
    part = m["parts"][0]
    assert part["count"] == 6 and part["index32"] is False
    assert array("H", base64.b64decode(part["i"])).tolist() == [0, 1, 2, 0, 2, 3]
    assert _floats(part["p"]) == [10, 0, 0, 12, 0, 0, 12, 2, 0, 10, 2, 0]  # verschoben und skaliert
    assert _floats(part["n"]) == [0, 0, 1] * 4
    assert m["bounds"] == {"min": [10, 0, 0], "max": [12, 2, 0]}
    assert part["metal"] == 0 and part["rough"] == 0.3 and part["alpha"] == 1
    assert part["color"] == [round(0.25 ** (1 / 2.2), 4), round(0.5 ** (1 / 2.2), 4), 1.0]  # sRGB


def test_glb_converter_normals_and_z_up(tmp_path):
    conv = _converter()
    doc, bufs = conv.read_gltf(_write(tmp_path, _glb(normals=False)))
    m = conv.convert(doc, bufs)
    n = _floats(m["parts"][0]["n"])
    assert all(abs(a - b) < 1e-6 for a, b in zip(n, [0, 0, 1] * 4))  # berechnet, weich
    m = conv.convert(doc, bufs, z_up=True)  # Z oben -> Y oben: Normale (0,0,1) zeigt danach nach oben
    n = _floats(m["parts"][0]["n"])
    assert all(abs(a - b) < 1e-6 for a, b in zip(n, [0, 1, 0] * 4))
    m = conv.convert(doc, bufs, flat=True)
    assert len(_floats(m["parts"][0]["p"])) == 6 * 3  # flach: eigene Punkte je Dreieck


def _write(tmp_path, data):
    p = tmp_path / "m.glb"
    p.write_bytes(data)
    return str(p)


def test_glb_converter_without_scenes_uses_real_roots(tmp_path):
    """Ohne "scenes": Wurzel ist nur der Knoten, der nirgends Kind ist; das Kind bekommt die Verschiebung des Elternknotens."""
    conv = _converter()
    data = _glb(scene=None, scenes=None, nodes=[{"children": [1], "translation": [5, 0, 0]}, {"mesh": 0}])
    doc, bufs = conv.read_gltf(_write(tmp_path, data))
    m = conv.convert(doc, bufs)
    assert m["triangles"] == 2
    assert m["bounds"] == {"min": [5, 0, 0], "max": [6, 1, 0]}


# ---------------------------------------------------------------- ungültige Produkte, sichere Seite
def test_invalid_products_skipped_and_logged(tmp_path, capsys):
    site = harness.fixture_copy(tmp_path)
    data = json.loads((site / "products.json").read_text(encoding="utf-8"))
    base = {"name": "X", "cls": "K", "variants": [{"label": "5 mg", "price": 1}]}
    data["products"] += [{**base, "slug": "x" * 49}, {**base, "slug": "sieben", "variants": [{"label": "a", "price": 1}] * 7},
                         {**base, "slug": "preis-text", "variants": [{"label": "a", "price": "9"}]}, {**base, "slug": "Gross"},
                         {**base, "slug": "ohne-name", "name": ""}, "kein-objekt",
                         {**base, "slug": "skript", "name": "</script><script>alert(1)</script>"}]
    (site / "products.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    c = app.app.test_client()
    assert set(app.products()) == {"alpha", "beta", "test-water", "skript"}
    log = capsys.readouterr().out
    assert log.count("[PRODUCTS]") == 6 and "'sieben'" in log
    pub = [p["slug"] for p in c.get("/products.json").get_json()["products"]]
    assert pub == ["alpha", "beta", "test-water", "skript"]
    page = c.get("/de/?full=1").get_data(as_text=True)
    assert "</script><script>alert(1)" not in page  # "<" im Skript-Block maskiert
    assert r'\u003c/script>\u003cscript>alert(1)\u003c/script>' in page
    assert c.get("/de/sieben/").status_code == 404
