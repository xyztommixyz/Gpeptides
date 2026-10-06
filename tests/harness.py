"""Golden-Master für den Shop: ruft alle wichtigen Seiten und Abläufe über den Flask-Test-Client auf,
normalisiert Zufallswerte (Bestellnummern, Tokens, Zeitstempel, Asset-Prüfsummen) und liefert pro Aufruf
Status, wichtige Header und eine Prüfsumme des Inhalts."""
import hashlib
import importlib.util
import json
import re
import sys
import threading
import zlib
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PW = "test-pass-123"


def server_dir():
    for c in (ROOT / "core" / "server", ROOT / "server"):
        if (c / "app.py").exists():
            return c
    raise FileNotFoundError("app.py nicht gefunden")


def site_dir():
    return ROOT / "site"


_counter = [0]


def load_app(tmp, env=None):
    import os
    tmp = Path(tmp)
    base = {"DB_PATH": str(tmp / "t.db"), "BACKUP_EVERY_HOURS": "0", "BACKUP_DIR": str(tmp / "bk"),
            "SMTP_HOST": "", "BASE_URL": "http://localhost:8000", "STRIPE_SECRET_KEY": "",
            "ORDER_NOTIFY": "notify@example.test", "NEXO_NOTIFY": "nexo@example.test"}
    base.update(env or {})
    for k in ("MAIL_FROM", "DISCORD_URL", "SHOP_LEGAL_NAME", "SHOP_EMAIL", "FREE_SHIPPING_FROM", "SITE_DIR", "PUBLIC_DIR"):
        if k not in base:
            os.environ.pop(k, None)
    os.environ.update(base)
    sd = server_dir()
    if str(sd) not in sys.path:
        sys.path.insert(0, str(sd))
    for name in ("shopsite", "pdfdoc", "qrcodegen"):
        sys.modules.pop(name, None)
    _counter[0] += 1
    spec = importlib.util.spec_from_file_location(f"shop_app_{_counter[0]}", sd / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ Normalisierung
YEAR_NO = re.compile(r"\b(RE|ST|GS)-20\d{2}-")
ORDER_RE = re.compile(r"\b[A-Z]{1,6}-\d{6}-[A-Z0-9]{5}\b")
PATTERNS = [
    (re.compile(r"token=[A-Za-z0-9_-]{20,}"), "token=TOKEN"),
    (re.compile(r"app\.[0-9a-f]{12}\.(js|css)"), r"app.HASH.\1"),
    (re.compile(r"\b1[6-9]\d{8}\b"), "TS"),
    (re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"), "DATE"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?\b"), "DATE"),
    (re.compile(r"\b\d{2}:\d{2}(:\d{2})?\b"), "TIME"),
    (re.compile(r"\d{2}(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{4}"), "DATE"),
]


def normalize(text, ids):
    def oid(m):
        return ids.setdefault(m.group(0), f"ORDER{len(ids) + 1}")
    text = ORDER_RE.sub(oid, text)
    text = YEAR_NO.sub(lambda m: m.group(1) + "-YYYY-", text)
    for rx, rep in PATTERNS:
        text = rx.sub(rep, text)
    return text


def _pdf_text(data):
    def unpack(m):
        try:
            return b"stream\n" + zlib.decompress(m.group(1)) + b"\nendstream"
        except zlib.error:
            return m.group(0)
    text = re.sub(rb"stream\r?\n(.*?)\r?\nendstream", unpack, data, flags=re.S).decode("latin-1")
    text = re.sub(r"/Length \d+", "/Length N", text)
    text = re.sub(r"\d{10} 00000 n", "OFFSET 00000 n", text)
    text = re.sub(r"startxref\s+\d+", "startxref N", text)
    text = re.sub(r"/(CreationDate|ModDate) *\([^)]*\)", "/DATEFIELD", text)
    return re.sub(r"/ID *\[[^\]]*\]", "/ID", text)


PDF_POS = re.compile(r"[\d.]+ [\d.]+ Td \(([^)]*(?:ORDER\d+|DATE|TIME|TS)[^)]*)\)")


def _pdf_norm(data, ids):
    """PDF-Text normalisiert; Position von Texten mit Zufallswerten (rechtsbündig, Breite variiert) entfernt."""
    return PDF_POS.sub(r"POS Td (\1)", normalize(_pdf_text(data), ids))


def _record(resp, ids):
    ctype = resp.headers.get("Content-Type", "")
    data = resp.get_data()
    if "pdf" in ctype:
        body = _pdf_norm(data, ids)
    elif ctype.startswith(("text/", "application/json", "application/javascript", "application/xml")):
        body = data.decode("utf-8")
    else:
        body = None
    if body is not None:
        body = normalize(body, ids)
        raw = body.encode("utf-8")
    else:
        raw = data
    headers = {}
    for h in ("Location", "Cache-Control", "Content-Security-Policy", "Content-Disposition"):
        if resp.headers.get(h):
            headers[h] = normalize(resp.headers[h], ids)
    cookies = sorted(c.split("=", 1)[0] for c in resp.headers.getlist("Set-Cookie"))
    if cookies:
        headers["Set-Cookie"] = cookies
    return {"status": resp.status_code, "type": ctype, "headers": headers,
            "body_sha": hashlib.sha256(raw).hexdigest(), "body_len": len(raw), "_body": body if body is not None else ""}


class _SyncThread:
    """Ersetzt threading.Thread während der Aufzeichnung: Mails werden sofort und in fester Reihenfolge erzeugt."""
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.t, self.a, self.k = target, args, kwargs or {}

    def start(self):
        self.t(*self.a, **self.k)


CASE_ITEM = {"slug": "nexo-case", "vi": 0, "qty": 1,
             "cfg": {"lid": "#1c1d20", "base": "#2c2e33", "inlay": "#e8e7e3", "layout": "daily"}}
ADDR_DE = {"name": "Erika Muster", "company": "", "street": "Teststraße 1", "zip": "10115", "city": "Berlin",
           "country": "DE", "email": "kunde@example.test"}
ADDR_AT = {**ADDR_DE, "zip": "1010", "city": "Wien", "country": "AT", "email": "gast@example.test"}
H = {"X-GP": "1"}

PAGES = ["/", "/de/", "/en/", "/pl/", "/de/bpc-157/", "/en/glow-stack/", "/de/cases/", "/de/rechner/",
         "/de/gibt-es-nicht/", "/sitemap.xml", "/robots.txt", "/products.json", "/de/?full=1", "/i18n/en.json",
         "/case-model.json", "/admin/", "/api/config", "/api/events", "/api/stock", "/thumbs/manifest.json"]


def run(tmp, env=None):
    app = load_app(tmp, env)
    ids, rec, mails = {}, {}, []

    def capture(to_addr, subject, text, html, dev_note="", attachments=None):
        mails.append({"to": to_addr, "subject": subject, "text": text, "html": html,
                      "att": [(a[0], hashlib.sha256(_pdf_norm(a[1], ids).encode()).hexdigest()) for a in attachments or []]})

    app.send_mail = capture
    orig_thread = threading.Thread
    threading.Thread = _SyncThread
    try:
        conn = app.sqlite3.connect(app.DB_PATH)
        conn.execute("INSERT OR REPLACE INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?)",
                     ("Tester", generate_password_hash(ADMIN_PW), 1, "owner"))
        conn.execute("INSERT OR REPLACE INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?)",
                     ("NexoTest", generate_password_hash(ADMIN_PW), 1, "nexo"))
        conn.commit()
        conn.close()

        guest = app.app.test_client()
        for p in PAGES:
            rec["GET " + p] = _record(guest.get(p), ids)
        page = guest.get("/de/").get_data(as_text=True)
        for kind in ("js", "css"):
            m = re.search(r"/assets/app\.[0-9a-f]{12}\." + kind, page)
            rec["asset " + kind] = _record(guest.get(m.group(0)), ids) if m else {"missing": True}

        user = app.app.test_client()
        r = user.post("/api/auth/request", json={"email": "kunde@example.test", "lang": "de"}, headers=H)
        rec["auth request"] = _record(r, ids)
        link = r.get_json()["devLink"].replace("http://localhost:8000", "")
        rec["auth verify"] = _record(user.get(link), ids)
        rec["me"] = _record(user.get("/api/me"), ids)
        rec["cart put"] = _record(user.put("/api/cart", json={"items": [{"slug": "bpc-157", "vi": 0, "qty": 2}]}, headers=H), ids)
        rec["cart get"] = _record(user.get("/api/cart"), ids)

        base = [{"slug": "bpc-157", "vi": 0, "qty": 2}, {"slug": "glp-3", "vi": 1, "qty": 1}]
        for name, body in (("quote de", {"items": base, "country": "DE"}),
                           ("quote code", {"items": base, "country": "DE", "code": "TOM10"}),
                           ("quote express", {"items": base, "country": "DE", "express": True}),
                           ("quote at", {"items": base, "country": "AT"}),
                           ("quote case", {"items": base + [CASE_ITEM], "country": "DE"})):
            rec[name] = _record(guest.post("/api/quote", json=body), ids)
        rec["code check"] = _record(guest.post("/api/code", json={"code": "TOM10"}), ids)

        o1 = user.post("/api/orders", headers=H, json={"items": base + [CASE_ITEM], "address": ADDR_DE, "code": "TOM10",
                                                       "method": "prepayment", "acceptTerms": True, "acceptResearch": True, "lang": "de"})
        rec["order 1"] = _record(o1, ids)
        o2 = guest.post("/api/orders", headers=H, json={"items": base, "address": ADDR_AT, "express": True,
                                                        "method": "prepayment", "acceptTerms": True, "acceptResearch": True, "lang": "en"})
        rec["order 2"] = _record(o2, ids)
        oid1 = o1.get_json()["order"]

        adm = app.app.test_client()
        rec["admin login"] = _record(adm.post("/admin/api/login", json={"user": "Tester", "password": ADMIN_PW}, headers=H), ids)
        rec["admin orders"] = _record(adm.get("/admin/api/orders"), ids)
        rec["admin order 1"] = _record(adm.get(f"/admin/api/orders/{oid1}"), ids)
        rec["admin paid"] = _record(adm.post(f"/admin/api/orders/{oid1}/status", json={"status": "paid"}, headers=H), ids)
        rec["admin invoice"] = _record(adm.get(f"/admin/api/orders/{oid1}/invoice.pdf"), ids)
        rec["admin csv"] = _record(adm.get("/admin/api/orders.csv"), ids)
        rec["customer orders"] = _record(user.get("/api/orders"), ids)
        rec["customer invoice"] = _record(user.get(f"/api/orders/{oid1}/invoice.pdf"), ids)

        nx = app.app.test_client()
        rec["nexo login"] = _record(nx.post("/admin/api/login", json={"user": "NexoTest", "password": ADMIN_PW}, headers=H), ids)
        rec["nexo orders"] = _record(nx.get("/admin/api/nexo/orders"), ids)
        rec["nexo forbidden"] = _record(nx.get("/admin/api/orders"), ids)

        for i, m in enumerate(mails):
            body = normalize(json.dumps(m, ensure_ascii=False, sort_keys=True), ids)
            rec[f"mail {i + 1}"] = {"body_sha": hashlib.sha256(body.encode()).hexdigest(), "body_len": len(body), "_body": body}
    finally:
        threading.Thread = orig_thread
    return rec


def strip(records):
    return {k: {kk: vv for kk, vv in v.items() if kk != "_body"} for k, v in records.items()}


def dump_bodies(records, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for k, v in records.items():
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", k).strip("_") or "root"
        (out / f"{name}.txt").write_text(json.dumps({kk: vv for kk, vv in v.items() if kk != "_body"}, indent=1)
                                         + "\n\n" + v.get("_body", ""), encoding="utf-8")
