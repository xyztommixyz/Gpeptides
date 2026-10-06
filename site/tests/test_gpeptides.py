"""Tests nur für GPeptides (Projektdaten in site/)."""
import json
import sys

import harness

sys.path.insert(0, str(harness.server_dir()))
import shopsite as shop_site  # noqa: E402


def test_load_gpeptides():
    s = shop_site.load(str(harness.site_dir()))
    assert s["name"] == "GPeptides" and s["id"] == "gpeptides"
    assert all(shop_site.feature(s, f) for f in shop_site.FEATURES)


def test_tokens_gpeptides():
    s = shop_site.load(str(harness.site_dir()))
    t = shop_site.tokens(s)
    assert t["SHOP_UPPER"] == "GPEPTIDES" and t["DOMAIN_UPPER"] == "GPEPTIDES.NET" and t["SPIN_CODE"] == "TOM10"


def test_product_block_matches_reference():
    """Die aus products.json erzeugte Produktliste entspricht exakt der früheren Liste in index.html."""
    ref = (harness.site_dir() / "golden" / "products_block.js").read_text(encoding="utf-8")
    s = shop_site.load(str(harness.site_dir()))
    core = (harness.ROOT / "core" / "public" / "index.html").read_text(encoding="utf-8")
    i = core.index("const P = [\n")
    j = core.index("\n", core.index("const BUNDLES=", i))
    p = json.loads((harness.site_dir() / "products.json").read_text(encoding="utf-8"))["products"]
    got = shop_site.apply(core[i:j], s, {"PRODUCT_ROWS": shop_site.product_rows(p),
                                         "PRODUCT_EXTRA": shop_site.product_extra(p),
                                         "PRODUCT_BUNDLES": shop_site.product_bundles(p)})
    assert got == ref


def test_case_large_slots_show_bac_water():
    """In den 10-ml-Mulden des Case-Konfigurators steht Bac-Wasser 10 ml, die Peptide (3-ml-Vials) in den kleinen Mulden."""
    import re
    core = (harness.ROOT / "core" / "public" / "index.html").read_text(encoding="utf-8")
    block = core[core.index("const INLAYS=["):core.index("const SLOT=")]
    found = 0
    for m in re.finditer(r'slots:(.*),\n\s*vials:(\[[^\]]*\])\}', block):
        slots, vials = m.group(1), json.loads(m.group(2))
        if "flatMap" in slots:  # nur 3-ml-Raster
            continue
        sizes = [int(s) for s in re.findall(r"\[-?\d+,-?\d+,(\d+)\]", slots)]
        for size, slug in zip(sizes, vials):
            if size == 10:
                found += 1
                assert slug == "bac-water", f"10-ml-Mulde zeigt {slug}"
    assert found == 6  # Duo 2 + Quad 4
