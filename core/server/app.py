"""
Shop-Backend für Kundenkonto (Login per E-Mail-Bestätigung), gespeicherten Warenkorb,
Kasse (Vorkasse + optional Stripe), Bestellungen und SEO-Produktseiten in 6 Sprachen
(DE, EN, IT, ES, FR, PL – Texte kommen aus dem Block <script id="i18nData"> in public/index.html).

- Passwortloser Login: Kunde gibt E-Mail ein -> bekommt Bestätigungslink -> Klick bestätigt
  die Adresse (Double-Opt-in) und meldet an.  Beim ersten Mal entsteht dabei das Konto.
- Session als HttpOnly-Cookie, Warenkorb wird pro Konto in SQLite gespeichert.
- Ohne SMTP-Konfiguration läuft der Server im Dev-Modus: der Link wird in der Konsole
  ausgegeben (und an den Browser zurückgegeben), damit man lokal testen kann.

Start (lokal):   pip install -r requirements.txt && python app.py
Produktion:      gunicorn -w 2 -b 0.0.0.0:8000 app:app   (hinter HTTPS-Reverse-Proxy)
"""
import hashlib
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
from collections import defaultdict, deque
from email.message import EmailMessage

from flask import Flask, g, jsonify, redirect, request, send_from_directory
from werkzeug.routing import BaseConverter
from werkzeug.security import check_password_hash, generate_password_hash


def _load_env(path):
    """Minimaler .env-Loader (KEY=VALUE pro Zeile), ohne zusätzliche Abhängigkeit."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


HERE = os.path.dirname(os.path.abspath(__file__))
_load_env(os.path.join(HERE, ".env"))

PUBLIC_DIR = os.path.abspath(os.environ.get("PUBLIC_DIR", os.path.join(HERE, "..", "public")))
SITE_DIR = os.path.abspath(os.environ.get("SITE_DIR", os.path.join(HERE, "..", "..", "site")))

import shopsite as shop_site  # noqa: E402  Projektdaten aus site/ (core/server/shopsite.py)

SITE = shop_site.load(SITE_DIR)
PARTNER = SITE["cases"]["partner"]
PARTNER_SHORT = SITE["cases"]["partnerShort"]
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, f"{SITE['id']}.db"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_SSL = os.environ.get("SMTP_SSL", "0") == "1"  # 1 = SMTPS (Port 465), sonst STARTTLS
MAIL_FROM = os.environ.get("MAIL_FROM", SITE["mailFrom"])
DEV_MODE = not SMTP_HOST

TOKEN_TTL = 30 * 60            # Login-Link 30 Minuten gültig
SESSION_TTL = 30 * 24 * 3600   # angemeldet bleiben: 30 Tage
COOKIE = f"{SITE['cookiePrefix']}_session"
COOKIE_SECURE = BASE_URL.startswith("https://")

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", re.I)
SLUG_RE = re.compile(r"^[a-z0-9-]{1,48}$")
CODE_RE = re.compile(r"^[A-Z0-9_-]{3,24}$")
AFF_DISCOUNT = float(os.environ.get("AFFILIATE_DISCOUNT", "10"))     # Rabatt für Kunden in %
AFF_COMMISSION = float(os.environ.get("AFFILIATE_COMMISSION", "10"))  # Provision für Partner in % vom Warenwert
SPIN_CODE = SITE["spinCode"]  # Rabattcode aus dem Vial-Spin-Easter-Egg (site.json)
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_COOKIE = f"{SITE['cookiePrefix']}_admin"
ADMIN_TTL = 12 * 3600          # Admin-Anmeldung gilt 12 Stunden
ORDER_STATUSES = ("awaiting_payment", "paid", "shipped", "cancelled")
DISCORD_URL = os.environ.get("DISCORD_URL", SITE["discordUrl"])
# Zugänge mit eingeschränkter Rolle. Sie werden bei jedem Start angelegt, falls sie fehlen (nur der Passwort-Hash steht hier).
#   owner = Shop-Team, sieht alles
#   nexo  = Case-Partner (site.json: cases.partner), sieht nur Bestellungen mit Cases und darin nur die Case-Positionen plus Lieferdaten
# Start-Zugänge stehen in site/admins.json (nicht in Git): {"Name": {"hash": "scrypt:…", "role": "owner"|"nexo"}}
SITE_ADMINS = shop_site.admins(SITE_DIR)
DUMMY_HASH = generate_password_hash(secrets.token_hex(8))  # gleich lange Antwortzeit bei unbekannten Namen
ROLES = ("owner", "nexo")
NEXO_COMMISSION = float(os.environ.get("NEXO_COMMISSION", "15"))  # Startwert: Provision für den Shop in % vom Case-Umsatz
NEXO_NOTIFY = os.environ.get("NEXO_NOTIFY", "")                    # Postfach von Nexo für Case-Bestellungen (zusätzlich zur E-Mail im Zugang)
CASE_STATUSES = ("open", "shipped", "cancelled")
NEXO_ADDRESS = [x.strip() for x in os.environ.get("NEXO_ADDRESS", f"{PARTNER}|[Straße und Hausnummer]|[PLZ Ort]").split("|") if x.strip()]

app = Flask(__name__, static_folder=None)


class LangConverter(BaseConverter):
    """Sprachkürzel in URLs: genau zwei Kleinbuchstaben (de, en, it, es, fr, pl)."""
    regex = r"[a-z]{2}"


app.url_map.converters["lang"] = LangConverter
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024


# --------------------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  created_at INTEGER NOT NULL,
  confirmed_at INTEGER
);
CREATE TABLE IF NOT EXISTS login_tokens(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
CREATE TABLE IF NOT EXISTS sessions(
  session_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  email TEXT NOT NULL,
  address TEXT NOT NULL,
  items TEXT NOT NULL,
  subtotal INTEGER NOT NULL,
  shipping INTEGER NOT NULL,
  total INTEGER NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  paid_at INTEGER,
  stripe_session TEXT
);
CREATE TABLE IF NOT EXISTS affiliates(
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  discount_pct REAL NOT NULL DEFAULT 10,
  commission_pct REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_users(
  username TEXT PRIMARY KEY COLLATE NOCASE,
  pw_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_login INTEGER
);
CREATE TABLE IF NOT EXISTS admin_sessions(
  session_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL REFERENCES admin_users(username) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stock(
  slug TEXT NOT NULL,
  vi INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(slug, vi)
);
CREATE TABLE IF NOT EXISTS nexo_payouts(
  month TEXT PRIMARY KEY,
  amount INTEGER NOT NULL,
  paid_at INTEGER,
  paid_by TEXT,
  credit_no TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS client_errors(
  key TEXT PRIMARY KEY,
  msg TEXT NOT NULL,
  src TEXT,
  line INTEGER,
  stack TEXT,
  path TEXT,
  ua TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  title_en TEXT,
  text TEXT,
  text_en TEXT,
  starts_at INTEGER NOT NULL,
  ends_at INTEGER NOT NULL,
  published INTEGER NOT NULL DEFAULT 0,
  pct REAL NOT NULL DEFAULT 0,
  scope TEXT NOT NULL DEFAULT 'all',
  slugs TEXT NOT NULL DEFAULT '[]',
  include_cases INTEGER NOT NULL DEFAULT 0,
  combinable INTEGER NOT NULL DEFAULT 0,
  prize TEXT,
  terms TEXT,
  requires_order INTEGER NOT NULL DEFAULT 0,
  winners INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  created_by TEXT
);
CREATE TABLE IF NOT EXISTS giveaway_entries(
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  winner_at INTEGER,
  PRIMARY KEY(event_id, user_id)
);
CREATE TABLE IF NOT EXISTS giveaway_winners(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  ticket TEXT NOT NULL,
  email TEXT NOT NULL,
  order_id TEXT,
  drawn_at INTEGER NOT NULL,
  drawn_by TEXT
);
CREATE TABLE IF NOT EXISTS counters(
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pageviews(
  day TEXT NOT NULL,
  path TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT '',
  device TEXT NOT NULL DEFAULT '',
  lang TEXT NOT NULL DEFAULT '',
  views INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(day,path,ref,device,lang)
);
CREATE TABLE IF NOT EXISTS visits_daily(
  day TEXT PRIMARY KEY,
  visitors INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS visitors(
  day TEXT NOT NULL,
  hash TEXT NOT NULL,
  PRIMARY KEY(day,hash)
);
CREATE TABLE IF NOT EXISTS carts(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  items TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
    for col, typ in (("discount", "INTEGER NOT NULL DEFAULT 0"), ("affiliate_code", "TEXT"), ("commission", "INTEGER NOT NULL DEFAULT 0"),
                     ("lang", "TEXT NOT NULL DEFAULT 'de'"),
                     # Case-Anteil (Case-Partner): Warenwert nach anteiligem Rabatt, Provisionssatz zum Bestellzeitpunkt, Provision, eigener Versandstatus
                     ("case_total", "INTEGER NOT NULL DEFAULT 0"), ("nexo_pct", "REAL"), ("nexo_fee", "INTEGER NOT NULL DEFAULT 0"),
                     ("case_status", "TEXT"), ("case_tracking", "TEXT"), ("case_shipped_at", "INTEGER"),
                     # Rechnung / Stornorechnung und Versand (Teil des Shops)
                     ("invoice_no", "TEXT"), ("invoice_at", "INTEGER"), ("storno_no", "TEXT"), ("storno_at", "INTEGER"),
                     ("tracking", "TEXT"), ("shipped_at", "INTEGER"),
                     ("stock_taken", "INTEGER NOT NULL DEFAULT 0"), ("express", "INTEGER NOT NULL DEFAULT 0")):
        if col not in cols:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
    # Codes aus der Umgebung anlegen, z. B. AFFILIATE_CODES=ANNA10:Anna,LAB10:Labor Müller
    for entry in filter(None, (e.strip() for e in os.environ.get("AFFILIATE_CODES", "").split(","))):
        code, _, name = entry.partition(":")
        code = code.strip().upper()
        if CODE_RE.match(code):
            conn.execute("INSERT OR IGNORE INTO affiliates(code,name,discount_pct,commission_pct,created_at) VALUES(?,?,?,?,?)",
                         (code, name.strip() or code, AFF_DISCOUNT, AFF_COMMISSION, int(time.time())))
    acols = {r[1] for r in conn.execute("PRAGMA table_info(admin_users)")}
    if "email" not in acols:
        conn.execute("ALTER TABLE admin_users ADD COLUMN email TEXT")
    if "role" not in acols:
        conn.execute("ALTER TABLE admin_users ADD COLUMN role TEXT NOT NULL DEFAULT 'owner'")
    ecols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    for col, typ in (("prod_pct", "TEXT NOT NULL DEFAULT '{}'"), ("case_pct", "REAL NOT NULL DEFAULT 0"), ("source", "TEXT NOT NULL DEFAULT 'entries'"),
                     ("paid_only", "INTEGER NOT NULL DEFAULT 1"), ("multi_win", "INTEGER NOT NULL DEFAULT 0")):
        if col not in ecols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")
    for col, typ in (("totp_secret", "TEXT"), ("totp_on", "INTEGER NOT NULL DEFAULT 0"), ("totp_last", "INTEGER NOT NULL DEFAULT 0")):
        if col not in acols:
            conn.execute(f"ALTER TABLE admin_users ADD COLUMN {col} {typ}")
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('nexo_pct',?)", (f"{NEXO_COMMISSION:g}",))
    # Admin-Zugänge beim ersten Start anlegen (nur die gesalzenen Passwort-Hashes stehen hier, nie die Passwörter).
    # Passwort ändern: im Admin-Bereich unter "Zugang" oder per  python app.py set-admin NAME
    if not conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        for name, a in SITE_ADMINS.items():
            if a["role"] == "owner":
                conn.execute("INSERT OR IGNORE INTO admin_users(username,pw_hash,created_at) VALUES(?,?,?)", (name, a["hash"], int(time.time())))
    # Rabattcode aus dem Vial-Spin-Easter-Egg (5 Umdrehungen in der Produktansicht): 10 % Rabatt, keine Provision.
    # Nur beim ersten Mal angelegt, danach im Admin unter "Partner-Codes" änderbar oder abschaltbar.
    conn.execute("INSERT OR IGNORE INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,?,NULL,10,0,1,?)",
                 (SPIN_CODE, "Vial-Spin (Easter Egg)", int(time.time())))
    for name, a in SITE_ADMINS.items():
        if a["role"] != "owner":
            conn.execute("INSERT OR IGNORE INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?)", (name, a["hash"], int(time.time()), a["role"]))
    if not SITE_ADMINS and not conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        print("[ADMIN] Keine Zugänge: site/admins.json anlegen oder  python app.py set-admin NAME", flush=True)
    conn.execute("DELETE FROM visitors WHERE day<?", (time.strftime("%Y-%m-%d"),))
    conn.commit()
    conn.close()


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def now():
    return int(time.time())


# ----------------------------------------------------------------- Sprachen
# Eine Quelle für alle Texte: der JSON-Block <script id="i18nData"> in public/index.html.
_i18n = {"mtime": 0, "data": {}}
DEFAULT_LANG = "de"


def i18n():
    path = os.path.join(PUBLIC_DIR, "index.html")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return _i18n["data"]
    if mt != _i18n["mtime"]:
        with open(path, encoding="utf-8") as fh:
            m = re.search(r'<script type="application/json" id="i18nData">(.*?)</script>', fh.read(), re.S)
        try:
            _i18n.update(mtime=mt, data=json.loads(m.group(1)) if m else {})
        except ValueError as exc:
            print(f"[I18N] Übersetzungen konnten nicht gelesen werden: {exc}", flush=True)
            _i18n.update(mtime=mt, data={})
    return _i18n["data"]


def langs():
    return list((i18n().get("langs") or {DEFAULT_LANG: "Deutsch"}).keys())


def norm_lang(value):
    value = str(value or "").lower()[:2]
    return value if value in langs() else None


def request_lang(body=None):
    """Sprache aus Anfrage-Daten, Cookie oder Accept-Language – sonst Deutsch."""
    if body and norm_lang(body.get("lang")):
        return norm_lang(body.get("lang"))
    if norm_lang(request.args.get("lang")):
        return norm_lang(request.args.get("lang"))
    if norm_lang(request.cookies.get("gp_lang")):
        return norm_lang(request.cookies.get("gp_lang"))
    best = request.accept_languages.best_match(langs())
    return best or DEFAULT_LANG


def tr(lang, key, **kw):
    srv = i18n().get("server", {})
    text = (srv.get(lang) or {}).get(key) or (srv.get(DEFAULT_LANG) or {}).get(key) or key
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


# ------------------------------------------------------------------ rate limit
_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def limited(key, maximum, window):
    """True, wenn der Schlüssel das Limit überschritten hat."""
    t = time.time()
    with _hits_lock:
        q = _hits[key]
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= maximum:
            return True
        q.append(t)
        return False


def recent_hits(key, window):
    """Anzahl der gemerkten Treffer im Zeitfenster, ohne einen neuen zu zählen."""
    t = time.time()
    with _hits_lock:
        q = _hits.get(key)
        return sum(1 for x in q if x >= t - window) if q else 0


def client_ip():
    # hinter einem Reverse-Proxy: X-Forwarded-For (erste Adresse) verwenden
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"


# -------------------------------------------------------------------- helpers
def require_custom_header():
    """Einfacher CSRF-Schutz: schreibende API-Aufrufe brauchen den Header X-GP: 1.
    Fremde Seiten können diesen Header ohne CORS-Freigabe nicht setzen."""
    return request.headers.get("X-GP") == "1"


def current_user():
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    row = db().execute(
        "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.session_hash=? AND s.expires_at>?",
        (sha(raw), now()),
    ).fetchone()
    return row


def clean_items(items):
    if not isinstance(items, list):
        raise ValueError("items")
    merged = {}
    for it in items[:60]:
        if not isinstance(it, dict):
            continue
        slug = str(it.get("slug", ""))
        try:
            vi = int(it.get("vi", 0))
            qty = int(it.get("qty", 1))
        except (TypeError, ValueError):
            continue
        if not SLUG_RE.match(slug) or not (0 <= vi <= 5) or qty < 1:
            continue
        cfg = clean_cfg(it.get("cfg"))
        key = (slug, vi, json.dumps(cfg, sort_keys=True) if cfg else "")
        merged[key] = min(99, merged.get(key, 0) + qty)
    out = []
    for (s, v, c), q in merged.items():
        row = {"slug": s, "vi": v, "qty": q}
        if c:
            row["cfg"] = json.loads(c)
        out.append(row)
    return out


HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def clean_cfg(cfg):
    """Konfiguration eines Cases: Farben für Deckel, Boden, Inlay (#rrggbb) und Inlay-Variante."""
    if not isinstance(cfg, dict):
        return None
    out = {}
    for k in ("lid", "base", "inlay"):
        v = str(cfg.get(k, "")).strip().lower()
        if HEX_RE.match(v):
            out[k] = v
    layout = str(cfg.get("layout", ""))
    if re.match(r"^[a-z0-9-]{1,24}$", layout):
        out["layout"] = layout
    return out if len(out) == 4 else None


def send_login_mail(to_addr, link, lang=DEFAULT_LANG):
    subject = tr(lang, "login_subject")
    text = tr(lang, "login_text", link=link)
    T = lambda k: _html.escape(tr(lang, k))
    html = f"""<!doctype html><html lang="{lang}"><body style="margin:0;background:#f4f5fa;font-family:Arial,Helvetica,sans-serif;color:#0a0f2e">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px">
<table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;background:#fff;border-radius:18px;overflow:hidden">
<tr><td style="background:{SITE['brandColor']};padding:22px 28px;color:#fff;font-weight:800;font-size:18px">{_html.escape(SITE['name'])}</td></tr>
<tr><td style="padding:28px">
<h1 style="margin:0 0 12px;font-size:22px">{T("login_h1")}</h1>
<p style="margin:0 0 22px;line-height:1.55">{T("login_p")}</p>
<p style="margin:0 0 22px"><a href="{link}" style="display:inline-block;background:#0a0f2e;color:#D9FF3F;text-decoration:none;font-weight:700;padding:14px 24px;border-radius:999px">{T("login_btn")}</a></p>
<p style="margin:0;font-size:12px;color:#6a7095;line-height:1.5">{T("login_small")}</p>
</td></tr></table></td></tr></table></body></html>"""

    send_mail(to_addr, subject, text, html, dev_note=f"Login-Link: {link}")


def mail_layout(title, body_html, lang=DEFAULT_LANG):
    return f"""<!doctype html><html lang="{lang}"><body style="margin:0;background:#f4f5fa;font-family:Arial,Helvetica,sans-serif;color:#0a0f2e">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fff;border-radius:18px;overflow:hidden">
<tr><td style="background:{SITE['brandColor']};padding:22px 28px;color:#fff;font-weight:800;font-size:18px">{_html.escape(SITE['name'])}</td></tr>
<tr><td style="padding:28px"><h1 style="margin:0 0 14px;font-size:22px">{title}</h1>{body_html}
<p style="margin:22px 0 0;font-size:13px"><a href="{DISCORD_URL}" style="color:#5865F2;font-weight:700;text-decoration:none">{_html.escape(tr(lang, "discord_line", link="Discord"))}</a></p>
<p style="margin:26px 0 0;font-size:11px;color:#6a7095;line-height:1.5">{_html.escape(tr(lang, "disclaimer"))}</p>
</td></tr></table></td></tr></table></body></html>"""


def send_mail(to_addr, subject, text, html, dev_note="", attachments=None):
    """Versendet eine E-Mail im Hintergrund. Ohne SMTP (Dev-Modus) nur Konsolenausgabe.
    attachments: Liste von (Dateiname, bytes, "application/pdf")"""
    if DEV_MODE:
        att = "".join(f"\n  [Anhang] {a[0]} ({len(a[1]) // 1024} KB)" for a in attachments or [])
        print(f"\n[DEV] Mail an {to_addr}: {subject}\n{dev_note or text[:400]}{att}\n", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = to_addr
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    ctx = ssl.create_default_context()
    try:
        if SMTP_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.starttls(context=ctx)
                if SMTP_USER:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
    except Exception as exc:  # Versandfehler nicht an den Client durchreichen
        print(f"[MAIL] Versand an {to_addr} fehlgeschlagen: {exc}", flush=True)


# ----------------------------------------------------------------------- auth
@app.post("/api/auth/request")
def auth_request():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify(error="invalid_email"), 400
    if limited("ip:" + client_ip(), 10, 15 * 60) or limited("mail:" + email, 4, 15 * 60):
        return jsonify(error="rate_limited"), 429

    conn = db()
    conn.execute("INSERT OR IGNORE INTO users(email, created_at) VALUES(?,?)", (email, now()))
    user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO login_tokens(token_hash,user_id,expires_at) VALUES(?,?,?)",
        (sha(token), user["id"], now() + TOKEN_TTL),
    )
    conn.execute("DELETE FROM login_tokens WHERE expires_at<?", (now() - 86400,))
    conn.commit()

    lang = request_lang(data)
    link = f"{BASE_URL}/api/auth/verify?token={token}&lang={lang}"
    threading.Thread(target=send_login_mail, args=(email, link, lang), daemon=True).start()
    resp = {"ok": True}
    if DEV_MODE:
        resp["devLink"] = link  # nur lokal ohne SMTP – in Produktion nie gesetzt
    return jsonify(resp)


@app.get("/api/auth/verify")
def auth_verify():
    token = request.args.get("token", "")
    conn = db()
    row = conn.execute(
        "SELECT token_hash,user_id FROM login_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
        (sha(token), now()),
    ).fetchone() if token else None
    lang = request_lang()
    if not row:
        return redirect(f"{BASE_URL}/{lang}/?login=expired")
    conn.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?", (now(), row["token_hash"]))
    conn.execute("UPDATE users SET confirmed_at=COALESCE(confirmed_at, ?) WHERE id=?", (now(), row["user_id"]))
    raw = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions(session_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
        (sha(raw), row["user_id"], now() + SESSION_TTL, now()),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
    conn.commit()
    resp = redirect(f"{BASE_URL}/{lang}/?login=ok")
    resp.set_cookie(COOKIE, raw, max_age=SESSION_TTL, httponly=True, secure=COOKIE_SECURE, samesite="Lax", path="/")
    return resp


@app.post("/api/auth/logout")
def auth_logout():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    raw = request.cookies.get(COOKIE)
    if raw:
        db().execute("DELETE FROM sessions WHERE session_hash=?", (sha(raw),))
        db().commit()
    resp = jsonify(ok=True)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/me")
def me():
    u = current_user()
    if not u:
        return jsonify(user=None)
    row = db().execute("SELECT items FROM carts WHERE user_id=?", (u["id"],)).fetchone()
    return jsonify(user={"email": u["email"], "partner": bool(partner_codes(u["email"])), "team": is_team(u["email"])},
                   cart=json.loads(row["items"]) if row else [])


# ----------------------------------------------------------------------- cart
@app.get("/api/cart")
def cart_get():
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    row = db().execute("SELECT items FROM carts WHERE user_id=?", (u["id"],)).fetchone()
    return jsonify(items=json.loads(row["items"]) if row else [])


@app.put("/api/cart")
def cart_put():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    try:
        items = clean_items(data.get("items"))
    except ValueError:
        return jsonify(error="invalid_items"), 400
    db().execute(
        "INSERT INTO carts(user_id,items,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET items=excluded.items, updated_at=excluded.updated_at",
        (u["id"], json.dumps(items), now()),
    )
    db().commit()
    return jsonify(items=items)


# ----------------------------------------------------------------------- shop
# Produktdaten kommen aus public/products.json – dieselbe Datei nutzt die Seite.
# Preise werden IMMER hier auf dem Server berechnet, nie aus dem Browser übernommen.
SHIPPING_DE = float(os.environ.get("SHIPPING_DE", "4.90"))        # Beispielwerte – anpassen!
SHIPPING_EU = float(os.environ.get("SHIPPING_EU", "9.90"))
FREE_SHIPPING_FROM = float(os.environ.get("FREE_SHIPPING_FROM", "100"))  # ab 100 € Warenwert (nach Rabatt) versandkostenfrei, 0 = aus
BANK = {k: os.environ.get("BANK_" + k.upper(), "") for k in ("owner", "iban", "bic", "name")}
STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WHSEC = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ORDER_NOTIFY = os.environ.get("ORDER_NOTIFY", "")  # Shop-Postfach für Bestell-Benachrichtigungen
# Rechnungen: Angaben des Verkäufers (Pflichtangaben nach § 14 UStG) – bitte in .env eintragen
SHOP_LEGAL_NAME = os.environ.get("SHOP_LEGAL_NAME", SITE["name"])
SHOP_ADDRESS = [x.strip() for x in os.environ.get("SHOP_ADDRESS", "Musterstraße 1|12345 Musterstadt|Deutschland").split("|") if x.strip()]
SHOP_EMAIL = os.environ.get("SHOP_EMAIL", f"info@{SITE['domain']}")
SHOP_VAT_ID = os.environ.get("SHOP_VAT_ID", "")
SHOP_TAX_NO = os.environ.get("SHOP_TAX_NO", "")
VAT_RATE = float(os.environ.get("VAT_RATE", "19"))
SMALL_BUSINESS = os.environ.get("SMALL_BUSINESS", "0") == "1"   # Kleinunternehmer nach § 19 UStG: keine Umsatzsteuer
TRACKING_URL = os.environ.get("TRACKING_URL", "")
EXPRESS_DE = float(os.environ.get("EXPRESS_DE", "9.90"))          # Aufpreis Expressversand Deutschland (0 = nicht angeboten)
EXPRESS_EU = float(os.environ.get("EXPRESS_EU", "0"))             # Aufpreis Express ins EU-Ausland (0 = nicht angeboten)
STOCK_LOW = int(os.environ.get("STOCK_LOW", "5"))                 # ab dieser Stückzahl „bald ausverkauft“ im Admin
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(HERE, "backups"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))            # so viele tägliche Sicherungen aufbewahren
BACKUP_EVERY = int(os.environ.get("BACKUP_EVERY_HOURS", "24")) * 3600                 # z. B. https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={code}

COUNTRIES = {
    "DE": "Deutschland", "AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien", "HR": "Kroatien", "CY": "Zypern",
    "CZ": "Tschechien", "DK": "Dänemark", "EE": "Estland", "FI": "Finnland", "FR": "Frankreich", "GR": "Griechenland",
    "HU": "Ungarn", "IE": "Irland", "IT": "Italien", "LV": "Lettland", "LT": "Litauen", "LU": "Luxemburg",
    "MT": "Malta", "NL": "Niederlande", "PL": "Polen", "PT": "Portugal", "RO": "Rumänien", "SK": "Slowakei",
    "SI": "Slowenien", "ES": "Spanien", "SE": "Schweden",
}

_products = {"mtime": 0, "data": {}, "raw": None}


def products():
    path = os.path.join(SITE_DIR, "products.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    if mt != _products["mtime"]:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        _products.update(mtime=mt, raw=raw, data={p["slug"]: p for p in raw.get("products", [])},
                         cases={c["slug"]: c for c in raw.get("cases", [])})
    return _products["data"]


def cases():
    products()
    return _products.get("cases") or {}


def case_line(c, it):
    """Bestellposition für ein Case. Ohne gültige Konfiguration -> None."""
    cfg = it.get("cfg")
    if not cfg or cfg.get("layout") not in (c.get("inlays") or {}):
        return None
    names = {k.lower(): v for k, v in (c.get("colors") or {}).items()}
    if not c.get("customColor") and any(cfg[k] not in names for k in ("lid", "base", "inlay")):
        return None
    col = lambda h: names.get(h) or f"Eigene Farbe {h}"
    unit = cents(c["price"])
    label = f"{c['inlays'][cfg['layout']]} · Deckel {col(cfg['lid'])} · Boden {col(cfg['base'])} · Inlay {col(cfg['inlay'])}"
    return {"slug": c["slug"], "sku": c.get("sku", ""), "name": c["name"], "variant": label, "vi": 0, "qty": it["qty"],
            "unit": unit, "total": unit * it["qty"], "preorder": c.get("status") == "preorder", "vendor": c.get("vendor", "nexo"), "cfg": cfg}


# ----------------------------------------------------------------- Events (Sales, Gewinnspiele)
def active_sales(conn=None):
    t = now()
    rows = (conn or db()).execute("SELECT * FROM events WHERE kind='sale' AND published=1 AND starts_at<=? AND ends_at>?", (t, t)).fetchall()
    return [dict(r, slugs=json.loads(r["slugs"] or "[]"), prod_pct=json.loads(r["prod_pct"] or "{}")) for r in rows]


def sale_pct_for(ev, slug, case=False):
    """Rabatt eines Sales für ein Produkt: eigener Wert je Produkt hat Vorrang (0 = ausgenommen), sonst der Standardwert."""
    if case:
        return (ev["case_pct"] or ev["pct"]) if ev["include_cases"] else 0
    if slug in ev["prod_pct"]:
        return ev["prod_pct"][slug]
    if ev["scope"] == "all" or slug in ev["slugs"]:
        return ev["pct"]
    return 0


def best_sale(sales, slug, case=False):
    best = None
    for ev in sales:
        pc = sale_pct_for(ev, slug, case)
        if pc > 0 and (not best or pc > best["pct"]):
            best = {**ev, "pct": pc}
    return best


def event_public(r, lang, user=None):
    en = lang != "de"
    o = {"id": r["id"], "kind": r["kind"], "title": (r["title_en"] if en and r["title_en"] else r["title"]),
         "text": (r["text_en"] if en and r["text_en"] else r["text"]) or "", "starts": r["starts_at"], "ends": r["ends_at"]}
    if r["kind"] == "sale":
        pp = json.loads(r["prod_pct"] or "{}")
        o.update(pct=r["pct"], scope=r["scope"], slugs=json.loads(r["slugs"] or "[]"), items=pp, cases=bool(r["include_cases"]),
                 case_pct=(r["case_pct"] or r["pct"]) if r["include_cases"] else 0, combinable=bool(r["combinable"]),
                 max_pct=max([r["pct"] if r["scope"] == "all" else 0] + list(pp.values()) + ([(r["case_pct"] or r["pct"])] if r["include_cases"] else [])))
    else:
        o.update(prize=r["prize"] or "", terms=r["terms"] or "", requires_order=bool(r["requires_order"]), entered=False, source=r["source"] or "entries")
        if user:
            o["entered"] = bool(db().execute("SELECT 1 FROM giveaway_entries WHERE event_id=? AND user_id=?", (r["id"], user["id"])).fetchone())
    return o


def stock_of(slug, vi, conn=None):
    """Verfügbare Stückzahl oder None (= nicht gezählt, unbegrenzt)."""
    r = (conn or db()).execute("SELECT qty FROM stock WHERE slug=? AND vi=?", (slug, vi)).fetchone()
    return r[0] if r else None


def take_stock(lines, conn=None):
    """Bestand für eine Bestellung abziehen. Reicht er nicht (gleichzeitige Bestellung), wird nichts abgezogen."""
    c = conn or db()
    done = []
    for l in lines:
        if is_case(l):
            continue
        cur = c.execute("UPDATE stock SET qty=qty-?, updated_at=? WHERE slug=? AND vi=? AND qty>=?", (l["qty"], now(), l["slug"], l["vi"], l["qty"]))
        if cur.rowcount == 0 and stock_of(l["slug"], l["vi"], c) is not None:
            for d in done:
                c.execute("UPDATE stock SET qty=qty+? WHERE slug=? AND vi=?", (d["qty"], d["slug"], d["vi"]))
            c.commit()
            return False
        done.append(l)
    return True


def give_back_stock(oid, conn=None):
    c = conn or db()
    r = c.execute("SELECT items, stock_taken FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or not r["stock_taken"]:
        return
    for l in json.loads(r["items"]):
        if not is_case(l):
            c.execute("UPDATE stock SET qty=qty+?, updated_at=? WHERE slug=? AND vi=?", (l["qty"], now(), l["slug"], l["vi"]))
    c.execute("UPDATE orders SET stock_taken=0 WHERE id=?", (oid,))
    c.commit()


def get_setting(key, default=None, conn=None):
    row = (conn or db()).execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def nexo_pct(conn=None):
    try:
        return float(get_setting("nexo_pct", NEXO_COMMISSION, conn))
    except (TypeError, ValueError):
        return NEXO_COMMISSION


def is_case(line):
    return line.get("vendor") == "nexo"


def cents(x):
    return int(round(float(x) * 100))


def eur(c, lang=DEFAULT_LANG):
    if lang == "en":
        return f"€{c / 100:,.2f}"
    return f"{c / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def find_affiliate(code):
    code = str(code or "").strip().upper()
    if not CODE_RE.match(code):
        return None
    return db().execute("SELECT * FROM affiliates WHERE code=? AND active=1", (code,)).fetchone()


def quote(items, country, code=None, express=False):
    """Berechnet Positionen, Zwischensumme, Rabatt, Versand und Summe serverseitig."""
    prods, lines, skipped, limited = products(), [], [], []
    for it in clean_items(items):
        c = cases().get(it["slug"])
        if c:
            if c.get("status") == "out_of_stock":
                skipped.append(c["name"])
                continue
            line = case_line(c, it)
            if line:
                lines.append(line)
            continue
        p = prods.get(it["slug"])
        if not p or it["vi"] >= len(p.get("variants", [])):
            continue
        if p.get("status") == "out_of_stock":
            skipped.append(p["name"])
            continue
        v = p["variants"][it["vi"]]
        avail = stock_of(p["slug"], it["vi"])
        if avail is not None and avail <= 0:
            skipped.append(f"{p['name']} ({v['label']})")
            continue
        if avail is not None and it["qty"] > avail:
            limited.append({"slug": p["slug"], "vi": it["vi"], "name": f"{p['name']} ({v['label']})", "qty": avail})
            it = {**it, "qty": avail}
        unit = cents(v["price"])
        lines.append({"slug": p["slug"], "sku": p.get("sku", ""), "name": p["name"], "variant": v["label"], "vi": it["vi"],
                      "qty": it["qty"], "unit": unit, "total": unit * it["qty"], "preorder": p.get("status") == "preorder"})
    # laufender Sale: Stückpreis reduzieren (bei mehreren Sales zählt der höchste Rabatt)
    sales = active_sales()
    for l in lines:
        ev = best_sale(sales, l["slug"], is_case(l))
        if ev:
            orig = l["unit"]
            l.update(orig_unit=orig, sale_pct=ev["pct"], event_id=ev["id"], unit=int(round(orig * (1 - ev["pct"] / 100))))
            l["total"] = l["unit"] * l["qty"]
            l["sale_combinable"] = bool(ev["combinable"])
    subtotal = sum(l["total"] for l in lines)
    aff, code_info, code_error, discount = None, None, None, 0
    if code:
        aff = find_affiliate(code)
        if aff:
            # Partner-Rabatt pro Position; Sale-Artikel nur, wenn der Sale mit Codes kombinierbar ist
            for l in lines:
                if "sale_pct" not in l or l.get("sale_combinable"):
                    l["code_disc"] = int(round(l["total"] * aff["discount_pct"] / 100))
            discount = sum(l.get("code_disc", 0) for l in lines)
            code_info = {"code": aff["code"], "pct": aff["discount_pct"], "partial": any("sale_pct" in l and not l.get("sale_combinable") for l in lines)}
        else:
            code_error = "invalid_code"
    net = subtotal - discount
    ship = cents(SHIPPING_DE if country == "DE" else SHIPPING_EU) if lines else 0
    if FREE_SHIPPING_FROM and net >= cents(FREE_SHIPPING_FROM):
        ship = 0
    # Express: fester Aufpreis, auch wenn der normale Versand frei ist
    express_fee = cents(EXPRESS_DE if country == "DE" else EXPRESS_EU) if (express and lines) else 0
    ship += express_fee
    commission = int(round(net * aff["commission_pct"] / 100)) if aff else 0
    # Case-Anteil: Warenwert der Cases abzüglich anteiligem Rabatt; davon bekommt der Shop nexo_pct % Provision
    case_gross = sum(l["total"] for l in lines if is_case(l))
    case_total = sum(l["total"] - l.get("code_disc", 0) for l in lines if is_case(l))
    for l in lines:
        l.pop("code_disc", None)
        l.pop("sale_combinable", None)
    pct = nexo_pct() if case_gross else None
    nexo_fee = int(round(case_total * pct / 100)) if case_gross else 0
    return {"lines": lines, "subtotal": subtotal, "discount": discount, "code": code_info, "codeError": code_error,
            "shipping": ship, "total": net + ship, "skipped": skipped, "limited": limited, "commission": commission,
            "express": bool(express_fee), "express_fee": express_fee,
            "case_total": case_total, "nexo_pct": pct, "nexo_fee": nexo_fee,
            "freeFrom": cents(FREE_SHIPPING_FROM) if FREE_SHIPPING_FROM else 0}


def new_order_id():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return SITE["orderPrefix"] + "-" + time.strftime("%y%m%d") + "-" + "".join(secrets.choice(alphabet) for _ in range(5))


def clean_address(a):
    a = a if isinstance(a, dict) else {}
    out = {k: str(a.get(k, "")).strip()[:120] for k in ("name", "company", "street", "zip", "city", "country", "email")}
    out["email"] = out["email"].lower()
    errs = []
    if len(out["name"]) < 2: errs.append("name")
    if len(out["street"]) < 3: errs.append("street")
    if not re.match(r"^[A-Za-z0-9 -]{3,10}$", out["zip"]): errs.append("zip")
    if len(out["city"]) < 2: errs.append("city")
    if out["country"] not in COUNTRIES: errs.append("country")
    if not EMAIL_RE.match(out["email"]): errs.append("email")
    return out, errs


def order_lines_text(q, lang=DEFAULT_LANG):
    rows = [f"{l['qty']}× {l['name']} ({l['variant']})  {eur(l['total'], lang)}" for l in q["lines"]]
    if q.get("discount"):
        rows.append(f"{tr(lang, 'discount')} ({q.get('code_label', '')})  −{eur(q['discount'], lang)}")
    ship_l = tr(lang, "shipping") + (f" ({tr(lang, 'express')})" if q.get("express") else "")
    rows += [f"{ship_l}  {eur(q['shipping'], lang)}", f"{tr(lang, 'total')}  {eur(q['total'], lang)}"]
    return "\n".join(rows)


def order_lines_html(q, lang=DEFAULT_LANG):
    e = _html.escape
    rows = "".join(f"<tr><td style='padding:6px 0'>{l['qty']}× {e(l['name'])} <span style='color:#6a7095'>({e(l['variant'])})</span></td>"
                   f"<td style='padding:6px 0;text-align:right'>{eur(l['total'], lang)}</td></tr>" for l in q["lines"])
    if q.get("discount"):
        rows += f"<tr><td style='padding:6px 0;color:#1a8f5a'>{e(tr(lang, 'discount'))} ({e(q.get('code_label', ''))})</td><td style='text-align:right;color:#1a8f5a'>−{eur(q['discount'], lang)}</td></tr>"
    ship_l = tr(lang, "shipping") + (f" ({tr(lang, 'express')})" if q.get("express") else "")
    rows += f"<tr><td style='padding:6px 0;color:#6a7095'>{e(ship_l)}</td><td style='text-align:right;color:#6a7095'>{eur(q['shipping'], lang)}</td></tr>"
    rows += f"<tr><td style='padding:10px 0;font-weight:800;border-top:1px solid #e6e8f2'>{e(tr(lang, 'total'))}</td><td style='text-align:right;font-weight:800;border-top:1px solid #e6e8f2'>{eur(q['total'], lang)}</td></tr>"
    return f"<table width='100%' style='font-size:14px;border-collapse:collapse'>{rows}</table>"


def send_order_mails(order_id, addr, q, method, paid=False, lang=DEFAULT_LANG, attachments=None):
    e = _html.escape
    if method == "prepayment" and not paid:
        bank_lines = [f"{tr(lang, 'owner')}: {BANK['owner']}", f"IBAN: {BANK['iban']}", f"BIC: {BANK['bic']}", f"Bank: {BANK['name']}",
                      f"{tr(lang, 'amount')}: {eur(q['total'], lang)}", f"{tr(lang, 'reference')}: {order_id}"]
        info_t = tr(lang, "bank_intro") + "\n" + "\n".join(bank_lines) + "\n\n" + tr(lang, "ship_after")
        info_h = (f"<p style='line-height:1.55'>{e(tr(lang, 'bank_intro_html'))}</p>"
                  "<p style='background:#f4f6fb;border-radius:12px;padding:14px;line-height:1.7;font-size:14px'>" + "<br>".join(e(b) for b in bank_lines) + "</p>")
    else:
        info_t = tr(lang, "paid_info")
        info_h = f"<p style='line-height:1.55'>{e(tr(lang, 'paid_info'))}</p>"
    subject = tr(lang, "subject_paid" if paid else "subject_thanks", order=order_id)
    text = (f"{tr(lang, 'hello', name=addr['name'])}\n\n{tr(lang, 'thanks_text', order=order_id)}\n\n"
            f"{order_lines_text(q, lang)}\n\n{info_t}\n\n" + SITE["name"])
    html = mail_layout(e(tr(lang, "order", order=order_id)),
                       f"<p>{e(tr(lang, 'thanks_html', name=addr['name']))}</p>{order_lines_html(q, lang)}{info_h}", lang)
    if attachments:
        text += "\n\n" + tr(lang, "invoice_attached")
        html = html.replace('<p style="margin:26px 0 0;font-size:11px', f"<p style='color:#6a7095;font-size:13px'>{e(tr(lang, 'invoice_attached'))}</p>" + '<p style="margin:26px 0 0;font-size:11px', 1)
    threading.Thread(target=send_mail, args=(addr["email"], subject, text, html), kwargs={"attachments": attachments}, daemon=True).start()
    if ORDER_NOTIFY:
        t = f"Neue Bestellung {order_id} ({method}, {'bezahlt' if paid else 'offen'}, Sprache {lang.upper()}){' · EXPRESS' if q.get('express') else ''}\n{addr}\n\n{order_lines_text(q)}"
        threading.Thread(target=send_mail, args=(ORDER_NOTIFY, f"[Shop]{' [EXPRESS]' if q.get('express') else ''} {order_id}", t, f"<pre>{t}</pre>"), daemon=True).start()


# ----------------------------------------------------------------- Rechnungen
import sys as _sys
_sys.path.insert(0, HERE)
import pdfdoc  # noqa: E402


def next_number(prefix, conn=None):
    """Fortlaufende Nummer pro Jahr, z. B. RE-2026-00001 (eine einzige SQL-Anweisung, daher auch mit mehreren Workern sicher)."""
    year = time.strftime("%Y")
    key = f"{prefix}-{year}"
    n = (conn or db()).execute("INSERT INTO counters(name,value) VALUES(?,1) ON CONFLICT(name) DO UPDATE SET value=value+1 RETURNING value",
                               (key,)).fetchone()[0]
    return f"{key}-{n:05d}"


def ensure_invoice(oid, conn=None):
    """Rechnung vergeben, sobald eine Bestellung bezahlt ist. Gibt die Rechnungsnummer zurück (oder None)."""
    c = conn or db()
    r = c.execute("SELECT status, invoice_no FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or r["status"] not in ("paid", "shipped"):
        return r["invoice_no"] if r else None
    if r["invoice_no"]:
        return r["invoice_no"]
    no = next_number("RE", c)
    c.execute("UPDATE orders SET invoice_no=?, invoice_at=? WHERE id=? AND invoice_no IS NULL", (no, now(), oid))
    c.commit()
    return c.execute("SELECT invoice_no FROM orders WHERE id=?", (oid,)).fetchone()[0]


def seller_lines():
    return [SHOP_LEGAL_NAME] + SHOP_ADDRESS + [SHOP_EMAIL]


def seller_footer(lang):
    tax = []
    if SHOP_VAT_ID:
        tax.append(("USt-IdNr. " if lang == "de" else "VAT ID ") + SHOP_VAT_ID)
    if SHOP_TAX_NO:
        tax.append(("Steuernummer " if lang == "de" else "Tax no. ") + SHOP_TAX_NO)
    bank = " · ".join(x for x in (BANK["name"], ("IBAN " + BANK["iban"]) if BANK["iban"] else "", ("BIC " + BANK["bic"]) if BANK["bic"] else "") if x)
    return [" · ".join([SHOP_LEGAL_NAME] + SHOP_ADDRESS), " · ".join(tax + [SHOP_EMAIL]), bank]


def invoice_pdf(r, storno=False):
    """Rechnung bzw. Stornorechnung als PDF (bytes). Sprache: Deutsch, für alle anderen Bestellsprachen Englisch."""
    lang = "de" if (r["lang"] or "de") == "de" else "en"
    D = lang == "de"
    a = json.loads(r["address"] or "{}")
    items = json.loads(r["items"] or "[]")
    sign = -1 if storno else 1
    m = lambda c: pdfdoc.money(sign * (c or 0), lang)
    date = lambda t: time.strftime("%d.%m.%Y", time.localtime(t)) if t else "-"
    buyer = [x for x in (a.get("name"), a.get("company"), a.get("street"), f"{a.get('zip', '')} {a.get('city', '')}".strip(),
                         COUNTRIES.get(a.get("country"), a.get("country", "")) if D else a.get("country", "")) if x]
    meta = []
    if storno:
        meta += [("Stornorechnung Nr." if D else "Credit note no.", r["storno_no"]), ("Datum" if D else "Date", date(r["storno_at"])),
                 ("zu Rechnung" if D else "for invoice", r["invoice_no"])]
    else:
        meta += [("Rechnungsnummer" if D else "Invoice no.", r["invoice_no"]), ("Rechnungsdatum" if D else "Invoice date", date(r["invoice_at"])),
                 ("Leistungsdatum" if D else "Date of supply", date(r["shipped_at"] or r["paid_at"] or r["invoice_at"]))]
    meta += [("Bestellnummer" if D else "Order no.", r["id"]), ("Bestellt am" if D else "Ordered", date(r["created_at"])),
             ("Zahlart" if D else "Payment", {"prepayment": "Vorkasse" if D else "Bank transfer", "stripe": "Online (Stripe)"}.get(r["method"], r["method"]))]
    rows = []
    for i in items:
        extra = i.get("variant", "")
        if i.get("vendor") == "nexo":
            extra += " · " + (f"gefertigt und versendet von {PARTNER}" if D else f"made and shipped by {PARTNER}")
        if i.get("sale_pct"):
            extra += f" · Sale −{i['sale_pct']:g} % ({'statt' if D else 'was'} {m(i.get('orig_unit', 0))})"
        if i.get("sku"):
            extra += f" · {'Art.-Nr.' if D else 'SKU'} {i['sku']}"
        rows.append((i.get("qty", 1), i.get("name", ""), extra, m(i.get("unit", 0)), m(i.get("total", 0))))
    totals = [("Zwischensumme" if D else "Subtotal", m(r["subtotal"]), False)]
    if r["discount"]:
        totals.append(((f"Rabatt ({r['affiliate_code']})" if D else f"Discount ({r['affiliate_code']})"), m(-r["discount"]), False))
    totals.append((("Versand" if D else "Shipping") + ((" (Express)") if r["express"] else ""), m(r["shipping"]), False))
    totals.append(("Gesamtbetrag (brutto)" if D else "Total (gross)", m(r["total"]), True))
    notes = []
    if SMALL_BUSINESS:
        notes.append("Gemäß § 19 UStG wird keine Umsatzsteuer berechnet." if D else "No VAT charged (small business, § 19 UStG).")
    else:
        net = int(round(r["total"] / (1 + VAT_RATE / 100)))
        totals.append((f"{'Nettobetrag' if D else 'Net amount'}", m(net), "small"))
        totals.append((f"{'enthaltene USt.' if D else 'included VAT'} {VAT_RATE:g} %", m(r["total"] - net), "small"))
        notes.append((f"Alle Preise enthalten {VAT_RATE:g} % Umsatzsteuer." if D else f"All prices include {VAT_RATE:g} % VAT."))
    if storno:
        notes.append(("Diese Stornorechnung hebt die oben genannte Rechnung vollständig auf. Bereits gezahlte Beträge erstatten wir auf dem ursprünglichen Zahlungsweg."
                      if D else "This credit note fully cancels the invoice above. Payments already made will be refunded via the original payment method."))
    else:
        if r["paid_at"]:
            notes.append((f"Bezahlt am {date(r['paid_at'])}. Vielen Dank!" if D else f"Paid on {date(r['paid_at'])}. Thank you!"))
        if any(i.get("vendor") == "nexo" for i in items) and any(i.get("vendor") != "nexo" for i in items):
            notes.append(f"Die Vial-Cases kommen in einem eigenen Paket von {PARTNER}." if D else f"The vial cases arrive in a separate parcel from {PARTNER}.")
    notes.append("Sämtliche Peptide sind Forschungsreagenzien und ausschließlich für die In-vitro-Forschung bestimmt."
                 if D else "All peptides are research reagents for in-vitro research use only.")
    title = ("Stornorechnung" if D else "Credit note") if storno else ("Rechnung" if D else "Invoice")
    return pdfdoc.document(title, seller_lines(), buyer, meta, rows, totals, notes, seller_footer(lang), lang)


def invoice_attachment(oid):
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or not r["invoice_no"]:
        return None
    return [(f"{r['invoice_no']}.pdf", invoice_pdf(r), "application/pdf")]


def order_paid(oid, notify=True):
    """Alles, was bei Zahlungseingang passiert: Rechnung vergeben, Kunde bekommt Bestätigung mit Rechnung, Nexo erfährt es."""
    ensure_invoice(oid)
    row = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if notify and row:
        q = {"lines": json.loads(row["items"]), "shipping": row["shipping"], "total": row["total"], "discount": row["discount"],
             "code_label": row["affiliate_code"] or "", "express": bool(row["express"])}
        send_order_mails(oid, json.loads(row["address"]), q, row["method"], paid=True, lang=norm_lang(row["lang"]) or DEFAULT_LANG,
                         attachments=invoice_attachment(oid))
    notify_nexo(oid, paid=True)


def track_link(code):
    return TRACKING_URL.replace("{code}", code) if (TRACKING_URL and code) else ""


def send_ship_mail(oid, part="shop"):
    """Versandbestätigung an den Kunden. part="shop": Peptide (euer Paket), part="case": Case-Paket vom Case-Partner."""
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r:
        return
    lang = norm_lang(r["lang"]) or DEFAULT_LANG
    a = json.loads(r["address"] or "{}")
    items = json.loads(r["items"] or "[]")
    case = part == "case"
    mine = [i for i in items if is_case(i) == case]
    code = (r["case_tracking"] if case else r["tracking"]) or ""
    e = _html.escape
    lines = "\n".join(f"{i['qty']}× {i['name']} ({i['variant']})" for i in mine)
    rest = ""
    if not case and any(is_case(i) for i in items) and r["case_status"] != "shipped":
        rest = tr(lang, "ship_cases_later")
    elif case and any(not is_case(i) for i in items) and r["status"] != "shipped":
        rest = tr(lang, "ship_rest_later")
    link = track_link(code)
    track_t = (f"{tr(lang, 'tracking')}: {code}" + (f"\n{link}" if link else "")) if code else ""
    subject = tr(lang, "ship_case_subject" if case else "ship_subject", order=oid)
    text = (f"{tr(lang, 'hello', name=a.get('name', ''))}\n\n{tr(lang, 'ship_case_text' if case else 'ship_text', order=oid)}\n\n{lines}"
            + (f"\n\n{track_t}" if track_t else "") + (f"\n\n{rest}" if rest else "") + "\n\n" + SITE["name"])
    btn = (f"<p style='margin:18px 0'><a href='{e(link)}' style='background:#D9FF3F;color:#0a0f2e;text-decoration:none;font-weight:800;"
           f"padding:12px 20px;border-radius:999px;display:inline-block'>{e(tr(lang, 'track_btn'))}</a></p>") if link else ""
    body = (f"<p>{e(tr(lang, 'hello', name=a.get('name', '')))}</p><p>{e(tr(lang, 'ship_case_text' if case else 'ship_text', order=oid))}</p>"
            + "<p style='background:#f4f6fb;border-radius:12px;padding:14px;line-height:1.7;font-size:14px'>" + "<br>".join(e(f"{i['qty']}× {i['name']} ({i['variant']})") for i in mine) + "</p>"
            + (f"<p>{e(tr(lang, 'tracking'))}: <b style='font-family:monospace'>{e(code)}</b></p>{btn}" if code else "")
            + (f"<p style='color:#6a7095'>{e(rest)}</p>" if rest else ""))
    html = mail_layout(e(tr(lang, "order", order=oid)), body, lang)
    threading.Thread(target=send_mail, args=(r["email"], subject, text, html), daemon=True).start()


def stripe_post(path, fields):
    """Minimaler Stripe-REST-Aufruf ohne SDK."""
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + STRIPE_KEY, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def stripe_session(order_id, email, q, lang=DEFAULT_LANG):
    f = {"mode": "payment", "customer_email": email, "client_reference_id": order_id, "metadata[order_id]": order_id,
         "success_url": f"{BASE_URL}/{lang}/?order={order_id}&paid=1", "cancel_url": f"{BASE_URL}/{lang}/?order={order_id}&cancelled=1",
         "locale": lang}
    if q.get("discount"):
        # Rabatt exakt abbilden: eine Position mit dem Endbetrag
        f["line_items[0][quantity]"] = 1
        f["line_items[0][price_data][currency]"] = "eur"
        f["line_items[0][price_data][unit_amount]"] = q["total"]
        f["line_items[0][price_data][product_data][name]"] = tr(lang, "stripe_bundle", order=order_id, pct=f"{q['code']['pct']:g}")
        return stripe_post("checkout/sessions", f)
    i = 0
    for l in q["lines"]:
        f[f"line_items[{i}][quantity]"] = l["qty"]
        f[f"line_items[{i}][price_data][currency]"] = "eur"
        f[f"line_items[{i}][price_data][unit_amount]"] = l["unit"]
        f[f"line_items[{i}][price_data][product_data][name]"] = f"{l['name']} ({l['variant']})"
        i += 1
    if q["shipping"]:
        f[f"line_items[{i}][quantity]"] = 1
        f[f"line_items[{i}][price_data][currency]"] = "eur"
        f[f"line_items[{i}][price_data][unit_amount]"] = q["shipping"]
        f[f"line_items[{i}][price_data][product_data][name]"] = tr(lang, "shipping") + (f" ({tr(lang, 'express')})" if q.get("express") else "")
    return stripe_post("checkout/sessions", f)


def stripe_verify(payload, header, secret, tolerance=300):
    """Prüft die Stripe-Signatur (Header 'Stripe-Signature')."""
    import hmac
    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        sigs = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
        ts = int(parts["t"])
    except Exception:
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


@app.get("/api/config")
def shop_config():
    return jsonify(stripe=bool(STRIPE_KEY), prepayment=True, shipping={"DE": cents(SHIPPING_DE), "EU": cents(SHIPPING_EU)},
                   express={"DE": cents(EXPRESS_DE), "EU": cents(EXPRESS_EU)},
                   freeFrom=cents(FREE_SHIPPING_FROM) if FREE_SHIPPING_FROM else 0, countries=COUNTRIES)


@app.post("/api/quote")
def shop_quote():
    data = request.get_json(silent=True) or {}
    country = str(data.get("country", "DE"))
    try:
        if data.get("code") and limited("code:" + client_ip(), 40, 600):
            return jsonify(error="rate_limited"), 429
        q = quote(data.get("items"), country if country in COUNTRIES else "DE", data.get("code"), bool(data.get("express")))
    except ValueError:
        return jsonify(error="invalid_items"), 400
    for k in ("commission", "case_total", "nexo_pct", "nexo_fee"):
        q.pop(k, None)
    return jsonify(q)


@app.post("/api/code")
def code_check():
    """Prüft einen Affiliate-Code (für Warenkorb-Anzeige)."""
    if limited("code:" + client_ip(), 40, 600):
        return jsonify(error="rate_limited"), 429
    data = request.get_json(silent=True) or {}
    a = find_affiliate(data.get("code"))
    if not a:
        return jsonify(valid=False)
    return jsonify(valid=True, code=a["code"], pct=a["discount_pct"])


@app.post("/api/orders")
def order_create():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    if limited("order:" + client_ip(), 12, 3600):
        return jsonify(error="rate_limited"), 429
    data = request.get_json(silent=True) or {}
    addr, errs = clean_address(data.get("address"))
    if errs:
        return jsonify(error="invalid_address", fields=errs), 400
    if not data.get("acceptTerms") or not data.get("acceptResearch"):
        return jsonify(error="consent_required"), 400
    method = data.get("method")
    if method not in ("prepayment", "stripe") or (method == "stripe" and not STRIPE_KEY):
        return jsonify(error="invalid_method"), 400
    try:
        q = quote(data.get("items"), addr["country"], data.get("code"), bool(data.get("express")))
    except ValueError:
        return jsonify(error="invalid_items"), 400
    if not q["lines"]:
        return jsonify(error="empty_cart", skipped=q["skipped"]), 400
    if q["codeError"]:
        return jsonify(error="invalid_code"), 400
    q["code_label"] = q["code"]["code"] if q["code"] else ""
    lang = request_lang(data)
    u = current_user()
    oid = new_order_id()
    if not take_stock(q["lines"]):
        return jsonify(error="out_of_stock"), 409
    db().execute(
        "INSERT INTO orders(id,user_id,email,address,items,subtotal,shipping,total,method,status,created_at,discount,affiliate_code,commission,lang,"
        "case_total,nexo_pct,nexo_fee,case_status,stock_taken,express) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (oid, u["id"] if u else None, addr["email"], json.dumps(addr), json.dumps(q["lines"]), q["subtotal"], q["shipping"],
         q["total"], method, "awaiting_payment", now(), q["discount"], q["code_label"] or None, q["commission"], lang,
         q["case_total"], q["nexo_pct"], q["nexo_fee"], "open" if any(is_case(l) for l in q["lines"]) else None, 1 if q["express"] else 0))
    if u:
        db().execute("INSERT INTO carts(user_id,items,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET items='[]',updated_at=excluded.updated_at",
                     (u["id"], "[]", now()))
    db().commit()
    resp = {"order": oid, "total": q["total"], "discount": q["discount"], "method": method}
    if method == "stripe":
        try:
            sess = stripe_session(oid, addr["email"], q, lang)
        except Exception as exc:
            print(f"[STRIPE] {exc}", flush=True)
            return jsonify(error="payment_provider_error", order=oid), 502
        db().execute("UPDATE orders SET stripe_session=? WHERE id=?", (sess.get("id"), oid))
        db().commit()
        resp["redirect"] = sess.get("url")
    else:
        send_order_mails(oid, addr, q, "prepayment", lang=lang)
        notify_nexo(oid, paid=False)
        resp["bank"] = {**BANK, "reference": oid}
    return jsonify(resp)


@app.get("/api/orders")
def order_list():
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    rows = db().execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (u["id"],)).fetchall()
    out = []
    for r in rows:
        items = [{k: i.get(k) for k in ("slug", "name", "variant", "qty", "total", "vendor", "cfg")} for i in json.loads(r["items"])]
        out.append({"id": r["id"], "items": items, "total": r["total"], "subtotal": r["subtotal"], "shipping": r["shipping"],
                    "discount": r["discount"], "status": r["status"], "method": r["method"], "created": r["created_at"],
                    "tracking": r["tracking"], "tracking_url": track_link(r["tracking"] or ""), "case_status": r["case_status"],
                    "case_tracking": r["case_tracking"], "case_tracking_url": track_link(r["case_tracking"] or ""),
                    "invoice": bool(r["invoice_no"]) or r["status"] in ("paid", "shipped"), "storno": bool(r["storno_no"]), "express": bool(r["express"])})
    return jsonify(orders=out)


@app.get("/api/orders/<oid>/<kind>.pdf")
def customer_invoice(oid, kind):
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    if kind not in ("invoice", "storno"):
        return jsonify(error="not_found"), 404
    r = db().execute("SELECT id FROM orders WHERE id=? AND user_id=?", (oid, u["id"])).fetchone()
    if not r:
        return jsonify(error="not_found"), 404
    ensure_invoice(oid)
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r["invoice_no"] or (kind == "storno" and not r["storno_no"]):
        return jsonify(error="no_invoice"), 404
    return _pdf_response(invoice_pdf(r, kind == "storno"), f"{r['storno_no'] if kind == 'storno' else r['invoice_no']}.pdf")


@app.post("/api/stripe/webhook")
def stripe_webhook():
    payload = request.get_data()
    if not STRIPE_WHSEC or not stripe_verify(payload, request.headers.get("Stripe-Signature", ""), STRIPE_WHSEC):
        return jsonify(error="bad_signature"), 400
    evt = json.loads(payload)
    if evt.get("type") == "checkout.session.completed":
        obj = evt["data"]["object"]
        oid = (obj.get("metadata") or {}).get("order_id") or obj.get("client_reference_id")
        if oid and obj.get("payment_status") == "paid":
            row = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            if row and row["status"] != "paid":
                db().execute("UPDATE orders SET status='paid', paid_at=? WHERE id=?", (now(), oid))
                db().commit()
                order_paid(oid)
    return jsonify(ok=True)


# --------------------------------------------------------------- affiliates
def admin_ok():
    import hmac
    auth = request.headers.get("Authorization", "")
    return bool(ADMIN_TOKEN) and hmac.compare_digest(auth, "Bearer " + ADMIN_TOKEN)


def affiliate_stats(conn):
    rows = conn.execute("""SELECT a.code,a.name,a.email,a.discount_pct,a.commission_pct,a.active,
        COUNT(o.id) AS orders,
        COALESCE(SUM(CASE WHEN o.status='paid' THEN o.total-o.shipping END),0) AS revenue_paid,
        COALESCE(SUM(CASE WHEN o.status='paid' THEN o.commission END),0) AS commission_paid,
        COALESCE(SUM(CASE WHEN o.status='awaiting_payment' THEN o.commission END),0) AS commission_open
        FROM affiliates a LEFT JOIN orders o ON o.affiliate_code=a.code GROUP BY a.code ORDER BY a.code""").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/admin/affiliates")
def admin_affiliates():
    if not admin_ok():
        return jsonify(error="unauthorized"), 401
    return jsonify(affiliates=affiliate_stats(db()))


@app.post("/api/admin/affiliates")
def admin_affiliate_upsert():
    if not admin_ok():
        return jsonify(error="unauthorized"), 401
    d = request.get_json(silent=True) or {}
    code = str(d.get("code", "")).strip().upper()
    if not CODE_RE.match(code):
        return jsonify(error="invalid_code"), 400
    db().execute("""INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(code) DO UPDATE SET name=excluded.name,email=excluded.email,discount_pct=excluded.discount_pct,
        commission_pct=excluded.commission_pct,active=excluded.active""",
        (code, str(d.get("name") or code)[:80], str(d.get("email") or "")[:120] or None, float(d.get("discount", AFF_DISCOUNT)),
         float(d.get("commission", AFF_COMMISSION)), 1 if d.get("active", True) else 0, now()))
    db().commit()
    return jsonify(ok=True, code=code, link=f"{BASE_URL}/?ref={code}")


@app.post("/api/admin/orders/<oid>")
def admin_order_status(oid):
    if not admin_ok():
        return jsonify(error="unauthorized"), 401
    st = (request.get_json(silent=True) or {}).get("status")
    if st not in ("awaiting_payment", "paid", "shipped", "cancelled"):
        return jsonify(error="invalid_status"), 400
    cur = db().execute("UPDATE orders SET status=?, paid_at=CASE WHEN ?='paid' THEN ? ELSE paid_at END WHERE id=?", (st, st, now(), oid))
    db().commit()
    return jsonify(ok=cur.rowcount == 1)


# ----------------------------------------------------------------- Admin-Bereich
# /admin/ = Verwaltungsseite (server/admin.html).  Anmeldung mit Benutzername + Passwort, Passwörter nur als scrypt-Hash
# in der Datenbank.  Session-Cookie gilt nur für /admin (HttpOnly, SameSite=Strict), schreibende Aufrufe brauchen X-GP: 1.
ADMIN_HTML = os.path.join(HERE, "admin.html")


def current_admin_row():
    if "admin_row" in g:
        return g.admin_row
    raw = request.cookies.get(ADMIN_COOKIE)
    row = None
    if raw:
        row = db().execute("SELECT a.username, a.role, a.email FROM admin_sessions s JOIN admin_users a ON a.username=s.username "
                           "WHERE s.session_hash=? AND s.expires_at>?", (sha(raw), now())).fetchone()
    g.admin_row = row
    return row


def current_admin():
    row = current_admin_row()
    return row["username"] if row else None


def admin_role():
    row = current_admin_row()
    return (row["role"] or "owner") if row else None


def admin_guard(write=False, roles=("owner",)):
    """None wenn erlaubt, sonst eine Fehler-Antwort. Standard: nur das Shop-Team (owner)."""
    if write and not require_custom_header():
        return jsonify(error="forbidden"), 403
    if not current_admin():
        return jsonify(error="unauthorized"), 401
    if roles and admin_role() not in roles:
        return jsonify(error="forbidden"), 403
    return None


def order_row(r, full=False):
    addr = json.loads(r["address"] or "{}")
    o = {"id": r["id"], "email": r["email"], "name": addr.get("name", ""), "country": addr.get("country", ""),
         "total": r["total"], "subtotal": r["subtotal"], "shipping": r["shipping"], "discount": r["discount"],
         "method": r["method"], "status": r["status"], "created": r["created_at"], "paid": r["paid_at"],
         "code": r["affiliate_code"], "commission": r["commission"], "lang": r["lang"], "account": bool(r["user_id"])}
    items = json.loads(r["items"] or "[]")
    o["count"] = sum(int(i.get("qty", 1)) for i in items)
    o["cases"] = sum(int(i.get("qty", 1)) for i in items if is_case(i))
    o["peptides"] = o["count"] - o["cases"]
    o.update(case_total=r["case_total"], nexo_pct=r["nexo_pct"], nexo_fee=r["nexo_fee"], case_status=r["case_status"],
             case_tracking=r["case_tracking"], case_shipped=r["case_shipped_at"], invoice_no=r["invoice_no"], storno_no=r["storno_no"],
             tracking=r["tracking"], shipped=r["shipped_at"], express=bool(r["express"]))
    if full:
        o["items"] = items
        o["address"] = addr
    return o


def nexo_order_row(r, full=False):
    """Sicht für Nexo: nur Case-Positionen, Lieferdaten und der Zahlungsstatus. Keine Peptide, keine Partner-Codes, keine Gesamtsumme."""
    addr = json.loads(r["address"] or "{}")
    items = [i for i in json.loads(r["items"] or "[]") if is_case(i)]
    o = {"id": r["id"], "created": r["created_at"], "paid": r["paid_at"], "payment": "cancelled" if r["status"] == "cancelled" else
         ("paid" if r["status"] in ("paid", "shipped") else "open"), "name": addr.get("name", ""), "country": addr.get("country", ""),
         "count": sum(int(i.get("qty", 1)) for i in items), "case_total": r["case_total"], "nexo_pct": r["nexo_pct"],
         "nexo_fee": r["nexo_fee"], "payout": (r["case_total"] or 0) - (r["nexo_fee"] or 0), "case_status": r["case_status"] or "open",
         "case_tracking": r["case_tracking"], "case_shipped": r["case_shipped_at"], "express": bool(r["express"])}
    if full:
        o["items"] = [{k: i.get(k) for k in ("sku", "name", "variant", "qty", "unit", "total", "cfg")} for i in items]
        o["address"] = {k: addr.get(k, "") for k in ("name", "company", "street", "zip", "city", "country")}
        o["email"] = r["email"]
    return o


def nexo_recipients(conn=None):
    rows = (conn or db()).execute("SELECT email FROM admin_users WHERE role='nexo' AND email IS NOT NULL AND email!=''").fetchall()
    out = {e.strip().lower() for e in NEXO_NOTIFY.split(",") if e.strip()}
    return sorted(out | {r[0].lower() for r in rows})


def notify_nexo(oid, paid):
    """Nexo bekommt bei Case-Bestellungen eine Mail mit NUR den Case-Positionen und der Lieferadresse."""
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or not r["case_status"]:
        return
    to = nexo_recipients()
    if not to:
        return
    o = nexo_order_row(r, full=True)
    a = o["address"]
    lines = "\n".join(f"{i['qty']}× {i['name']} ({i['variant']})  {eur(i['total'])}" for i in o["items"])
    head = ("Zahlung eingegangen, bitte versenden." if paid else "Zahlung noch offen. Bitte erst versenden, wenn die Bestellung als bezahlt gemeldet ist.")
    if r["express"]:
        head = "EXPRESSVERSAND gebucht, bitte bevorzugt bearbeiten. " + head
    t = (f"Case-Bestellung {oid}\n{head}\n\n{lines}\n\nCase-Warenwert {eur(o['case_total'])} · Provision Shop {eur(o['nexo_fee'])} "
         f"({(o['nexo_pct'] or 0):g} %) · Auszahlung an Nexo {eur(o['payout'])}\n\nLieferadresse:\n{a['name']}\n"
         + (f"{a['company']}\n" if a["company"] else "") + f"{a['street']}\n{a['zip']} {a['city']}\n{COUNTRIES.get(a['country'], a['country'])}\n\n"
         f"Alle Case-Bestellungen: {BASE_URL}/admin/")
    e = _html.escape
    body = "<pre style='font:14px/1.5 Arial,Helvetica,sans-serif;white-space:pre-wrap'>" + e(t) + "</pre>"
    subject = f"[{SITE['name']} × {PARTNER_SHORT}]{' EXPRESS' if r['express'] else ''} {'Bezahlt' if paid else 'Neu'}: {oid}"
    for addr in to:
        threading.Thread(target=send_mail, args=(addr, subject, t, body), daemon=True).start()


@app.get("/admin")
def admin_redirect():
    return redirect("/admin/", 301)


@app.get("/admin/")
def admin_page():
    with open(ADMIN_HTML, encoding="utf-8") as fh:
        resp = app.response_class(fh.read(), mimetype="text/html")
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                               "font-src 'self'; img-src 'self' data:; "
                                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    return resp


@app.post("/admin/api/login")
def admin_login():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    d = request.get_json(silent=True) or {}
    user = str(d.get("user", "")).strip()[:40]
    pw = str(d.get("password", ""))[:200]
    # nur Fehlversuche zählen: 8 pro IP bzw. 10 pro Benutzername in 15 Minuten
    k_ip, k_user = "adminfail:" + client_ip(), "adminfailuser:" + user.lower()
    if recent_hits(k_ip, 900) >= 8 or recent_hits(k_user, 900) >= 10:
        return jsonify(error="rate_limited"), 429
    row = db().execute("SELECT username,pw_hash,totp_on,totp_secret,totp_last FROM admin_users WHERE username=?", (user,)).fetchone()
    # immer einen Hash prüfen, damit die Antwortzeit nicht verrät, ob es den Namen gibt
    ok = check_password_hash(row["pw_hash"] if row else DUMMY_HASH, pw) and row is not None
    if not ok:
        limited(k_ip, 10**6, 900)
        limited(k_user, 10**6, 900)
        print(f"[ADMIN] fehlgeschlagene Anmeldung für '{user}' von {client_ip()}", flush=True)
        return jsonify(error="invalid_login"), 401
    if row["totp_on"]:
        code = re.sub(r"\s", "", str(d.get("code", "")))
        if not code:
            return jsonify(error="totp_required"), 401
        step = totp_check(row["totp_secret"], code, row["totp_last"])
        if not step:
            limited(k_ip, 10**6, 900)
            limited(k_user, 10**6, 900)
            print(f"[ADMIN] falscher 2FA-Code für '{user}' von {client_ip()}", flush=True)
            return jsonify(error="totp_invalid"), 401
        db().execute("UPDATE admin_users SET totp_last=? WHERE username=?", (step, row["username"]))
    raw = secrets.token_urlsafe(32)
    db().execute("DELETE FROM admin_sessions WHERE expires_at<?", (now(),))
    db().execute("INSERT INTO admin_sessions(session_hash,username,expires_at,created_at) VALUES(?,?,?,?)",
                 (sha(raw), row["username"], now() + ADMIN_TTL, now()))
    db().execute("UPDATE admin_users SET last_login=? WHERE username=?", (now(), row["username"]))
    db().commit()
    resp = jsonify(ok=True, user=row["username"])
    resp.set_cookie(ADMIN_COOKIE, raw, max_age=ADMIN_TTL, httponly=True, secure=COOKIE_SECURE, samesite="Strict", path="/admin")
    return resp


# ---- Zwei-Faktor-Anmeldung (TOTP, RFC 6238: 6 Ziffern, 30 Sekunden, z. B. Google Authenticator, Authy, 1Password)
import base64 as _b64
import hmac as _hmac
import struct as _struct


def totp_at(secret, step):
    key = _b64.b32decode(secret + "=" * (-len(secret) % 8))
    h = _hmac.new(key, _struct.pack(">Q", step), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(_struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def totp_check(secret, code, last=0):
    """Gibt den Zeitschritt zurück, wenn der Code passt (±30 s Toleranz) und noch nicht benutzt wurde, sonst 0."""
    if not secret or not re.match(r"^\d{6}$", code or ""):
        return 0
    t = int(time.time() // 30)
    for step in (t, t - 1, t + 1):
        if step > (last or 0) and _hmac.compare_digest(totp_at(secret, step), code):
            return step
    return 0


def qr_svg(text):
    import qrcodegen
    q = qrcodegen.QrCode.encode_text(text, qrcodegen.QrCode.Ecc.MEDIUM)
    n, b = q.get_size(), 4
    path = "".join(f"M{x + b},{y + b}h1v1h-1z" for y in range(n) for x in range(n) if q.get_module(x, y))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n + 2 * b} {n + 2 * b}" shape-rendering="crispEdges" width="200" height="200">'
            f'<rect width="100%" height="100%" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


@app.post("/admin/api/2fa/setup")
def admin_2fa_setup():
    err = admin_guard(write=True, roles=ROLES)
    if err:
        return err
    user = current_admin()
    if db().execute("SELECT totp_on FROM admin_users WHERE username=?", (user,)).fetchone()[0]:
        return jsonify(error="already_on"), 409
    secret = _b64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    db().execute("UPDATE admin_users SET totp_secret=?, totp_on=0 WHERE username=?", (secret, user))
    db().commit()
    import urllib.parse
    uri = f"otpauth://totp/{urllib.parse.quote(SITE['name'] + ':' + user)}?secret={secret}&issuer={urllib.parse.quote(SITE['name'])}&digits=6&period=30"
    return jsonify(secret=" ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), uri=uri, svg=qr_svg(uri))


@app.post("/admin/api/2fa/enable")
def admin_2fa_enable():
    err = admin_guard(write=True, roles=ROLES)
    if err:
        return err
    user = current_admin()
    if limited("2fa:" + user.lower(), 10, 900):
        return jsonify(error="rate_limited"), 429
    row = db().execute("SELECT totp_secret FROM admin_users WHERE username=?", (user,)).fetchone()
    step = totp_check(row["totp_secret"], re.sub(r"\s", "", str((request.get_json(silent=True) or {}).get("code", ""))))
    if not step:
        return jsonify(error="totp_invalid"), 400
    db().execute("UPDATE admin_users SET totp_on=1, totp_last=? WHERE username=?", (step, user))
    # andere Sitzungen dieses Zugangs beenden
    db().execute("DELETE FROM admin_sessions WHERE username=? AND session_hash!=?", (user, sha(request.cookies.get(ADMIN_COOKIE, ""))))
    db().commit()
    print(f"[ADMIN] {user} hat die Zwei-Faktor-Anmeldung eingeschaltet", flush=True)
    return jsonify(ok=True)


@app.post("/admin/api/2fa/disable")
def admin_2fa_disable():
    err = admin_guard(write=True, roles=ROLES)
    if err:
        return err
    user = current_admin()
    if limited("2fa:" + user.lower(), 10, 900):
        return jsonify(error="rate_limited"), 429
    d = request.get_json(silent=True) or {}
    row = db().execute("SELECT pw_hash, totp_secret, totp_last FROM admin_users WHERE username=?", (user,)).fetchone()
    if not check_password_hash(row["pw_hash"], str(d.get("password", ""))) or not totp_check(row["totp_secret"], re.sub(r"\s", "", str(d.get("code", ""))), row["totp_last"]):
        return jsonify(error="wrong"), 400
    db().execute("UPDATE admin_users SET totp_on=0, totp_secret=NULL WHERE username=?", (user,))
    db().commit()
    print(f"[ADMIN] {user} hat die Zwei-Faktor-Anmeldung ausgeschaltet", flush=True)
    return jsonify(ok=True)


@app.post("/admin/api/logout")
def admin_logout():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    raw = request.cookies.get(ADMIN_COOKIE)
    if raw:
        db().execute("DELETE FROM admin_sessions WHERE session_hash=?", (sha(raw),))
        db().commit()
    resp = jsonify(ok=True)
    resp.delete_cookie(ADMIN_COOKIE, path="/admin")
    return resp


@app.get("/admin/api/me")
def admin_me():
    user = current_admin()
    if not user:
        return jsonify(error="unauthorized"), 401
    totp = db().execute("SELECT totp_on FROM admin_users WHERE username=?", (user,)).fetchone()[0]
    return jsonify(user=user, role=admin_role(), email=current_admin_row()["email"] or "", totp=bool(totp), stripe=bool(STRIPE_KEY), mail="dev" if DEV_MODE else "smtp", base=BASE_URL)


@app.get("/admin/api/overview")
def admin_overview():
    err = admin_guard()
    if err:
        return err
    c = db()
    t30 = now() - 30 * 86400
    t_day = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0
    days = []
    for i in range(29, -1, -1):
        start = t_day - i * 86400
        days.append({"day": start, "revenue": one("SELECT SUM(total) FROM orders WHERE status IN ('paid','shipped') AND created_at>=? AND created_at<?", start, start + 86400),
                     "orders": one("SELECT COUNT(*) FROM orders WHERE status!='cancelled' AND created_at>=? AND created_at<?", start, start + 86400),
                     "signups": one("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?", start, start + 86400),
                     "confirmed": one("SELECT COUNT(*) FROM users WHERE confirmed_at IS NOT NULL AND created_at>=? AND created_at<?", start, start + 86400)})
    return jsonify(
        revenue_total=one("SELECT SUM(total) FROM orders WHERE status IN ('paid','shipped')"),
        revenue_30=one("SELECT SUM(total) FROM orders WHERE status IN ('paid','shipped') AND created_at>=?", t30),
        orders_30=one("SELECT COUNT(*) FROM orders WHERE status!='cancelled' AND created_at>=?", t30),
        orders_today=one("SELECT COUNT(*) FROM orders WHERE created_at>=?", t_day),
        open_count=one("SELECT COUNT(*) FROM orders WHERE status='awaiting_payment'"),
        open_sum=one("SELECT SUM(total) FROM orders WHERE status='awaiting_payment'"),
        to_ship=one("SELECT COUNT(*) FROM orders WHERE status='paid'"),
        express_open=one("SELECT COUNT(*) FROM orders WHERE status='paid' AND express=1"),
        customers=one("SELECT COUNT(*) FROM users WHERE confirmed_at IS NOT NULL"),
        commission_open=one("SELECT SUM(commission) FROM orders WHERE status='awaiting_payment'"),
        commission_paid=one("SELECT SUM(commission) FROM orders WHERE status IN ('paid','shipped')"),
        signups={"d7": one("SELECT COUNT(*) FROM users WHERE created_at>=?", now() - 7 * 86400),
                 "d30": one("SELECT COUNT(*) FROM users WHERE created_at>=?", t30),
                 "c30": one("SELECT COUNT(*) FROM users WHERE created_at>=? AND confirmed_at IS NOT NULL", t30),
                 "prev30": one("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?", t30 - 30 * 86400, t30),
                 "buyers30": one("SELECT COUNT(DISTINCT u.id) FROM users u JOIN orders o ON o.user_id=u.id WHERE u.created_at>=? AND o.status!='cancelled'", t30),
                 "total": one("SELECT COUNT(*) FROM users WHERE confirmed_at IS NOT NULL")},
        events=[event_admin(r) for r in c.execute("SELECT * FROM events WHERE published=1 AND ends_at>? ORDER BY starts_at LIMIT 4", (now(),))],
        nexo=nexo_summary(c), days=days,
        low_stock=[dict(r) for r in c.execute("SELECT slug, vi, qty FROM stock WHERE qty<=? ORDER BY qty", (STOCK_LOW,))],
        last_backup=(backup_list() or [{"time": None}])[0]["time"])


def nexo_summary(c):
    """Abrechnung Cases: bezahlte Bestellungen zählen, offene separat."""
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0
    paid = "status IN ('paid','shipped') AND case_status IS NOT NULL AND case_status!='cancelled'"
    months = [dict(r) for r in c.execute(f"""SELECT strftime('%Y-%m',created_at,'unixepoch','localtime') AS month, COUNT(*) AS orders,
        SUM(case_total) AS revenue, SUM(nexo_fee) AS fee, SUM(case_total-nexo_fee) AS payout FROM orders WHERE {paid}
        GROUP BY month ORDER BY month DESC LIMIT 24""")]
    pays = {r["month"]: dict(r) for r in c.execute("SELECT * FROM nexo_payouts")}
    cur_month = time.strftime("%Y-%m")
    for m in months:
        pr = pays.get(m["month"]) or {}
        m.update(paid_at=pr.get("paid_at"), credit_no=pr.get("credit_no"), paid_amount=pr.get("amount"), closed=m["month"] < cur_month)
    return {"pct": nexo_pct(c), "revenue": one(f"SELECT SUM(case_total) FROM orders WHERE {paid}"),
            "fee": one(f"SELECT SUM(nexo_fee) FROM orders WHERE {paid}"),
            "payout": one(f"SELECT SUM(case_total-nexo_fee) FROM orders WHERE {paid}"),
            "orders": one(f"SELECT COUNT(*) FROM orders WHERE {paid}"),
            "open_count": one("SELECT COUNT(*) FROM orders WHERE status='awaiting_payment' AND case_status IS NOT NULL"),
            "open_sum": one("SELECT SUM(case_total) FROM orders WHERE status='awaiting_payment' AND case_status IS NOT NULL"),
            "to_ship": one("SELECT COUNT(*) FROM orders WHERE status IN ('paid','shipped') AND case_status='open'"),
            "revenue_30": one(f"SELECT SUM(case_total) FROM orders WHERE {paid} AND created_at>=?", now() - 30 * 86400),
            "orders_30": one("SELECT COUNT(*) FROM orders WHERE case_status IS NOT NULL AND status!='cancelled' AND created_at>=?", now() - 30 * 86400),
            "new_24h": one("SELECT COUNT(*) FROM orders WHERE case_status IS NOT NULL AND created_at>=?", now() - 86400),
            "recent": [nexo_order_row(r) for r in c.execute("SELECT * FROM orders WHERE case_status IS NOT NULL ORDER BY created_at DESC LIMIT 8")],
            "months": months}


@app.get("/admin/api/orders")
def admin_orders():
    err = admin_guard()
    if err:
        return err
    st = request.args.get("status", "")
    q = request.args.get("q", "").strip()[:80]
    sql, args = "SELECT * FROM orders WHERE 1=1", []
    if st in ORDER_STATUSES:
        sql += " AND status=?"
        args.append(st)
    if request.args.get("cases") == "1":
        sql += " AND case_status IS NOT NULL"
    if st == "express":
        sql += " AND express=1 AND status IN ('awaiting_payment','paid')"
    if q:
        sql += " AND (id LIKE ? OR email LIKE ? OR address LIKE ? OR IFNULL(affiliate_code,'') LIKE ?)"
        args += [f"%{q}%"] * 4
    # Express-Bestellungen, die noch versendet werden müssen, stehen immer oben
    sql += " ORDER BY CASE WHEN express=1 AND status='paid' THEN 0 ELSE 1 END, created_at DESC LIMIT 300"
    return jsonify(orders=[order_row(r) for r in db().execute(sql, args)])


@app.get("/admin/api/orders/<oid>")
def admin_order_detail(oid):
    err = admin_guard()
    if err:
        return err
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r:
        return jsonify(error="not_found"), 404
    return jsonify(order=order_row(r, full=True))


@app.post("/admin/api/orders/<oid>/status")
def admin_order_set_status(oid):
    err = admin_guard(write=True)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    st = d.get("status")
    if st not in ORDER_STATUSES:
        return jsonify(error="invalid_status"), 400
    before = db().execute("SELECT status, case_status, storno_no, tracking FROM orders WHERE id=?", (oid,)).fetchone()
    if not before:
        return jsonify(error="not_found"), 404
    if before["storno_no"] and st != "cancelled":
        return jsonify(error="storno_exists"), 409
    tracking = str(d.get("tracking", before["tracking"] or "")).strip()[:80] or None
    db().execute("UPDATE orders SET tracking=? WHERE id=?", (tracking, oid))
    cur = db().execute("UPDATE orders SET status=?, paid_at=CASE WHEN ?='paid' AND paid_at IS NULL THEN ? ELSE paid_at END WHERE id=?",
                       (st, st, now(), oid))
    if before["case_status"]:
        if st == "cancelled" and before["case_status"] == "open":
            db().execute("UPDATE orders SET case_status='cancelled' WHERE id=?", (oid,))
        elif st != "cancelled" and before["case_status"] == "cancelled":
            db().execute("UPDATE orders SET case_status='open' WHERE id=?", (oid,))
    db().commit()
    print(f"[ADMIN] {current_admin()} setzt {oid} auf {st}", flush=True)
    if st in ("paid", "shipped") and before["status"] in ("awaiting_payment", "cancelled"):
        order_paid(oid)
    if st == "shipped" and before["status"] != "shipped":
        db().execute("UPDATE orders SET shipped_at=? WHERE id=?", (now(), oid))
        db().commit()
        if d.get("notify", True):
            send_ship_mail(oid, "shop")
    if st == "cancelled" and before["status"] != "cancelled":
        give_back_stock(oid)
    elif st != "cancelled" and before["status"] == "cancelled":
        r = db().execute("SELECT items FROM orders WHERE id=?", (oid,)).fetchone()
        lines = json.loads(r["items"])
        for l in lines:  # wieder aktiv: Bestand erneut abziehen (darf hier ins Minus, die Ware ist ja zugesagt)
            if not is_case(l):
                db().execute("UPDATE stock SET qty=qty-? WHERE slug=? AND vi=?", (l["qty"], l["slug"], l["vi"]))
        db().execute("UPDATE orders SET stock_taken=1 WHERE id=?", (oid,))
        db().commit()
    if st == "cancelled":
        r = db().execute("SELECT invoice_no, storno_no FROM orders WHERE id=?", (oid,)).fetchone()
        if r["invoice_no"] and not r["storno_no"]:
            db().execute("UPDATE orders SET storno_no=?, storno_at=? WHERE id=?", (next_number("ST"), now(), oid))
            db().commit()
    return jsonify(ok=cur.rowcount == 1)


def _pdf_response(data, name):
    resp = app.response_class(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'inline; filename="{name}"'
    return resp


@app.get("/admin/api/orders/<oid>/<kind>.pdf")
def admin_invoice(oid, kind):
    err = admin_guard()
    if err:
        return err
    if kind not in ("invoice", "storno"):
        return jsonify(error="not_found"), 404
    ensure_invoice(oid)
    r = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or not r["invoice_no"] or (kind == "storno" and not r["storno_no"]):
        return jsonify(error="no_invoice"), 404
    return _pdf_response(invoice_pdf(r, kind == "storno"), f"{r['storno_no'] if kind == 'storno' else r['invoice_no']}.pdf")


@app.get("/admin/api/orders.csv")
def admin_orders_csv():
    err = admin_guard()
    if err:
        return err
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Bestellnummer", "Datum", "Status", "Zahlart", "E-Mail", "Name", "Firma", "Straße", "PLZ", "Ort", "Land",
                "Positionen", "Zwischensumme", "Rabatt", "Versand", "Summe", "Code", "Provision", "Sprache",
                "Case-Warenwert", "Provision Shop (Cases)", "Auszahlung Nexo", "Case-Status", "Sendungsnummer Case"])
    for r in db().execute("SELECT * FROM orders ORDER BY created_at DESC"):
        a = json.loads(r["address"] or "{}")
        items = "; ".join(f"{i.get('qty')}x {i.get('name')} ({i.get('variant')})" for i in json.loads(r["items"] or "[]"))
        money = lambda c: f"{(c or 0) / 100:.2f}".replace(".", ",")
        w.writerow([r["id"], time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created_at"])), r["status"], r["method"], r["email"],
                    a.get("name", ""), a.get("company", ""), a.get("street", ""), a.get("zip", ""), a.get("city", ""), a.get("country", ""),
                    items, money(r["subtotal"]), money(r["discount"]), money(r["shipping"]), money(r["total"]),
                    r["affiliate_code"] or "", money(r["commission"]), r["lang"],
                    money(r["case_total"]) if r["case_status"] else "", money(r["nexo_fee"]) if r["case_status"] else "",
                    money((r["case_total"] or 0) - (r["nexo_fee"] or 0)) if r["case_status"] else "", r["case_status"] or "", r["case_tracking"] or ""])
    resp = app.response_class("﻿" + buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename={SITE['id']}-bestellungen-{time.strftime('%Y-%m-%d')}.csv"
    return resp


@app.get("/admin/api/affiliates")
def admin_affiliates_list():
    err = admin_guard()
    if err:
        return err
    rows = affiliate_stats(db())
    for r in rows:
        r["link"] = f"{BASE_URL}/?ref={r['code']}"
    return jsonify(affiliates=rows, defaults={"discount": AFF_DISCOUNT, "commission": AFF_COMMISSION})


@app.post("/admin/api/affiliates")
def admin_affiliates_save():
    err = admin_guard(write=True)
    if err:
        return err
    body, status = save_affiliate(request.get_json(silent=True) or {}, current_admin())
    return jsonify(body), status


@app.get("/admin/api/customers")
def admin_customers():
    err = admin_guard()
    if err:
        return err
    rows = db().execute("""SELECT u.email,u.created_at,u.confirmed_at,COUNT(o.id) AS orders,
        COALESCE(SUM(CASE WHEN o.status IN ('paid','shipped') THEN o.total END),0) AS revenue, MAX(o.created_at) AS last_order
        FROM users u LEFT JOIN orders o ON o.user_id=u.id GROUP BY u.id ORDER BY u.created_at DESC LIMIT 500""").fetchall()
    return jsonify(customers=[dict(r) for r in rows])


@app.get("/admin/api/admins")
def admin_admins():
    err = admin_guard()
    if err:
        return err
    rows = db().execute("SELECT username,last_login,email,role,totp_on FROM admin_users ORDER BY username COLLATE NOCASE").fetchall()
    return jsonify(admins=[dict(r) for r in rows], me=current_admin())


@app.post("/admin/api/password")
def admin_password():
    err = admin_guard(write=True, roles=ROLES)
    if err:
        return err
    user = current_admin()
    d = request.get_json(silent=True) or {}
    old, new = str(d.get("old", "")), str(d.get("new", ""))
    if limited("adminpw:" + user.lower(), 6, 900):
        return jsonify(error="rate_limited"), 429
    row = db().execute("SELECT pw_hash FROM admin_users WHERE username=?", (user,)).fetchone()
    if not row or not check_password_hash(row["pw_hash"], old):
        return jsonify(error="wrong_password"), 400
    if len(new) < 10 or new.lower() == user.lower():
        return jsonify(error="weak_password"), 400
    db().execute("UPDATE admin_users SET pw_hash=? WHERE username=?", (generate_password_hash(new), user))
    # alle anderen Sitzungen dieses Zugangs beenden
    db().execute("DELETE FROM admin_sessions WHERE username=? AND session_hash!=?", (user, sha(request.cookies.get(ADMIN_COOKIE, ""))))
    db().commit()
    print(f"[ADMIN] {user} hat das Passwort geändert", flush=True)
    return jsonify(ok=True)


# ------------------------------------------------- Fehler aus dem Browser
@app.post("/api/err")
def client_error():
    """Die Seite meldet JavaScript-Fehler hierher (ohne Personendaten). Gleiche Fehler werden zusammengezählt."""
    if limited("err:" + client_ip(), 20, 600):
        return ("", 204)
    try:
        d = json.loads(request.get_data(as_text=True) or "{}")
    except ValueError:
        return ("", 204)
    msg = str(d.get("m", ""))[:300]
    if not msg:
        return ("", 204)
    src = re.sub(r"[?#].*$", "", str(d.get("s", "")))[:200]
    try:
        line = int(d.get("l", 0))
    except (TypeError, ValueError):
        line = 0
    key = sha(f"{msg}|{src}|{line}")[:24]
    ua = request.headers.get("User-Agent", "")
    if BOT_RE.search(ua):
        return ("", 204)
    browser = ("Safari iOS" if "iPhone" in ua or "iPad" in ua else "Android" if "Android" in ua else "Firefox" if "Firefox" in ua
               else "Edge" if "Edg/" in ua else "Chrome" if "Chrome" in ua else "Safari" if "Safari" in ua else "andere")
    db().execute("""INSERT INTO client_errors(key,msg,src,line,stack,path,ua,count,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,1,?,?)
        ON CONFLICT(key) DO UPDATE SET count=count+1, last_seen=excluded.last_seen, ua=excluded.ua, path=excluded.path""",
                 (key, msg, src, line, str(d.get("st", ""))[:1200], re.sub(r"[^a-z0-9/_-]", "", str(d.get("p", "")).lower())[:80], browser, now(), now()))
    db().execute("DELETE FROM client_errors WHERE last_seen<?", (now() - 30 * 86400,))
    db().commit()
    return ("", 204)


@app.get("/admin/api/errors")
def admin_errors():
    err = admin_guard()
    if err:
        return err
    rows = db().execute("SELECT * FROM client_errors ORDER BY last_seen DESC LIMIT 50").fetchall()
    return jsonify(errors=[dict(r) for r in rows])


@app.post("/admin/api/errors/clear")
def admin_errors_clear():
    err = admin_guard(write=True)
    if err:
        return err
    db().execute("DELETE FROM client_errors")
    db().commit()
    return jsonify(ok=True)


# ------------------------------------------------- Statistik ohne Cookies
# Zählt Seitenaufrufe und ein paar Ereignisse (in den Warenkorb, Kasse geöffnet, Suche).  Keine Cookies, keine IP-Adressen:
# Für „Besucher pro Tag“ wird aus IP + Browser-Kennung + einem täglich neuen Zufallswert eine Prüfsumme gebildet; die
# Prüfsummen werden am nächsten Tag gelöscht, übrig bleibt nur die Anzahl.  Do-Not-Track / GPC wird respektiert.
STAT_EVENTS = ("view", "cart", "checkout", "search", "giveaway")
BOT_RE = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|python|curl|wget|httpclient|monitor", re.I)
_stat_salt = {"day": "", "salt": ""}


def stat_salt(day):
    if _stat_salt["day"] != day:
        db().execute("DELETE FROM visitors WHERE day<?", (day,))
        db().execute("DELETE FROM settings WHERE key LIKE 'stat_salt_%' AND key!=?", ("stat_salt_" + day,))
        salt = get_setting("stat_salt_" + day)
        if not salt:
            salt = secrets.token_hex(16)
            db().execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", ("stat_salt_" + day, salt))
            salt = get_setting("stat_salt_" + day)
        _stat_salt.update(day=day, salt=salt)
    return _stat_salt["salt"]


@app.post("/api/t")
def stat_hit():
    ua = request.headers.get("User-Agent", "")
    if (request.headers.get("DNT") == "1" or request.headers.get("Sec-GPC") == "1" or not ua or BOT_RE.search(ua)
            or limited("stat:" + client_ip(), 120, 600)):
        return ("", 204)
    try:
        d = json.loads(request.get_data(as_text=True) or "{}")
    except ValueError:
        return ("", 204)
    ev = d.get("e") if d.get("e") in STAT_EVENTS else "view"
    path = re.sub(r"[^a-z0-9/_-]", "", str(d.get("p", "/")).lower())[:80] or "/"
    if ev != "view":
        path = "#" + ev
    ref = re.sub(r"[^a-z0-9.-]", "", str(d.get("r", "")).lower())[:60]
    if ref.startswith("www."):
        ref = ref[4:]
    host = re.sub(r"^https?://", "", BASE_URL).split("/")[0].split(":")[0].lower()
    if ref in (host, "localhost", "127.0.0.1"):
        ref = ""
    try:
        w = int(d.get("w", 0))
    except (TypeError, ValueError):
        w = 0
    device = "Handy" if 0 < w < 760 else "Tablet" if w < 1100 and w else "Desktop"
    lang = norm_lang(d.get("l")) or ""
    day = time.strftime("%Y-%m-%d")
    c = db()
    c.execute("INSERT INTO pageviews(day,path,ref,device,lang,views) VALUES(?,?,?,?,?,1) "
              "ON CONFLICT(day,path,ref,device,lang) DO UPDATE SET views=views+1", (day, path, ref, device, lang))
    if ev == "view":
        h = sha(stat_salt(day) + client_ip() + ua)[:20]
        if c.execute("INSERT OR IGNORE INTO visitors(day,hash) VALUES(?,?)", (day, h)).rowcount:
            c.execute("INSERT INTO visits_daily(day,visitors) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET visitors=visitors+1", (day,))
    c.commit()
    return ("", 204)


@app.get("/admin/api/stats")
def admin_stats():
    err = admin_guard()
    if err:
        return err
    try:
        days = max(1, min(365, int(request.args.get("days", 30))))
    except ValueError:
        days = 30
    c = db()
    start = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    t0 = int(time.mktime(time.strptime(start, "%Y-%m-%d")))
    one = lambda sql, *a: (c.execute(sql, a).fetchone() or [0])[0] or 0
    rows = lambda sql, *a: [dict(r) for r in c.execute(sql, a)]
    series = []
    for i in range(days):
        d = time.strftime("%Y-%m-%d", time.localtime(t0 + i * 86400 + 3600))
        series.append({"day": d, "visitors": one("SELECT visitors FROM visits_daily WHERE day=?", d),
                       "views": one("SELECT SUM(views) FROM pageviews WHERE day=? AND path NOT LIKE '#%'", d)})
    ev = {e: one("SELECT SUM(views) FROM pageviews WHERE day>=? AND path=?", start, "#" + e) for e in ("cart", "checkout", "search")}
    orders = one("SELECT COUNT(*) FROM orders WHERE created_at>=? AND status!='cancelled'", t0)
    visitors = one("SELECT SUM(visitors) FROM visits_daily WHERE day>=?", start)
    return jsonify(
        days=series, visitors=visitors, views=one("SELECT SUM(views) FROM pageviews WHERE day>=? AND path NOT LIKE '#%'", start),
        funnel={"visitors": visitors, "cart": ev["cart"], "checkout": ev["checkout"], "orders": orders}, searches=ev["search"],
        pages=rows("SELECT path, SUM(views) AS views FROM pageviews WHERE day>=? AND path NOT LIKE '#%' GROUP BY path ORDER BY views DESC LIMIT 12", start),
        refs=rows("SELECT ref, SUM(views) AS views FROM pageviews WHERE day>=? AND ref!='' AND path NOT LIKE '#%' GROUP BY ref ORDER BY views DESC LIMIT 10", start),
        devices=rows("SELECT device, SUM(views) AS views FROM pageviews WHERE day>=? AND path NOT LIKE '#%' GROUP BY device ORDER BY views DESC", start),
        langs=rows("SELECT lang, SUM(views) AS views FROM pageviews WHERE day>=? AND path NOT LIKE '#%' AND lang!='' GROUP BY lang ORDER BY views DESC", start))


# ------------------------------------------------- Events: öffentlich
@app.get("/api/events")
def public_events():
    t = now()
    u = current_user()
    lang = request_lang()
    rows = db().execute("SELECT * FROM events WHERE published=1 AND starts_at<=? AND ends_at>? ORDER BY ends_at", (t, t)).fetchall()
    return jsonify(events=[event_public(r, lang, u) for r in rows], now=t)


@app.post("/api/events/<int:eid>/enter")
def event_enter(eid):
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    if limited("enter:" + client_ip(), 20, 600):
        return jsonify(error="rate_limited"), 429
    t = now()
    r = db().execute("SELECT * FROM events WHERE id=? AND kind='giveaway' AND published=1 AND starts_at<=? AND ends_at>?", (eid, t, t)).fetchone()
    if not r:
        return jsonify(error="not_active"), 404
    if (r["source"] or "entries") == "orders":
        return jsonify(error="orders_only"), 409
    if r["requires_order"] and not db().execute(
            "SELECT 1 FROM orders WHERE user_id=? AND status IN ('paid','shipped') AND created_at>=? AND created_at<?", (u["id"], r["starts_at"], r["ends_at"])).fetchone():
        return jsonify(error="order_required"), 409
    db().execute("INSERT OR IGNORE INTO giveaway_entries(event_id,user_id,email,created_at) VALUES(?,?,?,?)", (eid, u["id"], u["email"], t))
    db().commit()
    return jsonify(ok=True)


# ------------------------------------------------- Events: Admin
def _ts(v):
    """'2026-10-10T18:00' (Ortszeit aus dem Formular) -> Unix-Zeit"""
    try:
        return int(time.mktime(time.strptime(str(v)[:16], "%Y-%m-%dT%H:%M")))
    except (TypeError, ValueError):
        return None


def event_admin(r):
    c = db()
    o = dict(r)
    o["slugs"] = json.loads(r["slugs"] or "[]")
    o["prod_pct"] = json.loads(r["prod_pct"] or "{}")
    t = now()
    o["state"] = "draft" if not r["published"] else "planned" if r["starts_at"] > t else "running" if r["ends_at"] > t else "ended"
    if r["kind"] == "giveaway":
        tk = giveaway_tickets(r)
        o["entries"] = len(tk)
        o["people"] = len({x["email"] for x in tk})
        o["drawn"] = c.execute("SELECT COUNT(*) FROM giveaway_winners WHERE event_id=?", (r["id"],)).fetchone()[0]
    else:
        orders, revenue, items, saved = 0, 0, 0, 0
        for row in c.execute("SELECT items, total, shipping FROM orders WHERE status!='cancelled' AND created_at>=? AND created_at<?", (r["starts_at"], r["ends_at"])):
            ls = [l for l in json.loads(row["items"]) if l.get("event_id") == r["id"]]
            if ls:
                orders += 1
                revenue += row["total"] - row["shipping"]
                items += sum(l["qty"] for l in ls)
                saved += sum((l.get("orig_unit", l["unit"]) - l["unit"]) * l["qty"] for l in ls)
        o.update(orders=orders, revenue=revenue, items=items, saved=saved)
    return o


@app.get("/admin/api/events")
def admin_events():
    err = admin_guard()
    if err:
        return err
    rows = db().execute("SELECT * FROM events ORDER BY CASE WHEN ends_at>? THEN 0 ELSE 1 END, starts_at DESC", (now(),)).fetchall()
    prods = [{"slug": p["slug"], "name": p["name"]} for p in products().values()]
    return jsonify(events=[event_admin(r) for r in rows], products=prods, now=now())


@app.post("/admin/api/events")
def admin_event_save():
    err = admin_guard(write=True)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    kind = d.get("kind")
    if kind not in ("sale", "giveaway"):
        return jsonify(error="invalid_kind"), 400
    title = str(d.get("title", "")).strip()[:120]
    if len(title) < 3:
        return jsonify(error="invalid_title"), 400
    st, en = _ts(d.get("starts")), _ts(d.get("ends"))
    if not st or not en or en <= st:
        return jsonify(error="invalid_dates"), 400
    try:
        pct = float(str(d.get("pct", 0)).replace(",", ".")) if kind == "sale" else 0
        winners = max(1, min(100, int(d.get("winners", 1) or 1)))
    except (TypeError, ValueError):
        return jsonify(error="invalid_number"), 400
    known = products()
    prod_pct = {}
    try:
        for k, v in (d.get("prod_pct") or {}).items():
            if k in known and str(v).strip() != "":
                prod_pct[k] = round(float(str(v).replace(",", ".")), 2)
        case_pct = float(str(d.get("case_pct") or 0).replace(",", "."))
    except (TypeError, ValueError):
        return jsonify(error="invalid_number"), 400
    if kind == "sale":
        if not 0 <= pct <= 90 or not 0 <= case_pct <= 90 or any(not 0 <= v <= 90 for v in prod_pct.values()):
            return jsonify(error="invalid_pct"), 400
        if pct <= 0 and not any(v > 0 for v in prod_pct.values()) and not (d.get("include_cases") and case_pct > 0):
            return jsonify(error="no_products"), 400
    slugs = [x for x in (d.get("slugs") or []) if x in known][:100]
    scope = "all" if pct > 0 else "list"
    source = d.get("source") if d.get("source") in ("orders", "entries", "both") else "entries"
    vals = dict(kind=kind, title=title, title_en=str(d.get("title_en", "")).strip()[:120] or None, text=str(d.get("text", "")).strip()[:1500] or None,
                text_en=str(d.get("text_en", "")).strip()[:1500] or None, starts_at=st, ends_at=en, published=1 if d.get("published") else 0,
                pct=pct, scope=scope, slugs=json.dumps(slugs), include_cases=1 if d.get("include_cases") else 0,
                combinable=1 if d.get("combinable") else 0, prize=str(d.get("prize", "")).strip()[:200] or None,
                terms=str(d.get("terms", "")).strip()[:6000] or None, requires_order=1 if d.get("requires_order") else 0, winners=winners,
                prod_pct=json.dumps(prod_pct), case_pct=case_pct if kind == "sale" else 0, source=source,
                paid_only=0 if d.get("paid_only") is False else 1, multi_win=1 if d.get("multi_win") else 0)
    if kind == "giveaway" and vals["published"] and not vals["terms"]:
        return jsonify(error="terms_required"), 400
    eid = d.get("id")
    if eid:
        cols = ", ".join(f"{k}=?" for k in vals)
        cur = db().execute(f"UPDATE events SET {cols} WHERE id=?", (*vals.values(), int(eid)))
        if not cur.rowcount:
            return jsonify(error="not_found"), 404
    else:
        cur = db().execute(f"INSERT INTO events({', '.join(vals)}, created_at, created_by) VALUES({', '.join('?' * (len(vals) + 2))})",
                           (*vals.values(), now(), current_admin()))
        eid = cur.lastrowid
    db().commit()
    print(f"[ADMIN] {current_admin()} speichert Event {eid} ({kind}: {title})", flush=True)
    return jsonify(ok=True, id=int(eid))


@app.post("/admin/api/events/<int:eid>/delete")
def admin_event_delete(eid):
    err = admin_guard(write=True)
    if err:
        return err
    db().execute("PRAGMA foreign_keys=ON")
    db().execute("DELETE FROM events WHERE id=?", (eid,))
    db().commit()
    print(f"[ADMIN] {current_admin()} löscht Event {eid}", flush=True)
    return jsonify(ok=True)


def giveaway_tickets(ev):
    """Alle Lose eines Gewinnspiels: je Bestellung im Zeitraum ein Los (E-Mail kann mehrfach vorkommen) und/oder je Teilnahme eins."""
    out = []
    src = ev["source"] or "entries"
    if src in ("orders", "both"):
        states = ("paid", "shipped") if ev["paid_only"] else ("awaiting_payment", "paid", "shipped")
        q = f"SELECT id, email, created_at, total, status FROM orders WHERE created_at>=? AND created_at<? AND status IN ({','.join('?' * len(states))}) ORDER BY created_at"
        for r in db().execute(q, (ev["starts_at"], ev["ends_at"], *states)):
            out.append({"ticket": f"order:{r['id']}", "email": r["email"].lower(), "order_id": r["id"], "created": r["created_at"], "total": r["total"], "status": r["status"]})
    if src in ("entries", "both"):
        for r in db().execute("SELECT user_id, email, created_at FROM giveaway_entries WHERE event_id=? ORDER BY created_at", (ev["id"],)):
            out.append({"ticket": f"entry:{r['user_id']}", "email": r["email"].lower(), "order_id": None, "created": r["created_at"], "total": None, "status": "entry"})
    return out


@app.get("/admin/api/events/<int:eid>/tickets")
def admin_event_tickets(eid):
    err = admin_guard()
    if err:
        return err
    ev = db().execute("SELECT * FROM events WHERE id=? AND kind='giveaway'", (eid,)).fetchone()
    if not ev:
        return jsonify(error="not_found"), 404
    tk = giveaway_tickets(ev)
    counts = {}
    for x in tk:
        counts[x["email"]] = counts.get(x["email"], 0) + 1
    winners = [dict(w) for w in db().execute("SELECT * FROM giveaway_winners WHERE event_id=? ORDER BY drawn_at, id", (eid,))]
    if request.args.get("csv"):
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        won = {x["ticket"] for x in winners}
        w.writerow(["Los", "E-Mail", "Bestellung", "Datum", "Lose dieser E-Mail", "Gewinner"])
        for i, x in enumerate(tk, 1):
            w.writerow([i, x["email"], x["order_id"] or "Teilnahme", time.strftime("%d.%m.%Y %H:%M", time.localtime(x["created"])), counts[x["email"]],
                        "ja" if x["ticket"] in won else ""])
        resp = app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f"attachment; filename=gewinnspiel-{eid}-lose.csv"
        return resp
    return jsonify(tickets=tk, people=len(counts), counts=counts, winners=winners)


@app.post("/admin/api/events/<int:eid>/winners/<int:wid>/remove")
def admin_event_winner_remove(eid, wid):
    """Gewinner wieder entfernen (z. B. nicht erreichbar oder nicht teilnahmeberechtigt), danach kann neu gezogen werden."""
    err = admin_guard(write=True)
    if err:
        return err
    db().execute("DELETE FROM giveaway_winners WHERE id=? AND event_id=?", (wid, eid))
    db().commit()
    print(f"[ADMIN] {current_admin()} entfernt Gewinner {wid} aus Event {eid}", flush=True)
    return jsonify(ok=True)


@app.get("/admin/api/events/<int:eid>/entries")
def admin_event_entries(eid):
    err = admin_guard()
    if err:
        return err
    rows = db().execute("SELECT email, created_at, winner_at FROM giveaway_entries WHERE event_id=? ORDER BY winner_at IS NULL, created_at", (eid,)).fetchall()
    if request.args.get("csv"):
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["E-Mail", "Teilnahme", "Gewinner"])
        for r in rows:
            w.writerow([r["email"], time.strftime("%d.%m.%Y %H:%M", time.localtime(r["created_at"])),
                        time.strftime("%d.%m.%Y %H:%M", time.localtime(r["winner_at"])) if r["winner_at"] else ""])
        resp = app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f"attachment; filename=gewinnspiel-{eid}-teilnehmer.csv"
        return resp
    return jsonify(entries=[dict(r) for r in rows])


@app.post("/admin/api/events/<int:eid>/draw")
def admin_event_draw(eid):
    """Gewinner zufällig ziehen (kryptografischer Zufall). Schon gezogene bleiben Gewinner; es werden nur weitere ergänzt."""
    err = admin_guard(write=True)
    if err:
        return err
    r = db().execute("SELECT * FROM events WHERE id=? AND kind='giveaway'", (eid,)).fetchone()
    if not r:
        return jsonify(error="not_found"), 404
    try:
        n = max(1, min(100, int((request.get_json(silent=True) or {}).get("n", r["winners"]))))
    except (TypeError, ValueError):
        n = r["winners"]
    tickets = giveaway_tickets(r)
    done = list(db().execute("SELECT ticket, email FROM giveaway_winners WHERE event_id=?", (eid,)))
    used_t = {x["ticket"] for x in done}
    used_e = {x["email"] for x in done}
    pool = [x for x in tickets if x["ticket"] not in used_t and (r["multi_win"] or x["email"] not in used_e)]
    rng = secrets.SystemRandom()
    picked = []
    while pool and len(picked) < n:
        x = rng.choice(pool)  # jedes Los gleich wahrscheinlich: wer öfter bestellt hat, hat mehr Lose
        picked.append(x)
        pool = [y for y in pool if y["ticket"] != x["ticket"] and (r["multi_win"] or y["email"] != x["email"])]
    for x in picked:
        db().execute("INSERT INTO giveaway_winners(event_id,ticket,email,order_id,drawn_at,drawn_by) VALUES(?,?,?,?,?,?)",
                     (eid, x["ticket"], x["email"], x["order_id"], now(), current_admin()))
    db().commit()
    print(f"[ADMIN] {current_admin()} zieht {len(picked)} Gewinner für Event {eid} aus {len(tickets)} Losen", flush=True)
    winners = [dict(w) for w in db().execute("SELECT * FROM giveaway_winners WHERE event_id=? ORDER BY drawn_at, id", (eid,))]
    return jsonify(ok=True, drawn=len(picked), picked=[x["ticket"] for x in picked], winners=winners, tickets=len(tickets))


# ------------------------------------------------- Bestand
@app.get("/api/stock")
def public_stock():
    """Nur gezählte Varianten: {slug: {vi: Stück}} – die Seite markiert damit Ausverkauftes."""
    out = {}
    for r in db().execute("SELECT slug, vi, qty FROM stock"):
        out.setdefault(r["slug"], {})[str(r["vi"])] = max(0, r["qty"])
    resp = jsonify(out)
    resp.headers["Cache-Control"] = "public, max-age=60"
    return resp


@app.get("/admin/api/stock")
def admin_stock():
    err = admin_guard()
    if err:
        return err
    t30 = now() - 30 * 86400
    sold = {}
    for r in db().execute("SELECT items FROM orders WHERE status!='cancelled' AND created_at>=?", (t30,)):
        for l in json.loads(r["items"]):
            if not is_case(l):
                k = (l["slug"], l.get("vi", 0))
                sold[k] = sold.get(k, 0) + l["qty"]
    st = {(r["slug"], r["vi"]): r["qty"] for r in db().execute("SELECT slug, vi, qty FROM stock")}
    rows = []
    for p in products().values():
        for vi, v in enumerate(p.get("variants", [])):
            rows.append({"slug": p["slug"], "vi": vi, "name": p["name"], "variant": v["label"], "status": p.get("status"),
                         "qty": st.get((p["slug"], vi)), "sold30": sold.get((p["slug"], vi), 0)})
    return jsonify(items=rows, low=STOCK_LOW)


@app.post("/admin/api/stock")
def admin_stock_save():
    err = admin_guard(write=True)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    slug, raw = str(d.get("slug", "")), d.get("qty")
    try:
        vi = int(d.get("vi", 0))
    except (TypeError, ValueError):
        return jsonify(error="invalid"), 400
    p = products().get(slug)
    if not p or not 0 <= vi < len(p.get("variants", [])):
        return jsonify(error="not_found"), 404
    if raw in (None, ""):
        db().execute("DELETE FROM stock WHERE slug=? AND vi=?", (slug, vi))
    else:
        try:
            qty = max(0, min(100000, int(str(raw).strip())))
        except ValueError:
            return jsonify(error="invalid_number"), 400
        db().execute("INSERT INTO stock(slug,vi,qty,updated_at) VALUES(?,?,?,?) ON CONFLICT(slug,vi) DO UPDATE SET qty=excluded.qty, updated_at=excluded.updated_at",
                     (slug, vi, qty, now()))
    db().commit()
    print(f"[ADMIN] {current_admin()} setzt Bestand {slug}/{vi} auf {raw if raw not in (None, '') else 'unbegrenzt'}", flush=True)
    return jsonify(ok=True, qty=stock_of(slug, vi))


# ------------------------------------------------- Sicherung der Datenbank
import gzip as _gz_backup


def make_backup():
    """Konsistente Kopie der SQLite-Datenbank (auch im laufenden Betrieb), gzip-komprimiert, alte werden aufgeräumt."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    tmp = os.path.join(BACKUP_DIR, f".{SITE['id']}-{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    final = os.path.join(BACKUP_DIR, f"{SITE['id']}-{stamp}.db.gz")
    with open(tmp, "rb") as fi, _gz_backup.open(final, "wb", compresslevel=6) as fo:
        fo.write(fi.read())
    os.remove(tmp)
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(SITE["id"] + "-") and f.endswith(".db.gz"))
    for old in files[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return final


def backup_list():
    if not os.path.isdir(BACKUP_DIR):
        return []
    files = sorted((f for f in os.listdir(BACKUP_DIR) if f.startswith(SITE["id"] + "-") and f.endswith(".db.gz")), reverse=True)
    return [{"name": f, "size": os.path.getsize(os.path.join(BACKUP_DIR, f)), "time": int(os.path.getmtime(os.path.join(BACKUP_DIR, f)))} for f in files]


def _backup_loop():
    """Läuft in jedem Server-Prozess; über einen Vergleich-und-Setzen-Schritt in der Datenbank sichert pro Intervall nur einer."""
    time.sleep(30)
    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            last = (conn.execute("SELECT value FROM settings WHERE key='last_backup'").fetchone() or ["0"])[0]
            if time.time() - int(last) >= BACKUP_EVERY:
                won = conn.execute("UPDATE settings SET value=? WHERE key='last_backup' AND value=?", (str(int(time.time())), last)).rowcount
                if not won and last == "0":
                    won = conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('last_backup',?)", (str(int(time.time())),)).rowcount
                conn.commit()
                if won:
                    print(f"[BACKUP] {make_backup()}", flush=True)
            conn.close()
        except Exception as exc:
            print(f"[BACKUP] fehlgeschlagen: {exc}", flush=True)
        time.sleep(1800)


if os.environ.get("BACKUP_EVERY_HOURS", "24") != "0":
    threading.Thread(target=_backup_loop, daemon=True).start()


@app.get("/admin/api/backups")
def admin_backups():
    err = admin_guard()
    if err:
        return err
    return jsonify(backups=backup_list()[:BACKUP_KEEP], dir=BACKUP_DIR, keep=BACKUP_KEEP, every=BACKUP_EVERY // 3600)


@app.post("/admin/api/backups")
def admin_backup_now():
    err = admin_guard(write=True)
    if err:
        return err
    if limited("backupnow", 6, 3600):
        return jsonify(error="rate_limited"), 429
    path = make_backup()
    print(f"[ADMIN] {current_admin()} erstellt Sicherung {path}", flush=True)
    return jsonify(ok=True, name=os.path.basename(path))


@app.get("/admin/api/backups/<name>")
def admin_backup_download(name):
    err = admin_guard()
    if err:
        return err
    if not re.match(r"^" + re.escape(SITE["id"]) + r"-[0-9_-]+\.db\.gz$", name) or not os.path.isfile(os.path.join(BACKUP_DIR, name)):
        return jsonify(error="not_found"), 404
    print(f"[ADMIN] {current_admin()} lädt Sicherung {name} herunter", flush=True)
    return send_from_directory(BACKUP_DIR, name, as_attachment=True, mimetype="application/gzip")


# ------------------------------------------------- Einstellungen und Nexo-Bereich
@app.get("/admin/api/settings")
def admin_settings():
    err = admin_guard()
    if err:
        return err
    return jsonify(nexo_pct=nexo_pct(), nexo_notify=nexo_recipients())


@app.post("/admin/api/settings")
def admin_settings_save():
    err = admin_guard(write=True)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        pct = float(str(d.get("nexo_pct", "")).replace(",", "."))
    except (TypeError, ValueError):
        return jsonify(error="invalid_number"), 400
    if not 0 <= pct <= 90:
        return jsonify(error="invalid_number"), 400
    pct = round(pct, 2)
    db().execute("INSERT INTO settings(key,value) VALUES('nexo_pct',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"{pct:g}",))
    changed = 0
    if d.get("apply_open"):
        # offene (noch nicht bezahlte) Case-Bestellungen auf den neuen Satz umstellen; bezahlte bleiben beim alten Satz
        changed = db().execute("UPDATE orders SET nexo_pct=?, nexo_fee=CAST(ROUND(case_total*?/100.0) AS INTEGER) "
                               "WHERE status='awaiting_payment' AND case_status IS NOT NULL", (pct, pct)).rowcount
    db().commit()
    print(f"[ADMIN] {current_admin()} setzt Nexo-Provision auf {pct:g} % (offene angepasst: {changed})", flush=True)
    return jsonify(ok=True, nexo_pct=pct, changed=changed)


NEXO_ROLES = ("nexo", "owner")


@app.get("/admin/api/nexo/overview")
def nexo_overview():
    err = admin_guard(roles=NEXO_ROLES)
    if err:
        return err
    return jsonify(nexo_summary(db()))


def nexo_query():
    st, q = request.args.get("status", ""), request.args.get("q", "").strip()[:80]
    sql, args = "SELECT * FROM orders WHERE case_status IS NOT NULL", []
    if st == "to_ship":
        sql += " AND status IN ('paid','shipped') AND case_status='open'"
    elif st == "unpaid":
        sql += " AND status='awaiting_payment'"
    elif st in CASE_STATUSES:
        sql += " AND case_status=?"
        args.append(st)
    if q:
        # Nexo sucht nur in Nummer, Name und Ort (nicht in Peptid-Positionen)
        sql += " AND (id LIKE ? OR address LIKE ?)"
        args += [f"%{q}%"] * 2
    return sql + " ORDER BY CASE WHEN express=1 AND status IN ('paid','shipped') AND case_status='open' THEN 0 ELSE 1 END, created_at DESC", args


@app.get("/admin/api/nexo/orders")
def nexo_orders():
    err = admin_guard(roles=NEXO_ROLES)
    if err:
        return err
    sql, args = nexo_query()
    return jsonify(orders=[nexo_order_row(r) for r in db().execute(sql + " LIMIT 300", args)])


@app.get("/admin/api/nexo/orders/<oid>")
def nexo_order_detail(oid):
    err = admin_guard(roles=NEXO_ROLES)
    if err:
        return err
    r = db().execute("SELECT * FROM orders WHERE id=? AND case_status IS NOT NULL", (oid,)).fetchone()
    if not r:
        return jsonify(error="not_found"), 404
    return jsonify(order=nexo_order_row(r, full=True))


@app.post("/admin/api/nexo/orders/<oid>/case")
def nexo_order_case(oid):
    err = admin_guard(write=True, roles=NEXO_ROLES)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    r = db().execute("SELECT * FROM orders WHERE id=? AND case_status IS NOT NULL", (oid,)).fetchone()
    if not r:
        return jsonify(error="not_found"), 404
    st = d.get("status", r["case_status"])
    if st not in CASE_STATUSES:
        return jsonify(error="invalid_status"), 400
    if st == "shipped" and r["status"] not in ("paid", "shipped"):
        return jsonify(error="not_paid"), 409
    if st == "open" and r["status"] == "cancelled":
        return jsonify(error="order_cancelled"), 409
    tracking = str(d.get("tracking", r["case_tracking"] or "")).strip()[:80] or None
    db().execute("UPDATE orders SET case_status=?, case_tracking=?, case_shipped_at=CASE WHEN ?='shipped' THEN COALESCE(case_shipped_at,?) ELSE NULL END WHERE id=?",
                 (st, tracking, st, now(), oid))
    # reine Case-Bestellung: mit dem Versand durch Nexo ist die ganze Bestellung versendet
    if st == "shipped" and r["status"] == "paid" and not any(not is_case(i) for i in json.loads(r["items"] or "[]")):
        db().execute("UPDATE orders SET status='shipped' WHERE id=?", (oid,))
    db().commit()
    print(f"[ADMIN] {current_admin()} setzt Case-Teil von {oid} auf {st}", flush=True)
    if st == "shipped" and r["case_status"] != "shipped" and d.get("notify", True):
        send_ship_mail(oid, "case")
    if st == "shipped" and r["case_status"] != "shipped" and ORDER_NOTIFY:
        t = f"Nexo hat den Case-Teil von {oid} versendet." + (f" Sendungsnummer: {tracking}" if tracking else "")
        threading.Thread(target=send_mail, args=(ORDER_NOTIFY, f"[Shop] Case versendet: {oid}", t, f"<p>{_html.escape(t)}</p>"), daemon=True).start()
    return jsonify(ok=True)


@app.get("/admin/api/nexo/orders.csv")
def nexo_orders_csv():
    err = admin_guard(roles=NEXO_ROLES)
    if err:
        return err
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Bestellnummer", "Datum", "Zahlung", "Case-Status", "Sendungsnummer", "Name", "Firma", "Straße", "PLZ", "Ort", "Land",
                "Cases", "Case-Warenwert", "Provision Shop %", "Provision Shop", "Auszahlung Nexo"])
    money = lambda c: f"{(c or 0) / 100:.2f}".replace(".", ",")
    pay = {"paid": "bezahlt", "open": "offen", "cancelled": "storniert"}
    sql, args = nexo_query()
    for r in db().execute(sql, args):
        o = nexo_order_row(r, full=True)
        a = o["address"]
        items = "; ".join(f"{i['qty']}x {i['name']} ({i['variant']})" for i in o["items"])
        w.writerow([o["id"], time.strftime("%d.%m.%Y %H:%M", time.localtime(o["created"])), pay[o["payment"]], o["case_status"], o["case_tracking"] or "",
                    a["name"], a["company"], a["street"], a["zip"], a["city"], a["country"], items, money(o["case_total"]),
                    f"{(o['nexo_pct'] or 0):g}".replace(".", ","), money(o["nexo_fee"]), money(o["payout"])])
    resp = app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename=nexo-case-bestellungen-{time.strftime('%Y-%m-%d')}.csv"
    return resp


def month_orders(month, conn=None):
    """Bezahlte Case-Bestellungen eines Monats (Basis der Abrechnung)."""
    return (conn or db()).execute("""SELECT * FROM orders WHERE status IN ('paid','shipped') AND case_status IS NOT NULL AND case_status!='cancelled'
        AND strftime('%Y-%m',created_at,'unixepoch','localtime')=? ORDER BY created_at""", (month,)).fetchall()


@app.post("/admin/api/nexo/payouts")
def nexo_payout_mark():
    """Monat als an Nexo ausgezahlt markieren (nur das Team). Vergibt eine Gutschrift-Nummer und friert den Betrag ein."""
    err = admin_guard(write=True)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    month = str(d.get("month", ""))
    if not re.match(r"^\d{4}-\d{2}$", month) or month >= time.strftime("%Y-%m"):
        return jsonify(error="invalid_month"), 400
    rows = month_orders(month)
    amount = sum((r["case_total"] or 0) - (r["nexo_fee"] or 0) for r in rows)
    ex = db().execute("SELECT * FROM nexo_payouts WHERE month=?", (month,)).fetchone()
    if d.get("paid", True):
        credit = (ex["credit_no"] if ex and ex["credit_no"] else next_number("GS"))
        db().execute("""INSERT INTO nexo_payouts(month,amount,paid_at,paid_by,credit_no,note) VALUES(?,?,?,?,?,?)
            ON CONFLICT(month) DO UPDATE SET amount=excluded.amount, paid_at=excluded.paid_at, paid_by=excluded.paid_by, credit_no=excluded.credit_no, note=excluded.note""",
                     (month, amount, now(), current_admin(), credit, str(d.get("note", ""))[:200] or None))
    elif ex:
        db().execute("UPDATE nexo_payouts SET paid_at=NULL, paid_by=NULL WHERE month=?", (month,))
    db().commit()
    print(f"[ADMIN] {current_admin()} Nexo-Auszahlung {month}: {'bezahlt' if d.get('paid', True) else 'offen'} ({eur(amount)})", flush=True)
    return jsonify(ok=True, amount=amount)


@app.get("/admin/api/nexo/payouts/<month>.pdf")
def nexo_payout_pdf(month):
    """Gutschrift/Abrechnung für Nexo über einen Monat (für Nexo und das Team)."""
    err = admin_guard(roles=NEXO_ROLES)
    if err:
        return err
    if not re.match(r"^\d{4}-\d{2}$", month):
        return jsonify(error="not_found"), 404
    rows = month_orders(month)
    pay = db().execute("SELECT * FROM nexo_payouts WHERE month=?", (month,)).fetchone()
    y, mo = month.split("-")
    label = f"{mo}/{y}"
    m = lambda c: pdfdoc.money(c or 0)
    items = []
    for r in rows:
        n = sum(int(i.get("qty", 1)) for i in json.loads(r["items"]) if is_case(i))
        items.append((n, f"Bestellung {r['id']}", f"{time.strftime('%d.%m.%Y', time.localtime(r['created_at']))} · Case-Warenwert {m(r['case_total'])} · "
                      f"Provision {(r['nexo_pct'] or 0):g} % = {m(r['nexo_fee'])}", m(r["case_total"]), m((r["case_total"] or 0) - (r["nexo_fee"] or 0))))
    rev = sum(r["case_total"] or 0 for r in rows)
    fee = sum(r["nexo_fee"] or 0 for r in rows)
    meta = [("Gutschrift Nr.", pay["credit_no"] if pay and pay["credit_no"] else "Entwurf"), ("Zeitraum", label),
            ("Datum", time.strftime("%d.%m.%Y", time.localtime(pay["paid_at"] if pay and pay["paid_at"] else time.time()))),
            ("Bestellungen", str(len(rows)))]
    totals = [("Case-Umsatz", m(rev), False), ("abzgl. Provision Shop", m(-fee), False), (f"Auszahlung an {PARTNER}", m(rev - fee), True)]
    notes = [f"Abrechnung der über den {SITE['name']}-Shop verkauften Vial-Cases für {label}. Gezählt werden bezahlte Bestellungen; Basis ist der "
             "Case-Warenwert nach anteiligem Rabatt, ohne Versandkosten."]
    notes.append(f"Ausgezahlt am {time.strftime('%d.%m.%Y', time.localtime(pay['paid_at']))}." if pay and pay["paid_at"] else
                 "Noch nicht ausgezahlt (Entwurf).")
    pdf = pdfdoc.document("Gutschrift Vial-Cases", seller_lines(), NEXO_ADDRESS, meta, items, totals, notes, seller_footer("de"), "de",
                          heads=("Cases", "Bestellung", "Case-Wert", "", "Auszahlung"))
    return _pdf_response(pdf, f"nexo-abrechnung-{month}.pdf")


# ------------------------------------------------- Partner- und Team-Bereich im Kundenkonto
# Partner: Kundenkonto mit derselben E-Mail wie beim Partner-Code -> eigenes Dashboard (nur Zahlen, keine Kundendaten).
# Team:    Kundenkonto mit einer Admin-E-Mail (im Admin-Bereich unter "Zugang" hinterlegt oder ADMIN_EMAILS in .env)
#          -> Übersicht aller Partner-Codes und neue Codes anlegen.
def team_emails():
    env = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    # nur das Shop-Team: die E-Mail eines Nexo-Zugangs ist nur für Benachrichtigungen da
    rows = db().execute("SELECT lower(email) AS e FROM admin_users WHERE email IS NOT NULL AND email!='' AND IFNULL(role,'owner')='owner'").fetchall()
    return env | {r["e"] for r in rows}


def is_team(email):
    return bool(email) and email.lower() in team_emails()


def partner_codes(email):
    return db().execute("SELECT * FROM affiliates WHERE lower(email)=? ORDER BY code", ((email or "").lower(),)).fetchall()


def save_affiliate(d, who):
    """Gemeinsame Prüfung für Admin-Bereich und Team-Ansicht im Konto. Gibt (antwort, status) zurück."""
    code = str(d.get("code", "")).strip().upper()
    if not CODE_RE.match(code):
        return {"error": "invalid_code"}, 400
    try:
        disc = min(90.0, max(0.0, float(str(d.get("discount", AFF_DISCOUNT)).replace(",", "."))))
        comm = min(90.0, max(0.0, float(str(d.get("commission", AFF_COMMISSION)).replace(",", "."))))
    except (TypeError, ValueError):
        return {"error": "invalid_number"}, 400
    email = str(d.get("email") or "").strip().lower()[:120]
    if email and not EMAIL_RE.match(email):
        return {"error": "invalid_email"}, 400
    exists = db().execute("SELECT 1 FROM affiliates WHERE code=?", (code,)).fetchone()
    if d.get("create_only") and exists:
        return {"error": "code_exists"}, 409
    db().execute("""INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(code) DO UPDATE SET name=excluded.name,email=excluded.email,discount_pct=excluded.discount_pct,
        commission_pct=excluded.commission_pct,active=excluded.active""",
                 (code, str(d.get("name") or code).strip()[:80], email or None, disc, comm, 1 if d.get("active", True) else 0, now()))
    db().commit()
    print(f"[ADMIN] {who} speichert Code {code}", flush=True)
    return {"ok": True, "code": code, "link": f"{BASE_URL}/?ref={code}"}, 200


@app.get("/api/partner")
def partner_dashboard():
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    out = []
    for a in partner_codes(u["email"]):
        rows = db().execute("SELECT id,created_at,status,total,shipping,commission FROM orders WHERE affiliate_code=? ORDER BY created_at DESC",
                            (a["code"],)).fetchall()
        live = [r for r in rows if r["status"] != "cancelled"]
        paid = [r for r in live if r["status"] in ("paid", "shipped")]
        months = {}
        for r in live:
            key = time.strftime("%Y-%m", time.localtime(r["created_at"]))
            m = months.setdefault(key, {"month": key, "orders": 0, "revenue": 0, "commission": 0})
            m["orders"] += 1
            m["revenue"] += r["total"] - r["shipping"]
            m["commission"] += r["commission"]
        out.append({
            "code": a["code"], "name": a["name"], "active": bool(a["active"]), "discount": a["discount_pct"], "commission_pct": a["commission_pct"],
            "link": f"{BASE_URL}/?ref={a['code']}", "orders": len(live),
            "revenue": sum(r["total"] - r["shipping"] for r in live), "revenue_paid": sum(r["total"] - r["shipping"] for r in paid),
            "commission_paid": sum(r["commission"] for r in paid),
            "commission_open": sum(r["commission"] for r in live if r["status"] == "awaiting_payment"),
            "months": sorted(months.values(), key=lambda m: m["month"], reverse=True)[:12],
            # nur Datum, Status und Beträge: keine Namen, Adressen oder E-Mails der Kunden
            "recent": [{"created": r["created_at"], "status": r["status"], "amount": r["total"] - r["shipping"], "commission": r["commission"]}
                       for r in rows[:10]],
        })
    return jsonify(partner=out)


@app.get("/api/team/affiliates")
def team_affiliates():
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    if not is_team(u["email"]):
        return jsonify(error="forbidden"), 403
    rows = affiliate_stats(db())
    for r in rows:
        r["link"] = f"{BASE_URL}/?ref={r['code']}"
    return jsonify(affiliates=rows, defaults={"discount": AFF_DISCOUNT, "commission": AFF_COMMISSION})


@app.post("/api/team/affiliates")
def team_affiliates_save():
    if not require_custom_header():
        return jsonify(error="forbidden"), 403
    u = current_user()
    if not u:
        return jsonify(error="unauthorized"), 401
    if not is_team(u["email"]):
        return jsonify(error="forbidden"), 403
    body, status = save_affiliate(request.get_json(silent=True) or {}, u["email"])
    return jsonify(body), status


@app.post("/admin/api/email")
def admin_set_email():
    err = admin_guard(write=True, roles=ROLES)
    if err:
        return err
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()[:120]
    if email and not EMAIL_RE.match(email):
        return jsonify(error="invalid_email"), 400
    db().execute("UPDATE admin_users SET email=? WHERE username=?", (email or None, current_admin()))
    db().commit()
    return jsonify(ok=True, email=email)


def cli(argv):
    """Befehle:
  python app.py add-affiliate CODE "Name" [email]   Code anlegen (Rabatt/Provision aus .env)
  python app.py disable-affiliate CODE              Code deaktivieren
  python app.py list-affiliates                     Übersicht mit Bestellungen und Provision
  python app.py list-orders                         Letzte Bestellungen
  python app.py set-status BESTELLNR paid|shipped|cancelled   Status setzen (z. B. Überweisung eingegangen)
  python app.py set-admin NAME [owner|nexo]         Admin-Zugang anlegen oder Passwort ändern (fragt das Passwort ab)
  python app.py hash-password                       Passwort-Hash für site/admins.json erzeugen (fragt das Passwort ab)
  python app.py remove-admin NAME                   Admin-Zugang löschen
  python app.py list-admins                         Admin-Zugänge anzeigen
  python app.py backup                              Datenbank jetzt sichern (sonst automatisch täglich)
  python app.py reset-2fa NAME                      Zwei-Faktor-Anmeldung zurücksetzen (Handy verloren)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cmd = argv[0] if argv else ""
    if cmd == "add-affiliate" and len(argv) >= 3:
        code = argv[1].strip().upper()
        if not CODE_RE.match(code):
            print("Ungültiger Code (3–24 Zeichen: A–Z, 0–9, - oder _)")
            return
        conn.execute("""INSERT INTO affiliates(code,name,email,discount_pct,commission_pct,active,created_at) VALUES(?,?,?,?,?,1,?)
            ON CONFLICT(code) DO UPDATE SET name=excluded.name,email=excluded.email,active=1""",
            (code, argv[2], argv[3] if len(argv) > 3 else None, AFF_DISCOUNT, AFF_COMMISSION, int(time.time())))
        conn.commit()
        print(f"Code {code} aktiv: {AFF_DISCOUNT:g} % Rabatt, {AFF_COMMISSION:g} % Provision\nPartner-Link: {BASE_URL}/?ref={code}")
    elif cmd == "disable-affiliate" and len(argv) >= 2:
        conn.execute("UPDATE affiliates SET active=0 WHERE code=?", (argv[1].strip().upper(),))
        conn.commit()
        print("deaktiviert")
    elif cmd == "list-affiliates":
        for r in affiliate_stats(conn):
            print(f"{r['code']:<14} {r['name']:<22} {'aktiv' if r['active'] else 'aus':<6} Bestellungen {r['orders']:>3}  "
                  f"Umsatz bezahlt {eur(r['revenue_paid']):>12}  Provision bezahlt {eur(r['commission_paid']):>10}  offen {eur(r['commission_open']):>10}")
    elif cmd == "list-orders":
        for r in conn.execute("SELECT id,email,total,discount,affiliate_code,method,status,created_at FROM orders ORDER BY created_at DESC LIMIT 50"):
            print(f"{r['id']}  {time.strftime('%d.%m.%Y %H:%M', time.localtime(r['created_at']))}  {r['email']:<28} {eur(r['total']):>11}  "
                  f"{r['method']:<10} {r['status']:<16} {('Code ' + r['affiliate_code']) if r['affiliate_code'] else ''}")
    elif cmd == "set-status" and len(argv) >= 3 and argv[2] in ("paid", "shipped", "cancelled", "awaiting_payment"):
        cur = conn.execute("UPDATE orders SET status=?, paid_at=CASE WHEN ?='paid' THEN ? ELSE paid_at END WHERE id=?",
                           (argv[2], argv[2], int(time.time()), argv[1]))
        conn.commit()
        if cur.rowcount and argv[2] in ("paid", "shipped"):
            print("Rechnung:", ensure_invoice(argv[1], conn))
        print("aktualisiert" if cur.rowcount else "Bestellung nicht gefunden")
    elif cmd == "hash-password":
        import getpass
        pw = getpass.getpass("Passwort: ")
        if len(pw) < 10 or getpass.getpass("Wiederholen: ") != pw:
            print("Abgebrochen: mindestens 10 Zeichen und beide Eingaben gleich.")
            return
        print("Hash für site/admins.json:")
        print(generate_password_hash(pw))
    elif cmd == "set-admin" and len(argv) >= 2:
        import getpass
        name = argv[1].strip()[:40]
        pw = getpass.getpass(f"Neues Passwort für {name}: ")
        if len(pw) < 10 or getpass.getpass("Wiederholen: ") != pw:
            print("Abgebrochen: mindestens 10 Zeichen und beide Eingaben gleich.")
            return
        role = argv[2] if len(argv) > 2 and argv[2] in ROLES else None
        conn.execute("INSERT INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?) ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash",
                     (name, generate_password_hash(pw), int(time.time()), role or "owner"))
        if role:
            conn.execute("UPDATE admin_users SET role=? WHERE username=?", (role, name))
        conn.execute("DELETE FROM admin_sessions WHERE username=?", (name,))
        conn.commit()
        print(f"Zugang {name} gespeichert.")
    elif cmd == "remove-admin" and len(argv) >= 2:
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.execute("DELETE FROM admin_users WHERE username=?", (argv[1].strip(),))
        conn.commit()
        print("gelöscht" if cur.rowcount else "nicht gefunden")
    elif cmd == "reset-2fa" and len(argv) >= 2:
        cur = conn.execute("UPDATE admin_users SET totp_on=0, totp_secret=NULL WHERE username=?", (argv[1].strip(),))
        conn.execute("DELETE FROM admin_sessions WHERE username=?", (argv[1].strip(),))
        conn.commit()
        print("Zwei-Faktor-Anmeldung zurückgesetzt" if cur.rowcount else "nicht gefunden")
    elif cmd == "backup":
        print("Sicherung:", make_backup())
    elif cmd == "list-admins":
        for r in conn.execute("SELECT username,last_login,role FROM admin_users ORDER BY username COLLATE NOCASE"):
            last = time.strftime('%d.%m.%Y %H:%M', time.localtime(r['last_login'])) if r['last_login'] else "noch nie"
            print(f"{r['username']:<16} {r['role']:<6} zuletzt angemeldet: {last}")
    else:
        print(cli.__doc__)


# ------------------------------------------------------------------------ SEO
import html as _html


def _index_html():
    with open(os.path.join(PUBLIC_DIR, "index.html"), encoding="utf-8") as fh:
        return fh.read()


def page_url(lang, slug=""):
    return f"{BASE_URL}/{lang}/" + (f"{slug}/" if slug else "")


def render_page(product=None, lang=DEFAULT_LANG, slug="", title=None):
    """index.html mit Titel, Beschreibung, hreflang, Canonical und strukturierten Daten für die jeweilige Sprache."""
    page = _index_html()
    esc = _html.escape
    data = i18n()
    if product:
        slug = product["slug"]
        r = ((data.get("res") or {}).get(lang) or {}).get(slug) or product.get("research") or {}
        title = tr(lang, "product_title", name=product["name"], purity=product.get("purity", ""))
        desc = (r.get("intro") or product.get("cls", ""))[:300]
        url = page_url(lang, slug)
        offers = [{"@type": "Offer", "price": f"{v['price']:.2f}", "priceCurrency": "EUR", "name": v["label"],
                   "availability": "https://schema.org/" + {"out_of_stock": "OutOfStock", "preorder": "PreOrder"}.get(product.get("status"), "InStock"),
                   "url": url} for v in product.get("variants", [])]
        ld = {"@context": "https://schema.org", "@type": "Product", "name": product["name"], "sku": product.get("sku"),
              "description": desc, "image": product.get("image"), "brand": {"@type": "Brand", "name": SITE["name"]}, "offers": offers}
        noscript = (f"<noscript><h1>{esc(product['name'])}</h1><p>{esc(desc)}</p><ul>"
                    + "".join(f"<li>{esc(v['label'])}: {v['price']:.2f} €</li>" for v in product.get("variants", []))
                    + f"</ul><p>{esc(tr(lang, 'research_only'))}</p></noscript>")
        image = product.get("image", "")
    else:
        title = title or tr(lang, "home_title")
        desc = tr(lang, "home_desc")
        url = page_url(lang, slug)
        items = [{"@type": "ListItem", "position": i + 1, "url": page_url(lang, p["slug"]), "name": p["name"]}
                 for i, p in enumerate(products().values())]
        ld = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items}
        noscript = f"<noscript><h1>{esc(title)}</h1><ul>" + "".join(
            f"<li><a href='/{lang}/{p['slug']}/'>{esc(p['name'])}</a></li>" for p in products().values()) + "</ul></noscript>"
        image = ""
    case = cases().get("nexo-case") if slug == "cases" else None
    if case:
        # Cases-Seite: strukturierte Produktdaten für Google (Preis, Verfügbarkeit)
        ld = {"@context": "https://schema.org", "@type": "Product", "name": case["name"], "sku": case.get("sku"),
              "description": tr(lang, "cases_title"), "brand": {"@type": "Brand", "name": f"{SITE['name']} × {PARTNER}"},
              "offers": {"@type": "Offer", "price": f"{case['price']:.2f}", "priceCurrency": "EUR", "url": url,
                         "availability": "https://schema.org/" + {"out_of_stock": "OutOfStock", "preorder": "PreOrder"}.get(case.get("status"), "InStock")}}
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    alternates = "".join(f'<link rel="alternate" hreflang="{l}" href="{esc(page_url(l, slug))}">\n' for l in langs())
    alternates += f'<link rel="alternate" hreflang="x-default" href="{esc(page_url(DEFAULT_LANG, slug))}">\n'
    head = (f'<meta name="description" content="{esc(desc)}">\n<link rel="canonical" href="{esc(url)}">\n' + alternates +
            f'<meta property="og:type" content="{"product" if product else "website"}">\n<meta property="og:title" content="{esc(title)}">\n'
            f'<meta property="og:description" content="{esc(desc)}">\n<meta property="og:url" content="{esc(url)}">\n'
            f'<meta property="og:locale" content="{ {"de": "de_DE", "en": "en_GB", "it": "it_IT", "es": "es_ES", "fr": "fr_FR", "pl": "pl_PL"}.get(lang, "de_DE") }">\n'
            + (f'<meta property="og:image" content="{esc(image)}">\n' if image else "")
            + '<script type="application/ld+json">' + ld_json + '</script>')
    page = re.sub(r"<title>.*?</title>", lambda m: f"<title>{esc(title)}</title>", page, count=1, flags=re.S)
    page = page.replace('<html lang="de">', f'<html lang="{lang}">', 1)
    page = page.replace("<!--SEO-->", head, 1).replace("<!--NOSCRIPT-->", noscript, 1)
    return slim_page(page, lang)


# Ladezeit: Die Seite enthält für den Betrieb ohne Server alle Sprachen und das 3D-Modell des Cases.
# Über den Server bekommt der Browser nur die aktuelle Sprache; andere Sprachen (/i18n/xx.json) und das Case-Modell
# (/case-model.json) lädt die Seite erst, wenn sie gebraucht werden.  Spart rund 370 KB pro Seitenaufruf.
_slim = {"mtime": 0, "parts": {}}
I18N_RE = re.compile(r'(<script type="application/json" id="i18nData">)(.*?)(</script>)', re.S)
CASE_RE = re.compile(r'(<script type="application/json" id="nexoCaseData">)(.*?)(</script>)', re.S)


def _json_script(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def slim_parts(lang):
    data = i18n()
    if _slim["mtime"] != _i18n["mtime"]:
        _slim.update(mtime=_i18n["mtime"], parts={})
    key = lang
    if key not in _slim["parts"]:
        _slim["parts"][key] = _json_script({"langs": data.get("langs", {}), "legal": data.get("legal", {}),
                                            "ui": {lang: (data.get("ui") or {}).get(lang, {})},
                                            "res": {lang: (data.get("res") or {}).get(lang, {})}, "partial": True})
    return _slim["parts"][key]


def slim_page(page, lang):
    if request.args.get("full") == "1":
        return page
    page = I18N_RE.sub(lambda m: m.group(1) + slim_parts(lang) + m.group(3), page, count=1)
    page = CASE_RE.sub(lambda m: m.group(1) + '{"external":"/case-model.json"}' + m.group(3), page, count=1)
    return externalize(page)


# Ladezeit für wiederkehrende Besucher: das große Skript und das große Stylesheet aus index.html werden als eigene Dateien
# mit Prüfsumme im Namen ausgeliefert (/assets/app.<hash>.js|css) und ein Jahr im Browser gespeichert. Ändert sich
# index.html, ändert sich der Name, der Browser lädt dann automatisch neu. index.html selbst bleibt eine Datei.
_assets = {"mtime": None, "files": {}, "parts": None}
STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)
SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.S)


def _asset_parts():
    path = os.path.join(PUBLIC_DIR, "index.html")
    mt = os.path.getmtime(path)
    if _assets["mtime"] != mt:
        page = _index_html()
        st = max(STYLE_RE.finditer(page), key=lambda m: len(m.group(1)), default=None)
        sc = max(SCRIPT_RE.finditer(page), key=lambda m: len(m.group(1)), default=None)
        files, parts = {}, {}
        for kind, m, mime in (("css", st, "text/css"), ("js", sc, "application/javascript")):
            if m and len(m.group(1)) > 20000:
                body = m.group(1).encode()
                name = f"app.{hashlib.sha1(body).hexdigest()[:12]}.{kind}"
                files[name] = (body, mime)
                parts[kind] = (m.group(0), name)
        _assets.update(mtime=mt, files=files, parts=parts)
    return _assets["parts"]


def externalize(page):
    try:
        parts = _asset_parts()
    except OSError:
        return page
    if "css" in parts and parts["css"][0] in page:
        page = page.replace(parts["css"][0], f'<link rel="stylesheet" href="/assets/{parts["css"][1]}">', 1)
    if "js" in parts and parts["js"][0] in page:
        page = page.replace(parts["js"][0], f'<script src="/assets/{parts["js"][1]}"></script>', 1)
    return page


@app.get("/assets/<name>")
def asset_file(name):
    _asset_parts()
    f = _assets["files"].get(name)
    if not f:
        return jsonify(error="not_found"), 404
    resp = app.response_class(f[0], mimetype=f[1])
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@app.get("/i18n/<lang:lang>.json")
def i18n_lang(lang):
    data = i18n()
    if lang not in langs():
        return jsonify(error="not_found"), 404
    return jsonify(ui=(data.get("ui") or {}).get(lang, {}), res=(data.get("res") or {}).get(lang, {}))


_case_model = {"mtime": 0, "body": b""}


@app.get("/case-model.json")
def case_model():
    path = os.path.join(PUBLIC_DIR, "index.html")
    mt = os.path.getmtime(path)
    if _case_model["mtime"] != mt:
        m = CASE_RE.search(_index_html())
        _case_model.update(mtime=mt, body=(m.group(2) if m else "{}").encode())
    return app.response_class(_case_model["body"], mimetype="application/json")


def html_response(body, status=200):
    if status == 404:
        # eigene 404-Seite: die Seite zeigt oben einen Hinweis mit Suche, darunter das Sortiment
        body = body.replace("<html ", '<html data-nf="1" ', 1)
        body = re.sub(r'<meta name="description"[^>]*>\n<link rel="canonical"[^>]*>\n', "", body, count=1)
        body = body.replace("<!--SEO-->", "", 1).replace("</title>", "</title>\n<meta name=\"robots\" content=\"noindex\">", 1)
    resp = app.response_class(body, status=status, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Vary"] = "Accept-Language, Cookie"
    return resp


@app.get("/sitemap.xml")
def sitemap():
    esc = _html.escape
    paths = ["", "cases"] + list(products())
    out = []
    for path in paths:
        alts = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{esc(page_url(l, path))}"/>' for l in langs())
        out += [f"<url><loc>{esc(page_url(l, path))}</loc>{alts}</url>" for l in langs()]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + "".join(out) + "</urlset>")
    return app.response_class(body, mimetype="application/xml")


@app.get("/robots.txt")
def robots():
    return app.response_class(f"User-agent: *\nDisallow: /api/\nDisallow: /admin/\nSitemap: {BASE_URL}/sitemap.xml\n", mimetype="text/plain")


# --------------------------------------------------------------------- static
@app.get("/")
def index():
    # Startseite: in die passende Sprache weiterleiten (Cookie > Browser-Sprache > Deutsch), Parameter bleiben erhalten
    qs = request.query_string.decode()
    return redirect(f"/{request_lang()}/" + (f"?{qs}" if qs else ""), 302)


@app.get("/<lang:lang>/")
def index_lang(lang):
    if lang not in langs():
        return static_files(lang + "/")
    return html_response(render_page(lang=lang))


@app.get("/<lang:lang>/cases/")
def cases_page(lang):
    if lang not in langs():
        return html_response(render_page(), 404)
    return html_response(render_page(lang=lang, slug="cases", title=tr(lang, "cases_title")))


@app.get("/<lang:lang>/rechner/")
def calc_page(lang):
    # Der Peptid-Rechner wurde entfernt: alte Links und Lesezeichen landen auf der Startseite
    return redirect(f"/{lang if lang in langs() else DEFAULT_LANG}/", 301)


@app.get("/<lang:lang>/<slug>/")
def product_page(lang, slug):
    if lang not in langs():
        return html_response(render_page(), 404)
    p = products().get(slug)
    if not p:
        return html_response(render_page(lang=lang), 404)
    return html_response(render_page(p, lang=lang))


@app.get("/<path:path>")
def static_files(path):
    if path.startswith("api/"):
        return jsonify(error="not_found"), 404
    if path == "products.json" or path.startswith("thumbs/"):
        sfull = os.path.join(SITE_DIR, path)
        if os.path.isfile(sfull):
            return send_from_directory(SITE_DIR, path)
    full = os.path.join(PUBLIC_DIR, path)
    if os.path.isfile(full) and not path.endswith("index.html"):
        return send_from_directory(PUBLIC_DIR, path)
    m = re.match(r"^([a-z]{2})(?:/([a-z0-9-]+))?$", path)
    if m and m.group(1) in langs() and (not m.group(2) or m.group(2) in ("cases",) or m.group(2) in products()):
        return redirect("/" + "/".join(x for x in m.groups() if x) + "/", 301)
    return html_response(render_page(lang=request_lang()), 404)


# ---------------------------------------------------------- Caching & gzip
# Seiten: ETag + "no-cache" (Browser fragt kurz nach, bekommt bei unveränderter Seite nur 304 ohne Inhalt).
# Bilder/Schriften: 7 Tage im Browser-Cache, products.json: 5 Minuten.  Text wird gzip-komprimiert (≈ 650 KB -> 215 KB).
import gzip as _gzip

COMPRESSIBLE = ("text/", "application/json", "application/javascript", "application/xml", "image/svg+xml")
_GZ_CACHE = {}


def _gzip_bytes(data):
    key = hashlib.sha1(data).hexdigest()
    hit = _GZ_CACHE.get(key)
    if hit is None:
        hit = _gzip.compress(data, compresslevel=6, mtime=0)
        if len(_GZ_CACHE) > 64:
            _GZ_CACHE.clear()
        _GZ_CACHE[key] = hit
    return hit


@app.after_request
def caching_and_compression(resp):
    path = request.path
    if path.startswith("/api/") or path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    elif resp.status_code == 200 and request.method == "GET":
        ctype = resp.mimetype or ""
        if ctype == "text/html":
            resp.headers["Cache-Control"] = "no-cache"
        elif path.endswith("products.json") or path.startswith("/i18n/") or path == "/case-model.json":
            resp.headers["Cache-Control"] = "public, max-age=300"
        elif re.search(r"\.(png|jpe?g|webp|avif|gif|svg|ico|woff2?|ttf|mp4|webm)$", path, re.I):
            resp.headers["Cache-Control"] = "public, max-age=604800"
        if ctype == "text/html" or path.endswith(".json"):
            resp.direct_passthrough = False
            resp.add_etag(weak=True)
            resp.make_conditional(request)
    # gzip
    if (resp.status_code == 200 and "gzip" in request.headers.get("Accept-Encoding", "").lower()
            and (resp.mimetype or "").startswith(COMPRESSIBLE) and "Content-Encoding" not in resp.headers):
        resp.direct_passthrough = False
        data = resp.get_data()
        if len(data) > 1024:
            resp.set_data(_gzip_bytes(data))
            resp.headers["Content-Encoding"] = "gzip"
    if (resp.mimetype or "").startswith(COMPRESSIBLE):
        vary = [v.strip() for v in resp.headers.get("Vary", "").split(",") if v.strip()]
        if "Accept-Encoding" not in vary:
            vary.append("Accept-Encoding")
        resp.headers["Vary"] = ", ".join(vary)
    return resp


SHOP_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:" + "".join(" " + h for h in SITE["cspImgHosts"]) + "; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()")
    if (resp.mimetype or "") == "text/html":
        resp.headers.setdefault("Content-Security-Policy", SHOP_CSP)
    if COOKIE_SECURE:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


init_db()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cli(sys.argv[1:])
        raise SystemExit
    mode = "DEV (Links erscheinen hier in der Konsole)" if DEV_MODE else f"SMTP {SMTP_HOST}"
    print(f"{SITE['name']} läuft auf {BASE_URL}  ·  Mail: {mode}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
