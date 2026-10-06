"""Projektdaten aus site/: site.json (Marke, Domain, Schalter), texts.json, case.json, admins.json.
Der Kern enthält Platzhalter @@NAME@@, die hier ersetzt werden."""
import json
import os
import re

TOKEN_RE = re.compile(r"@@([A-Z_]+)@@")
FEATURES = ("cases", "events", "affiliate", "discord", "spin")


def load(site_dir):
    with open(os.path.join(site_dir, "site.json"), encoding="utf-8") as fh:
        s = json.load(fh)
    s.setdefault("cookiePrefix", s["id"][:8])
    s.setdefault("orderPrefix", s["short"])
    s.setdefault("skuPrefix", s["short"])
    s.setdefault("brandColor", "#2A41E8")
    s.setdefault("mailFrom", f"{s['name']} <no-reply@{s['domain']}>")
    s.setdefault("imageBase", f"https://{s['domain']}/product_images/")
    s.setdefault("certificateUrl", "")
    s.setdefault("legalBase", f"https://{s['domain']}/")
    s.setdefault("discordUrl", "")
    s.setdefault("spinCode", "")
    s.setdefault("cspImgHosts", [])
    s["features"] = {f: bool((s.get("features") or {}).get(f, False)) for f in FEATURES}
    s.setdefault("cases", {})
    s["cases"].setdefault("partner", "")
    s["cases"].setdefault("partnerShort", s["cases"]["partner"])
    s["cases"].setdefault("partnerUrl", "")
    s["dir"] = site_dir
    return s


def tokens(s):
    return {
        "SHOP": s["name"], "SHOP_UPPER": s["name"].upper(), "SHORT": s["short"],
        "DOMAIN": s["domain"], "DOMAIN_UPPER": s["domain"].upper(),
        "SKU_PREFIX": s["skuPrefix"], "IMAGE_BASE": s["imageBase"], "CERT_URL": s["certificateUrl"],
        "LEGAL_BASE": s["legalBase"], "DISCORD": s["discordUrl"], "SPIN_CODE": s["spinCode"],
        "PARTNER": s["cases"]["partner"], "PARTNER_SHORT": s["cases"]["partnerShort"],
        "PARTNER_URL": s["cases"]["partnerUrl"],
    }


def apply(text, s, extra=None):
    t = tokens(s)
    if extra:
        t.update(extra)
    return TOKEN_RE.sub(lambda m: t[m.group(1)], text)


def feature(s, name):
    return bool(s["features"].get(name))


def admins(site_dir):
    path = os.path.join(site_dir, "admins.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {n: {"hash": v["hash"], "role": v.get("role", "owner")}
            for n, v in data.items() if not n.startswith("_") and isinstance(v, dict) and v.get("hash")}


STATUS_SHORT = {"preorder": "pre", "out_of_stock": "oos"}


def _js(v):
    return json.dumps(v, ensure_ascii=False)


def _num(x):
    return f"{x:g}"


def product_rows(products):
    rows = []
    for p in products:
        s = f'{{slug:{_js(p["slug"])},name:{_js(p["name"])}'
        if p.get("short"):
            s += f',short:{_js(p["short"])}'
        s += f',cls:{_js(p["cls"])},v:[' + ",".join(f'[{_js(v["label"])},{_num(v["price"])}]' for v in p["variants"]) + "]"
        s += f',pur:{_js(p.get("purity", ""))},cap:{_js(p.get("accent", ""))},tags:[' + ",".join(_js(t) for t in p.get("tags", [])) + "]"
        if p.get("liquid"):
            s += ",liquid:true"
        if p.get("status") in STATUS_SHORT:
            s += f',st:{_js(STATUS_SHORT[p["status"]])}'
        rows.append(" " + s + "}")
    return ",\n".join(rows) + ","


IMG_RE = re.compile(r"prod_(\d+)_([0-9a-f]+)\.webp$")


def product_extra(products):
    found = []
    for p in products:
        m = IMG_RE.search(p.get("image", ""))
        if m:
            found.append((int(m.group(1)), p["slug"], m.group(2)))
    return "{" + ",".join(f"{_js(slug)}:[{n},{_js(h)}]" for n, slug, h in sorted(found)) + "}"


def product_bundles(products):
    return "{" + ",".join(f'{_js(p["slug"])}:[' + ",".join(_js(b) for b in p["bundle"]) + "]"
                          for p in products if p.get("bundle")) + "}"


def texts(site_dir):
    """Eigene Texte des Projekts: {"ui"|"server"|"res": {lang: {key: text}}}. Fehlt/ungültig -> {}."""
    path = os.path.join(site_dir, "texts.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except ValueError as exc:
        print(f"[TEXTS] site/texts.json ungültig, Kern-Texte werden genutzt: {exc}", flush=True)
        return {}


def merge_texts(i18n_json, over):
    """Überschreibt Einträge im i18n-JSON der Seite mit den Projekttexten."""
    data = json.loads(i18n_json)
    for part in ("ui", "server", "res"):
        for lang, entries in (over.get(part) or {}).items():
            if isinstance(entries, dict):
                data.setdefault(part, {}).setdefault(lang, {}).update(entries)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
