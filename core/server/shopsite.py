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
