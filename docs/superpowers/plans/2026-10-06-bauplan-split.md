# Bauplan-Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den GPeptides-Shop in einen wiederverwendbaren Kern (`core/`) und projektspezifische Daten (`site/`) aufteilen, daraus das private Repo `shop-bauplan` erzeugen und GPeptides per Git-Remote damit verbinden – ohne dass sich GPeptides inhaltlich ändert.

**Architecture:** Der Kern enthält in `index.html` und `admin.html` Platzhalter der Form `@@NAME@@`, die der Server beim Ausliefern aus `site/site.json` ersetzt (wie heute schon die i18n-Verkleinerung). Server-Konstanten mit Markenbezug lesen aus demselben `site.json`. Ein Golden-Master-Test (Flask-Test-Client) zeichnet vor dem Umbau alle wichtigen Antworten auf und beweist nach jedem Schritt, dass GPeptides gleich bleibt.

**Tech Stack:** Python 3.13, Flask 3.1, SQLite, pytest, Git, GitHub CLI (`gh`).

**Spec:** `docs/superpowers/specs/2026-10-06-bauplan-split-design.md`

## Global Constraints

- Ausgangs-Commit `9efb7ea`; gearbeitet wird auf Branch `bauplan-split`; **kein Push**, bis der Mensch den Endstand freigibt.
- GPeptides muss nach jedem Task den Golden-Master-Test bestehen (Ausnahme nur Task 8, dort mit begründetem Neu-Aufzeichnen).
- Keine neuen Funktionen, keine optischen Änderungen.
- Werte aus `.env` haben Vorrang vor `site.json`.
- In `shop-bauplan` dürfen **keine** Passwort-Hashes, GPeptides-Produktdaten, Produktbilder, echten Adressen, Discord-Links oder `gpeptides`-Strings landen (Ausnahme: keine).
- Interne technische Namen bleiben (Header `X-GP`, Rolle `nexo`, Vendor `"nexo"`, Spalten `nexo_pct` …); geändert werden nur sichtbare Marken-/Partner-Texte.
- Platzhalter-Syntax `@@[A-Z_]+@@`; vor dem Umbau prüfen, dass `@@` in keiner Datei vorkommt.
- Laufzeitdaten (`*.db`, `backups/`, `.env`, `site/admins.json`, `site/golden/bodies/`, `site/golden/actual/`) nie committen.
- Sprache der Doku/Commits: Deutsch. Commit-Nachrichten enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Server-Texte aus i18n:** Mails, Rechnungen, SEO-Titel lesen `i18n()` aus `index.html` – wenn dort `@@SHOP@@` steht, muss `i18n()` die Platzhalter ersetzen, sonst steht „@@SHOP@@“ in Kunden-Mails. Abgedeckt durch Mail-/PDF-Aufzeichnung in Task 1 und Test `test_no_placeholder_leaks` (Task 6).
2. **Asset-Prüfsumme:** `/assets/app.<hash>.js` wird aus dem Seiteninhalt berechnet; wird vor dem Hashen nicht ersetzt, liefert der Browser `@@…@@`. Test `test_no_placeholder_leaks` holt die Assets ab.
3. **Fehlende `site/admins.json` auf frischem Server:** Kein Admin-Zugang, aber der Server muss starten und einen Hinweis ausgeben. Test `test_no_admins_file_starts` (Task 5).
4. **Ausgeschaltetes Case-Modul:** Ein alter Warenkorb mit `nexo-case`-Position darf keine Bestellung mit Case erzeugen. Test `test_cases_off_rejects_case_items` (Task 8).
5. **`texts.json` fehlerhaft (ungültiges JSON):** Server startet trotzdem, nutzt Kern-Texte und loggt den Fehler. Test `test_broken_texts_json_ignored` (Task 7).

---

## Dateistruktur nach dem Umbau

```
gpeptides/
├── core/
│   ├── public/index.html, fonts/            (aus public/)
│   ├── server/app.py, shopsite.py (neu), admin.html, pdfdoc.py, qrcodegen.py, make_thumbs.py, requirements.txt, .env.example
│   └── deploy/Caddyfile, nginx.conf, shop.service   (Vorlagen mit Platzhaltern)
├── site/
│   ├── site.json, products.json, texts.json, case.json
│   ├── admins.example.json   (in Git)   admins.json (nicht in Git)
│   ├── thumbs/               (aus public/thumbs/)
│   ├── deploy/Caddyfile, gpeptides.service
│   ├── golden/golden.json    (in Git; bodies/ und actual/ nicht)
│   └── README.md             (GPeptides-spezifische Doku)
├── tests/harness.py, record_golden.py, test_snapshot.py, test_site.py, test_features.py, conftest.py
├── requirements-dev.txt
├── docs/…
└── README.md (Kern-Doku)
```

Verantwortung `core/server/shopsite.py`: `site.json`/`texts.json`/`case.json`/`admins.json` laden, Platzhalter ersetzen, Produkt-JS erzeugen, Feature-Abfrage. Sonst nichts.

---

### Task 0: Entwicklungsumgebung

**Files:**
- Create: `requirements-dev.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Dateien anlegen**

`requirements-dev.txt`:
```
-r core/server/requirements.txt
pytest>=8.0
```
Bis Task 2 existiert `core/` noch nicht, daher vorerst installieren mit:
```bash
cd "/c/Users/tomho/Desktop/Claude Code Cowork/gpeptides"
python -m venv .venv
.venv/Scripts/python.exe -m pip install -q -r server/requirements.txt "pytest>=8.0"
```

`.gitignore` ergänzen (am Ende):
```
# Entwicklung
.venv/
.pytest_cache/
# Projekt-Laufzeitdaten
site/admins.json
site/golden/bodies/
site/golden/actual/
core/server/.env
core/server/*.db
core/server/*.db-*
core/server/backups/
```

- [ ] **Step 2: Prüfen, dass `@@` nirgends vorkommt**

Run: `grep -c "@@" public/index.html server/admin.html server/app.py`
Expected: `0` für alle drei Dateien.

- [ ] **Step 3: Commit**

```bash
git add requirements-dev.txt .gitignore
git commit -m "Entwicklungsumgebung: pytest, .gitignore für core/ und site/"
```

---

### Task 1: Golden-Master aufzeichnen (vor jedem Umbau)

**Files:**
- Create: `tests/harness.py`, `tests/record_golden.py`, `tests/test_snapshot.py`, `tests/conftest.py`
- Create (generiert): `site/golden/golden.json`

**Interfaces:**
- Produces: `harness.ROOT: Path`, `harness.server_dir() -> Path`, `harness.load_app(tmp: Path, env: dict|None=None) -> module`, `harness.run(tmp: Path, env: dict|None=None) -> dict[str, dict]`, `harness.normalize(text: str, ids: dict) -> str`, `harness.dump_bodies(records: dict, out: Path) -> None`. Records: `{"status": int, "type": str, "headers": dict, "body_sha": str, "body_len": int}`; Bodies für Diff-Zwecke unter `record["_body"]` (wird nicht in golden.json geschrieben).

- [ ] **Step 1: `tests/harness.py` schreiben**

```python
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
    out = [data.decode("latin-1")]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except zlib.error:
            pass
    text = "\n".join(out)
    text = re.sub(r"/(CreationDate|ModDate) *\([^)]*\)", "/DATEFIELD", text)
    return re.sub(r"/ID *\[[^\]]*\]", "/ID", text)


def _record(resp, ids):
    ctype = resp.headers.get("Content-Type", "")
    data = resp.get_data()
    if "pdf" in ctype:
        body = _pdf_text(data)
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
                      "att": [(a[0], hashlib.sha256(_pdf_text(a[1]).encode()).hexdigest()) for a in attachments or []]})

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
```

- [ ] **Step 2: `tests/record_golden.py` und `tests/conftest.py` schreiben**

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
```

`tests/record_golden.py`:
```python
"""Zeichnet den Golden-Master neu auf: python tests/record_golden.py
Schreibt site/golden/golden.json (in Git) und site/golden/bodies/ (lokal, zum Vergleichen)."""
import json
import tempfile

import harness

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        rec = harness.run(tmp)
    out = harness.site_dir() / "golden"
    out.mkdir(parents=True, exist_ok=True)
    (out / "golden.json").write_text(json.dumps(harness.strip(rec), indent=1, sort_keys=True), encoding="utf-8")
    harness.dump_bodies(rec, out / "bodies")
    print(f"{len(rec)} Aufrufe aufgezeichnet -> {out / 'golden.json'}")
```

- [ ] **Step 3: `tests/test_snapshot.py` schreiben**

```python
import json

import harness

GOLDEN = harness.site_dir() / "golden" / "golden.json"


def test_matches_golden(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rec = harness.run(tmp_path)
    actual = harness.strip(rec)
    diff = sorted(k for k in set(golden) | set(actual) if golden.get(k) != actual.get(k))
    if diff:
        harness.dump_bodies({k: rec[k] for k in diff if k in rec}, harness.site_dir() / "golden" / "actual")
    assert not diff, "Abweichungen (Vergleich: site/golden/bodies vs. site/golden/actual): " + ", ".join(diff)
```

- [ ] **Step 4: Aufzeichnen und Stabilität prüfen**

Run: `.venv/Scripts/python.exe tests/record_golden.py`
Expected: `NN Aufrufe aufgezeichnet` (ca. 50). Dann `grep -l '"status": 5' site/golden/golden.json` → keine Ausgabe (kein 500er).
Prüfen, dass jeder Aufruf das erwartete Ergebnis hat: `order 1` und `order 2` Status 200, `admin login` 200, `nexo forbidden` 403, `customer invoice` 200 mit `type` `application/pdf`, mindestens 4 `mail N`-Einträge. Weicht etwas ab (z. B. Feldnamen der API), Szenario in `harness.run` anpassen – nicht den Server.

- [ ] **Step 5: Test zweimal laufen lassen (Determinismus)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot.py -q` (zweimal)
Expected: beide Male `1 passed`. Schlägt es fehl, ist eine Normalisierung lückenhaft: `site/golden/actual/` mit `site/golden/bodies/` vergleichen (`git diff --no-index`) und ein Muster in `PATTERNS` ergänzen. Danach neu aufzeichnen.

- [ ] **Step 6: Commit**

```bash
git add tests/ site/golden/golden.json
git commit -m "Golden-Master-Test für den Ist-Stand (9efb7ea)"
```

---

### Task 2: Dateien nach `core/` und `site/` verschieben

**Files:**
- Move: `public/` → `core/public/` (ohne `products.json`, `thumbs/`), `server/` → `core/server/`, `deploy/` → `site/deploy/` und Kopie nach `core/deploy/`
- Move: `public/products.json` → `site/products.json`, `public/thumbs/` → `site/thumbs/`
- Modify: `core/server/app.py:49` (Pfade), `core/server/app.py:693-704` (`products()`), `core/server/app.py:3098-3104` (`static_files`), `core/server/make_thumbs.py:1,20`, `requirements-dev.txt`

**Interfaces:**
- Produces: `app.SITE_DIR: str` (absoluter Pfad), Umgebungsvariable `SITE_DIR`.

- [ ] **Step 1: Verschieben**

```bash
mkdir -p core site
git mv public core/public
git mv server core/server
git mv core/public/products.json site/products.json
git mv core/public/thumbs site/thumbs
git mv deploy site/deploy
mkdir -p core/deploy && cp site/deploy/* core/deploy/
# Laufzeitdaten (nicht in Git) mitnehmen, falls vorhanden
for f in server/gpeptides.db server/.env; do [ -f "$f" ] && mv "$f" core/server/; done
[ -d server/backups ] && mv server/backups core/server/
ls server 2>/dev/null   # übrig bleiben nur .venv und __pycache__ (alte venv, darf der Mensch löschen)
```
`requirements-dev.txt` Zeile 1 bleibt `-r core/server/requirements.txt` (stimmt jetzt).

- [ ] **Step 2: Test laufen lassen – muss scheitern**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot.py -q`
Expected: FAIL (u. a. `GET /products.json`, `quote …` – Produkte nicht gefunden).

- [ ] **Step 3: Pfade in `app.py` anpassen**

Nach Zeile 49 (`PUBLIC_DIR = …`) einfügen:
```python
SITE_DIR = os.path.abspath(os.environ.get("SITE_DIR", os.path.join(HERE, "..", "..", "site")))
```
In `products()` `path = os.path.join(PUBLIC_DIR, "products.json")` ersetzen durch:
```python
    path = os.path.join(SITE_DIR, "products.json")
```
In `static_files(path)` vor `full = os.path.join(PUBLIC_DIR, path)` einfügen:
```python
    if path == "products.json" or path.startswith("thumbs/"):
        sfull = os.path.join(SITE_DIR, path)
        if os.path.isfile(sfull):
            return send_from_directory(SITE_DIR, path)
```
`make_thumbs.py`: Docstring Zeile 1 `public/thumbs/` → `site/thumbs/`; Zeile 20:
```python
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "site", "thumbs")
```
Danach `grep -n "PUBLIC_DIR" core/server/app.py` durchsehen: Jede weitere Stelle, die `products.json` oder `thumbs` liest, ebenso auf `SITE_DIR` umstellen.

- [ ] **Step 4: Test grün**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot.py -q`
Expected: `1 passed`. (Cache-Control-Header für `/products.json` muss gleich bleiben – das `after_request` prüft nur das Pfadende.)

- [ ] **Step 5: Commit**

```bash
git add -A core site requirements-dev.txt
git status --short | grep -v "^R\|^A\|^M"   # darf nichts Unerwartetes zeigen (keine .db/.env)
git commit -m "Aufteilung in core/ (Kern) und site/ (Projekt), Produktdaten und Bilder aus site/"
```

---

### Task 3: `shopsite.py` – Projektdaten laden und Platzhalter ersetzen

**Files:**
- Create: `core/server/shopsite.py`, `site/site.json`, `tests/test_site.py`

**Interfaces:**
- Produces (in `shopsite.py`):
  - `load(site_dir: str) -> dict` – liest `site.json`, ergänzt abgeleitete Werte.
  - `tokens(s: dict) -> dict[str, str]` – Platzhalter ohne `@@`.
  - `apply(text: str, s: dict) -> str` – ersetzt alle `@@NAME@@`; unbekannte Namen lösen `KeyError` aus.
  - `feature(s: dict, name: str) -> bool`
  - `product_rows(products: list) -> str`, `product_extra(products: list) -> str`, `product_bundles(products: list) -> str` (Task 6)

- [ ] **Step 1: Failing test schreiben** – `tests/test_site.py`

```python
import json
import sys

import harness
import pytest

sys.path.insert(0, str(harness.server_dir()))
import site as shop_site  # noqa: E402  (core/server/shopsite.py, nicht das Python-Modul site)


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
```

- [ ] **Step 2: Test laufen lassen – FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_site.py -q`
Expected: FAIL `ModuleNotFoundError`/`AttributeError: load`.

- [ ] **Step 3: `site/site.json` anlegen**

```json
{
  "id": "gpeptides",
  "name": "GPeptides",
  "short": "GP",
  "domain": "gpeptides.net",
  "cookiePrefix": "gp",
  "orderPrefix": "GP",
  "skuPrefix": "GP",
  "brandColor": "#2A41E8",
  "mailFrom": "GPeptides <no-reply@gpeptides.net>",
  "imageBase": "https://gpeptides.net/product_images/",
  "certificateUrl": "https://gpeptides.net/de/laborzertifikate/",
  "legalBase": "https://gpeptides.net/",
  "discordUrl": "https://discord.gg/pwaEYzeDr",
  "spinCode": "TOM10",
  "cspImgHosts": ["https://gpeptides.net"],
  "features": {"cases": true, "events": true, "affiliate": true, "discord": true, "spin": true},
  "cases": {"partner": "NexoForm", "partnerShort": "Nexo", "partnerUrl": "https://www.nexoform.store"}
}
```

- [ ] **Step 4: `core/server/shopsite.py` schreiben**

```python
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
```

- [ ] **Step 5: Test grün**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: alle bestanden (Snapshot unverändert, weil `app.py` `shopsite.py` noch nicht nutzt).

- [ ] **Step 6: Commit**

```bash
git add core/server/shopsite.py site/site.json tests/test_site.py
git commit -m "site.py: Projektdaten laden und Platzhalter ersetzen"
```

---

### Task 4: Markenstellen in `app.py` aus `site.json`

**Files:**
- Modify: `core/server/app.py` (Zeilen laut Tabelle; Zeilennummern vom Stand `9efb7ea`, können um wenige Zeilen verschoben sein)

**Interfaces:**
- Consumes: `shopsite.load`, `shopsite.feature` aus Task 3.
- Produces: `app.SITE: dict`, `app.PARTNER: str`, `app.PARTNER_SHORT: str`.

- [ ] **Step 1: Laden einbauen** – direkt nach `SITE_DIR = …`:

```python
import site as shop_site  # core/server/shopsite.py

SITE = shop_site.load(SITE_DIR)
PARTNER = SITE["cases"]["partner"]
PARTNER_SHORT = SITE["cases"]["partnerShort"]
```

- [ ] **Step 2: Ersetzungen** (jeweils exakt; Verhalten für GPeptides bleibt gleich)

| Stelle (alt) | neu |
|---|---|
| Docstring Zeile 2 `GPeptides – Backend …` | `Shop-Backend …` (Rest gleich) |
| `DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "gpeptides.db"))` | `… os.path.join(HERE, f"{SITE['id']}.db"))` – **nach** dem `SITE`-Block platzieren |
| `MAIL_FROM = os.environ.get("MAIL_FROM", "GPeptides <no-reply@gpeptides.net>")` | `MAIL_FROM = os.environ.get("MAIL_FROM", SITE["mailFrom"])` |
| `COOKIE = "gp_session"` | `COOKIE = f"{SITE['cookiePrefix']}_session"` |
| `SPIN_CODE = "TOM10"  # …` | `SPIN_CODE = SITE["spinCode"]  # Rabattcode aus dem Vial-Spin-Easter-Egg (site.json)` |
| `ADMIN_COOKIE = "gp_admin"` | `ADMIN_COOKIE = f"{SITE['cookiePrefix']}_admin"` |
| `DISCORD_URL = os.environ.get("DISCORD_URL", "https://discord.gg/pwaEYzeDr")` | `DISCORD_URL = os.environ.get("DISCORD_URL", SITE["discordUrl"])` |
| Kommentar `#   owner = GPeptides-Team, sieht alles` | `#   owner = Shop-Team, sieht alles` |
| `NEXO_ADDRESS = … "NexoForm\|[Straße …"` | erster Teil `"NexoForm"` → `f"{PARTNER}\|[Straße …"` (Rest gleich) |
| Mail-Layout Zeilen ~490 und ~505: `background:#2A41E8;…">GPeptides</td>` | `background:{SITE['brandColor']};…">{_html.escape(SITE['name'])}</td>` (f-String prüfen) |
| `SHOP_LEGAL_NAME = os.environ.get("SHOP_LEGAL_NAME", "GPeptides")` | `… SITE["name"])` |
| `SHOP_EMAIL = os.environ.get("SHOP_EMAIL", "info@gpeptides.net")` | `… f"info@{SITE['domain']}")` |
| `return "GP-" + time.strftime(…)` (`new_order_id`) | `return SITE["orderPrefix"] + "-" + time.strftime(…)` |
| Mail-Signaturen `"\n\nGPeptides")` (~966, ~1123) | `"\n\n" + SITE["name"])` |
| Docstring `Standard: nur das GPeptides-Team (owner).` | `Standard: nur das Shop-Team (owner).` |
| Betreff `f"[GPeptides × Nexo]…"` | `f"[{SITE['name']} × {PARTNER_SHORT}]…"` |
| TOTP `quote('GPeptides:' + user)…&issuer=GPeptides` | `quote(SITE['name'] + ':' + user)…&issuer={urllib.parse.quote(SITE['name'])}` |
| CSV `filename=gpeptides-bestellungen-…` | `filename={SITE['id']}-bestellungen-…` |
| Backups `".gpeptides-{stamp}.db"`, `"gpeptides-{stamp}.db.gz"`, `startswith("gpeptides-")` (2×), Regex `^gpeptides-[0-9_-]+\.db\.gz$` | `SITE['id']` bzw. `re.escape(SITE['id'])` einsetzen |
| Gutschrift-Text `über den GPeptides-Shop verkauften Vial-Cases` | `über den {SITE['name']}-Shop verkauften Vial-Cases` |
| Kommentar `# nur das GPeptides-Team …` | `# nur das Shop-Team …` |
| SEO `"brand": {"@type": "Brand", "name": "GPeptides"}` | `"name": SITE["name"]` |
| SEO Case `"name": "GPeptides × NexoForm"` | `"name": f"{SITE['name']} × {PARTNER}"` |
| CSP `img-src 'self' data: blob: https://gpeptides.net;` | `img-src 'self' data: blob: " + " ".join(SITE["cspImgHosts"]) + ";` (Leerzeichen so setzen, dass für GPeptides exakt der alte String entsteht) |
| `print(f"GPeptides läuft auf …")` | `print(f"{SITE['name']} läuft auf …")` |

Danach: `grep -n -i "gpeptides\|NexoForm" core/server/app.py` – erlaubt sind nur Kommentare, die auf `site.json` verweisen. Jede andere sichtbare Zeichenkette mit `NexoForm` → `PARTNER`.

- [ ] **Step 3: Tests**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: alle bestanden. Bei Abweichung: `git diff --no-index site/golden/bodies/<name>.txt site/golden/actual/<name>.txt`.

- [ ] **Step 4: Commit**

```bash
git add core/server/app.py
git commit -m "app.py: Marke, Domain, Cookies, Nummern und Partner aus site.json"
```

---

### Task 5: Admin-Zugänge aus `site/admins.json`

**Files:**
- Modify: `core/server/app.py` (`DEFAULT_ADMINS`, `ROLE_ADMINS`, `init_db`, `admin_login`), `core/server/shopsite.py`
- Create: `site/admins.json` (lokal, nicht in Git), `site/admins.example.json`
- Test: `tests/test_site.py`

**Interfaces:**
- Produces: `shopsite.admins(site_dir: str) -> dict[str, dict]` → `{"Name": {"hash": str, "role": "owner"|"nexo"}}`, leeres Dict wenn Datei fehlt oder ungültig ist.

- [ ] **Step 1: Failing tests** (an `tests/test_site.py` anhängen)

```python
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
```

- [ ] **Step 2: FAIL prüfen**

Run: `.venv/Scripts/python.exe -m pytest tests/test_site.py -q` → FAIL (`admins` fehlt).

- [ ] **Step 3: `site/admins.json` aus den aktuellen Konstanten erzeugen** (vor dem Löschen!)

```bash
cd core/server && ../../.venv/Scripts/python.exe - <<'EOF'
import json, re
src = open("app.py", encoding="utf-8").read()
ns = {}
exec(re.search(r"DEFAULT_ADMINS = \{.*?\n\}", src, re.S).group(0), ns)
exec(re.search(r"ROLE_ADMINS = \{.*?\}\n", src, re.S).group(0), ns)
out = {n: {"hash": h, "role": "owner"} for n, h in ns["DEFAULT_ADMINS"].items()}
out.update({n: {"hash": h, "role": r} for n, (r, h) in ns["ROLE_ADMINS"].items()})
json.dump(out, open("../../site/admins.json", "w", encoding="utf-8"), indent=2)
print(list(out))
EOF
```
Expected: `['Ruffy', 'Tom', 'ZUP', 'Nexo']`.

`site/admins.example.json`:
```json
{
  "_hinweis": "Kopieren nach admins.json (nicht in Git). Hash erzeugen: python core/server/app.py hash-password",
  "Name": {"hash": "scrypt:…", "role": "owner"}
}
```
(`shopsite.admins` ignoriert Schlüssel, die mit `_` beginnen.)

- [ ] **Step 4: Implementieren**

In `shopsite.py`:
```python
def admins(site_dir):
    path = os.path.join(site_dir, "admins.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {n: {"hash": v["hash"], "role": v.get("role", "owner")}
            for n, v in data.items() if not n.startswith("_") and isinstance(v, dict) and v.get("hash")}
```
In `app.py`: `DEFAULT_ADMINS = {…}` und `ROLE_ADMINS = {…}` löschen und ersetzen durch:
```python
# Start-Zugänge stehen in site/admins.json (nicht in Git): {"Name": {"hash": "scrypt:…", "role": "owner"|"nexo"}}
SITE_ADMINS = shop_site.admins(SITE_DIR)
DUMMY_HASH = generate_password_hash(secrets.token_hex(8))  # für gleich lange Antwortzeit bei unbekannten Namen
```
In `init_db()`:
```python
    if not conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        for name, a in SITE_ADMINS.items():
            if a["role"] == "owner":
                conn.execute("INSERT OR IGNORE INTO admin_users(username,pw_hash,created_at) VALUES(?,?,?)", (name, a["hash"], int(time.time())))
```
und die `ROLE_ADMINS`-Schleife:
```python
    for name, a in SITE_ADMINS.items():
        if a["role"] != "owner":
            conn.execute("INSERT OR IGNORE INTO admin_users(username,pw_hash,created_at,role) VALUES(?,?,?,?)", (name, a["hash"], int(time.time()), a["role"]))
    if not SITE_ADMINS and not conn.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        print("[ADMIN] Keine Zugänge: site/admins.json anlegen oder  python app.py set-admin NAME", flush=True)
```
In `admin_login`: `DEFAULT_ADMINS["Ruffy"]` → `DUMMY_HASH`.
CLI: Unterbefehl `hash-password` ergänzen (fragt per `getpass` ab, druckt `generate_password_hash(pw)`), im `cli`-Docstring aufführen.

- [ ] **Step 5: Tests**

Run: `.venv/Scripts/python.exe -m pytest tests -q` → alle bestanden.
Run: `grep -c "scrypt:" core/server/app.py` → `0`.

- [ ] **Step 6: Commit**

```bash
git add core/server/app.py core/server/shopsite.py site/admins.example.json tests/test_site.py
git status --short site/admins.json   # muss leer sein (ignoriert)
git commit -m "Admin-Zugänge aus site/admins.json statt Passwort-Hashes im Code"
```

---

### Task 6: Platzhalter in `index.html` und `admin.html`, Produktliste und Case-Daten aus `site/`

**Files:**
- Modify: `core/public/index.html`, `core/server/admin.html`, `core/server/app.py` (`_index_html`, `i18n`, `_asset_parts`, `/case-model.json`, `/admin/`-Route, `slim_page`), `core/server/shopsite.py`
- Create: `site/case.json`, `site/golden/products_block.js` (Referenz, in Git)
- Test: `tests/test_site.py`

**Interfaces:**
- Consumes: `shopsite.apply`, `app.SITE`, `app.products()`.
- Produces: `app.index_source() -> str` (Kern-HTML mit ersetzten Platzhaltern, Case-Daten und Produktliste; per mtime von `index.html`, `site.json`, `products.json`, `case.json` gecacht). Alle bisherigen Leser von `index.html` (`_index_html`, `i18n`, `_asset_parts`, `/case-model.json`) nutzen nur noch `index_source()`.
- `shopsite.product_rows(products) -> str`, `shopsite.product_extra(products) -> str`, `shopsite.product_bundles(products) -> str`.

- [ ] **Step 1: Referenzblock sichern** (vor jeder Änderung an `index.html`)

```bash
.venv/Scripts/python.exe - <<'EOF'
t = open("core/public/index.html", encoding="utf-8").read()
i = t.index("const P = [\n"); j = t.index("const BUNDLES=", i); j = t.index("\n", j)
open("site/golden/products_block.js", "w", encoding="utf-8", newline="").write(t[i:j])
print(t[i:j][-300:])
EOF
```

- [ ] **Step 2: Failing tests** (an `tests/test_site.py` anhängen)

```python
def _products():
    return json.loads((harness.site_dir() / "products.json").read_text(encoding="utf-8"))["products"]


def test_product_block_matches_reference():
    ref = (harness.site_dir() / "golden" / "products_block.js").read_text(encoding="utf-8")
    s = shop_site.load(str(harness.site_dir()))
    core = (harness.ROOT / "core" / "public" / "index.html").read_text(encoding="utf-8")
    i = core.index("const P = [\n"); j = core.index("\n", core.index("const BUNDLES=", i))
    p = _products()
    got = shop_site.apply(core[i:j], s, {"PRODUCT_ROWS": shop_site.product_rows(p),
                                         "PRODUCT_EXTRA": shop_site.product_extra(p),
                                         "PRODUCT_BUNDLES": shop_site.product_bundles(p)})
    assert got == ref


def test_no_placeholder_leaks(tmp_path):
    app = harness.load_app(tmp_path)
    c = app.app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    bodies = [page, c.get("/de/?full=1").get_data(as_text=True), c.get("/admin/").get_data(as_text=True),
              c.get("/i18n/en.json").get_data(as_text=True)]
    import re
    for m in re.finditer(r"/assets/app\.[0-9a-f]{12}\.(js|css)", page):
        bodies.append(c.get(m.group(0)).get_data(as_text=True))
    bodies.append(app.tr("en", "home_title"))
    for b in bodies:
        assert "@@" not in b
```

- [ ] **Step 3: FAIL prüfen**

Run: `.venv/Scripts/python.exe -m pytest tests/test_site.py -q` → FAIL (`product_rows` fehlt).

- [ ] **Step 4: Produktliste erzeugen** (`shopsite.py`)

```python
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
    parts = []
    for p in products:
        m = IMG_RE.search(p.get("image", ""))
        if m:
            parts.append(f'{_js(p["slug"])}:[{int(m.group(1))},{_js(m.group(2))}]')
    return "{" + ",".join(parts) + "}"


def product_bundles(products):
    return "{" + ",".join(f'{_js(p["slug"])}:[' + ",".join(_js(b) for b in p["bundle"]) + "]"
                          for p in products if p.get("bundle")) + "}"
```
Die exakte Form (Einrückung, Komma am Ende, Reihenfolge der Felder) an `site/golden/products_block.js` anpassen, bis `test_product_block_matches_reference` grün ist. Weichen einzelne Produkte inhaltlich ab (z. B. Feld nur in der Inline-Liste), Regel in `product_rows` ergänzen – **nicht** `products.json` ändern.

- [ ] **Step 5: `index.html` auf Platzhalter umstellen**

Im Block ab `const P = [` bis Ende der `BUNDLES`-Zeile:
```js
const P = [
@@PRODUCT_ROWS@@
];
```
(die vorhandenen Kommentarzeilen zwischen `];` und `const EXTRA` unverändert lassen)
```js
const EXTRA=@@PRODUCT_EXTRA@@;
const BUNDLES=@@PRODUCT_BUNDLES@@;
P.forEach(p=>{const e=EXTRA[p.slug];if(e){p.sku="@@SKU_PREFIX@@-"+String(e[0]).padStart(4,"0");p.img=`@@IMAGE_BASE@@prod_${e[0]}_${e[1]}.webp`}
  p.cert="@@CERT_URL@@";if(BUNDLES[p.slug])p.bundle=BUNDLES[p.slug]});
```
Inhalt von `<script type="application/json" id="nexoCaseData">…</script>` nach `site/case.json` verschieben (Inhalt exakt, ohne Tags) und im HTML durch `@@CASE_DATA@@` ersetzen.

Übrige Stellen (Fundliste vom Stand `9efb7ea`, Zeilen ±):

| Zeile | alt | neu |
|---|---|---|
| 6 | `<title>GPeptides \| Research-Grade Peptide</title>` | `<title>@@SHOP@@ \| Research-Grade Peptide</title>` |
| 843, 1159, 2178 | Kommentare `GPeptides × NexoForm` | `@@SHOP@@ × @@PARTNER@@` |
| 949, 1102 | `aria-label="GPeptides Startseite"><span class="gp">GP</span>GPeptides</a>` | `aria-label="@@SHOP@@ Startseite"><span class="gp">@@SHORT@@</span>@@SHOP@@</a>` |
| 961, 1102, 1104, 3057 | `https://discord.gg/pwaEYzeDr` | `@@DISCORD@@` |
| 1079 | `<span class="gp">GP</span>GPeptides · Analytik` | `<span class="gp">@@SHORT@@</span>@@SHOP@@ · Analytik` |
| 1105 | `https://gpeptides.net/de/` (4×) | `@@LEGAL_BASE@@de/` |
| 1108, 1109 | `© 2026 GPeptides`, `f-big">GPeptides` | `@@SHOP@@` |
| 1168–1170 | `aria-label="GPeptides × NexoForm"`, `t1">GPeptides`, `t3">NexoForm` | `@@SHOP@@`, `@@PARTNER@@` |
| 1179 | `https://www.nexoform.store` … `Mehr über NexoForm` | `@@PARTNER_URL@@` … `Mehr über @@PARTNER@@` |
| 1180 | `Versand durch NexoForm` | `Versand durch @@PARTNER@@` |
| 1235 | Kommentar `gpeptides.net` | `@@DOMAIN@@` |
| 1293 | `"https://gpeptides.net/"+LANG+` | `"@@LEGAL_BASE@@"+LANG+` |
| 1298 | `BASE_TITLE="GPeptides \| Research-Grade Peptide"` | `"@@SHOP@@ \| Research-Grade Peptide"` |
| 1519 | `fillText("GPEPTIDES",` | `fillText("@@SHOP_UPPER@@",` |
| 1543 | `fillText("GPEPTIDES.NET",` | `fillText("@@DOMAIN_UPPER@@",` |
| 2028, 2648, 3140, 3388 | `t("…GPeptides…")`, `"GPeptides × NexoForm: Vial-Case"`, `" \| GPeptides"` | `@@SHOP@@` / `@@PARTNER@@` im String |
| 2200 | `name:"GPeptides × NexoForm Vial-Case"` | `name:"@@SHOP@@ × @@PARTNER@@ Vial-Case"` |
| 2970, 3204, 3207, 3308 | `NexoForm` in `t("…")` | `@@PARTNER@@` |
| 3025 | `SPIN_CODE="TOM10"` | `SPIN_CODE="@@SPIN_CODE@@"` |

Im i18n-JSON-Block (`id="i18nData"`) alle Vorkommen von `GPeptides` → `@@SHOP@@`, `NexoForm` → `@@PARTNER@@`, `gpeptides.net` → `@@DOMAIN@@` (Schlüssel **und** Werte, 184 Stellen) per Skript:
```bash
.venv/Scripts/python.exe - <<'EOF'
import re
p = "core/public/index.html"
t = open(p, encoding="utf-8").read()
m = re.search(r'(<script type="application/json" id="i18nData">)(.*?)(</script>)', t, re.S)
b = m.group(2).replace("GPeptides", "@@SHOP@@").replace("NexoForm", "@@PARTNER@@").replace("gpeptides.net", "@@DOMAIN@@")
open(p, "w", encoding="utf-8", newline="").write(t[:m.start(2)] + b + t[m.end(2):])
EOF
```
Danach: `grep -n -i -o ".\{40\}\(gpeptides\|nexoform\|TOM10\|discord.gg\).\{20\}" core/public/index.html` → keine Treffer.

`admin.html` (Zeilen ±): Titel `Admin | @@SHOP@@`; 239/251 `logo">@@SHORT@@</div><div><b>@@SHOP@@</b>`; 261/269 Discord → `@@DISCORD@@`; 316/468/471 `NexoForm` → `@@PARTNER@@`, `GPeptides × NexoForm` → `@@SHOP@@ × @@PARTNER@@`; 424 `placeholder="name@gpeptides.net"` → `placeholder="name@@@DOMAIN@@"`. Kommentare 314/765 ebenso. Danach `grep -n -i "gpeptides\|nexoform\|discord.gg" core/server/admin.html` → leer.

- [ ] **Step 6: Server: eine Quelle für die Seite**

In `app.py` `_index_html()` ersetzen durch:
```python
_src = {"key": None, "page": ""}


def _src_files():
    return [os.path.join(PUBLIC_DIR, "index.html"), os.path.join(SITE_DIR, "site.json"),
            os.path.join(SITE_DIR, "products.json"), os.path.join(SITE_DIR, "case.json")]


def index_source():
    """index.html des Kerns mit den Daten dieses Projekts (Platzhalter @@…@@ ersetzt)."""
    key = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in _src_files())
    if key != _src["key"]:
        with open(os.path.join(PUBLIC_DIR, "index.html"), encoding="utf-8") as fh:
            raw = fh.read()
        try:
            with open(os.path.join(SITE_DIR, "case.json"), encoding="utf-8") as fh:
                case_data = fh.read()
        except OSError:
            case_data = "{}"
        prods = (_products_raw().get("products") or [])
        page = shop_site.apply(raw, SITE, {"CASE_DATA": case_data,
                                           "PRODUCT_ROWS": shop_site.product_rows(prods),
                                           "PRODUCT_EXTRA": shop_site.product_extra(prods),
                                           "PRODUCT_BUNDLES": shop_site.product_bundles(prods)})
        _src.update(key=key, page=page)
    return _src["page"]


def _index_html():
    return index_source()
```
`_products_raw()` neu neben `products()`: ruft `products()` auf und gibt `_products.get("raw") or {}` zurück.

Alle Stellen, die `index.html` direkt lesen oder dessen mtime nutzen, auf `index_source()` umstellen:
- `i18n()`: statt Datei lesen `src = index_source()`; Cache-Schlüssel `mt = _src["key"]` statt `os.path.getmtime(path)`; Regex auf `src`.
- `_asset_parts()`: `mt = (index_source(), _src["key"])[1]`; `page = index_source()`.
- `/case-model.json` (Zeile ~3020): Inhalt aus `CASE_RE` auf `index_source()` statt Datei.
`admin_page()` (Route `/admin/`, liest `ADMIN_HTML`): Inhalt durch `shop_site.apply(…, SITE)` schicken.

- [ ] **Step 7: Tests**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: alle bestanden, inkl. Snapshot (Seiten und Assets byte-gleich nach Normalisierung).

- [ ] **Step 8: Commit**

```bash
git add core/public/index.html core/server/admin.html core/server/app.py core/server/shopsite.py site/case.json site/golden/products_block.js tests/test_site.py
git commit -m "Seite und Admin mit Platzhaltern; Produktliste und Case-Daten aus site/"
```

---

### Task 7: Projekttexte `site/texts.json`

**Files:**
- Modify: `core/server/app.py` (`i18n()`), `core/server/shopsite.py`
- Create: `site/texts.json` (Inhalt `{}`)
- Test: `tests/test_site.py`

**Interfaces:**
- Produces: `shopsite.texts(site_dir: str) -> dict` – Form `{"ui": {lang: {key: text}}, "server": {lang: {key: text}}}`; fehlt/ungültig → `{}` und Logzeile `[TEXTS] …`.

- [ ] **Step 1: Failing tests**

```python
def _site_copy(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    for f in ("site.json", "products.json", "case.json"):
        (site / f).write_text((harness.site_dir() / f).read_text(encoding="utf-8"), encoding="utf-8")
    return site


def test_texts_override(tmp_path):
    site = _site_copy(tmp_path)
    (site / "texts.json").write_text(json.dumps({"server": {"de": {"home_title": "Mein Titel"}}}), encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    assert "<title>Mein Titel</title>" in app.app.test_client().get("/de/").get_data(as_text=True)


def test_broken_texts_json_ignored(tmp_path, capsys):
    site = _site_copy(tmp_path)
    (site / "texts.json").write_text("{kaputt", encoding="utf-8")
    app = harness.load_app(tmp_path, {"SITE_DIR": str(site)})
    assert app.app.test_client().get("/de/").status_code == 200
    assert "[TEXTS]" in capsys.readouterr().out
```

- [ ] **Step 2: FAIL prüfen** – `pytest tests/test_site.py -q`.

- [ ] **Step 3: Implementieren**

`shopsite.py`:
```python
def texts(site_dir):
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
```
`app.py` `i18n()`: nach dem Laden der Daten
```python
        over = shop_site.texts(SITE_DIR)
        for part in ("ui", "server", "res"):
            for lang, entries in (over.get(part) or {}).items():
                data.setdefault(part, {}).setdefault(lang, {}).update(entries)
```
und `os.path.getmtime(texts.json)` in den Cache-Schlüssel von `index_source()` aufnehmen (`_src_files()` um `texts.json` ergänzen). Damit die Seite die Overrides auch im Browser bekommt, das `i18nData`-JSON in `index_source()` nach dem Ersetzen mit denselben Overrides zusammenführen (Regex `I18N_RE`, `json.loads`, mergen, `_json_script` zurückschreiben) – **nur wenn** `over` nicht leer ist, damit GPeptides byte-gleich bleibt.
`site/texts.json`: `{}`.

- [ ] **Step 4: Tests** – `pytest tests -q` → alle bestanden.

- [ ] **Step 5: Commit**

```bash
git add core/server/app.py core/server/shopsite.py site/texts.json tests/test_site.py
git commit -m "Projekttexte per site/texts.json überschreibbar"
```

---

### Task 8: Modul-Schalter (cases, events, affiliate, discord, spin)

**Files:**
- Modify: `core/server/app.py`, `core/public/index.html`, `core/server/admin.html`
- Create: `tests/test_features.py`

**Interfaces:**
- Consumes: `shopsite.feature`, `app.SITE`.
- Produces: `app.feature_off_classes() -> str` (z. B. `"no-cases no-spin"`, leer wenn alles an); Decorator `app.needs(feature: str)` → Route liefert `jsonify(error="not_found"), 404`, wenn aus.

- [ ] **Step 1: Failing tests** – `tests/test_features.py`

```python
import json

import harness

ALL_OFF = {"cases": False, "events": False, "affiliate": False, "discord": False, "spin": False}


def _site(tmp_path, features):
    site = tmp_path / "site"
    site.mkdir()
    for f in ("products.json", "case.json"):
        (site / f).write_text((harness.site_dir() / f).read_text(encoding="utf-8"), encoding="utf-8")
    s = json.loads((harness.site_dir() / "site.json").read_text(encoding="utf-8"))
    s["features"] = features
    (site / "site.json").write_text(json.dumps(s), encoding="utf-8")
    return site


def test_cases_off_routes(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    c = app.app.test_client()
    assert c.get("/de/cases/").status_code == 404
    assert c.get("/case-model.json").status_code == 404
    assert 'class="no-cases' in c.get("/de/").get_data(as_text=True)


def test_cases_off_rejects_case_items(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    q = app.app.test_client().post("/api/quote", json={"items": [harness.CASE_ITEM], "country": "DE"}).get_json()
    assert q["lines"] == []


def test_affiliate_off(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    c = app.app.test_client()
    assert c.post("/api/code", json={"code": "TOM10"}).get_json()["valid"] is False
    q = c.post("/api/quote", json={"items": [{"slug": "bpc-157", "vi": 0, "qty": 1}], "country": "DE", "code": "TOM10"}).get_json()
    assert q["discount"] == 0


def test_events_off(tmp_path):
    app = harness.load_app(tmp_path, {"SITE_DIR": str(_site(tmp_path, ALL_OFF))})
    assert app.app.test_client().get("/api/events").get_json()["events"] == []


def test_all_on_has_no_classes(tmp_path):
    app = harness.load_app(tmp_path)
    assert app.feature_off_classes() == ""
```

- [ ] **Step 2: FAIL prüfen** – `pytest tests/test_features.py -q`.

- [ ] **Step 3: Server**

```python
def feature_off_classes():
    return " ".join(f"no-{f}" for f in shop_site.FEATURES if not shop_site.feature(SITE, f))


def needs(feat):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not shop_site.feature(SITE, feat):
                return jsonify(error="not_found"), 404
            return fn(*a, **kw)
        return wrapper
    return deco
```
(`import functools` oben ergänzen.) Anwenden:
- `cases`: `cases()` gibt `{}` zurück, wenn aus. `@needs("cases")` auf `/<lang>/cases/`, `/case-model.json`, alle `/admin/api/nexo/*`. In `sitemap.xml` die Cases-URL nur, wenn an.
- `events`: `public_events()` liefert `events=[]`, wenn aus; `@needs("events")` auf `/api/events/<eid>/enter` und alle `/admin/api/events*`; Sale-Berechnung in `quote()` ignoriert Events, wenn aus.
- `affiliate`: `find_affiliate()` gibt `None`, wenn aus (deckt `/api/code` und `quote()` ab); `@needs("affiliate")` auf `/api/partner`, `/api/team/affiliates` (GET/POST), `/admin/api/affiliates` (GET/POST), `/api/admin/affiliates` (GET/POST). `init_db` legt den Spin-Code nur an, wenn `spin` an und `SPIN_CODE` nicht leer.
- `discord`: Discord-Zeile in `mail_layout` nur, wenn an **und** `DISCORD_URL` gesetzt.
- Seite: in `render_page()` nach dem `<html lang=…>`-Ersatz: wenn `feature_off_classes()` nicht leer, `<html lang="{lang}">` → `<html lang="{lang}" class="{feature_off_classes()}">`. Ebenso in `admin_page()`.

- [ ] **Step 4: Seite und Admin**

In `index.html`/`admin.html` jedes Element, das zu einem Modul führt, mit `data-f="<modul>"` markieren (Cases-Links/Abschnitt, Code-Eingabe in Warenkorb und Kasse, Partner-Bereich im Konto, Discord-Links, Events-Menü im Admin, Partner-Codes-Menü, „Cases · Nexo“-Menü). Fundstellen: `grep -n 'cases\|Cases\|discord\|code' core/public/index.html | grep -n '<a \|<button\|<section\|<div class="'`; im Admin die `nav`-Einträge. Ins Haupt-Stylesheet beider Dateien:
```css
.no-cases [data-f="cases"],.no-events [data-f="events"],.no-affiliate [data-f="affiliate"],.no-discord [data-f="discord"]{display:none!important}
```
Im Skript beim Spin-Easter-Egg die Auslösung mit `if(document.documentElement.classList.contains("no-spin"))return;` absichern.

- [ ] **Step 5: Tests und begründetes Neu-Aufzeichnen**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: `test_features.py` grün; `test_snapshot` darf **nur** bei `asset css`, `asset js`, `GET /de/?full=1`, `GET /admin/` und den Seiten abweichen, in denen `data-f` ergänzt wurde. Prüfen:
```bash
git diff --no-index --word-diff site/golden/bodies site/golden/actual | grep -v '^ ' | grep -E '^\+|^-|\{\+|\[-' | head -60
```
Erlaubt sind ausschließlich `data-f="…"`-Attribute, die CSS-Regel oben und die `no-spin`-Zeile. Dann neu aufzeichnen:
```bash
.venv/Scripts/python.exe tests/record_golden.py && .venv/Scripts/python.exe -m pytest tests -q
```

- [ ] **Step 6: Commit** (Golden getrennt)

```bash
git add core tests/test_features.py
git commit -m "Modul-Schalter: cases, events, affiliate, discord, spin"
git add site/golden/golden.json
git commit -m "Golden-Master neu: nur data-f-Markierungen und Schalter-CSS"
```

---

### Task 9: Deploy-Vorlagen und Doku aufteilen

**Files:**
- Modify: `core/deploy/Caddyfile`, `core/deploy/nginx.conf`; Rename `core/deploy/gpeptides.service` → `core/deploy/shop.service`
- Modify: `site/deploy/Caddyfile`, `site/deploy/gpeptides.service`, `site/deploy/nginx.conf`
- Modify: `README.md` (→ Kern-Doku), Create: `site/README.md`
- Modify: `core/server/.env.example`

- [ ] **Step 1: Kern-Vorlagen generisch**

`core/deploy/*`: `gpeptides.net` → `example.com`, `/srv/gpeptides` → `/srv/SHOP`, `GPeptides Shop` → `Shop`, `User=gpeptides` → `User=shop`. Pfade auf neue Struktur:
- Caddy: `@static path /fonts/* /favicon.ico` mit `root * /srv/SHOP/core/public`; zusätzlicher Block `@thumbs path /thumbs/*` mit `root * /srv/SHOP/site`.
- Service: `WorkingDirectory=/srv/SHOP/core/server`, `EnvironmentFile=/srv/SHOP/core/server/.env`.
- nginx analog (`alias`-Pfade).

- [ ] **Step 2: GPeptides-Vorlagen** – `site/deploy/*` gleiche Struktur mit `gpeptides.net` und `/srv/gpeptides`.

- [ ] **Step 3: Doku**

`README.md`: alle GPeptides-spezifischen Angaben (Admin-Namen Ruffy/Tom/ZUP, Nexo-Abschnitt mit Firmennamen, Discord-Link, `gpeptides.net`-Beispiele, Case-Preis 24,99 €) nach `site/README.md` verschieben; im Kern-README neutral formulieren („Partner-Fulfillment (Case-Modul)“, `example.com`). Neue Abschnitte im Kern-README:
1. **Aufbau `core/` und `site/`** (Baum aus der Spec, Tabelle der `site.json`-Felder, Schalter).
2. **Neues Projekt aus dem Bauplan** (Repo aus Template, `site/` füllen, `admins.json` per `python core/server/app.py hash-password`).
3. **Updates aus dem Bauplan holen** (`git fetch bauplan && git merge bauplan/main`, IntelliJ: Git → Fetch, Git → Merge…). Regel: Änderungen an `core/` im Bauplan machen.
4. **Tests** (`python -m pytest tests -q`, Golden neu: `python tests/record_golden.py`).
5. **Umzug eines bestehenden Servers** (Pfade alt → neu, `DB_PATH` auf bestehende DB setzen, `site/admins.json` nicht nötig, wenn die DB schon Admins hat).
`core/server/.env.example`: Kopfzeilen neutral (`BASE_URL=https://example.com`, `SMTP_USER=no-reply@example.com`, `MAIL_FROM=` auskommentiert mit Hinweis „Standard aus site.json“), `SITE_DIR` dokumentieren.

- [ ] **Step 4: Prüfen**

Run: `grep -rn -i "gpeptides\|nexoform\|ruffy\|discord.gg\|TOM10" core/ README.md tests/ requirements-dev.txt`
Expected: keine Treffer.
Run: `.venv/Scripts/python.exe -m pytest tests -q` → alle bestanden.

- [ ] **Step 5: Commit**

```bash
git add -A core site README.md
git commit -m "Deploy-Vorlagen und Doku in Kern und Projekt aufgeteilt"
```

---

### Task 10: Repo `shop-bauplan` anlegen

**Files:**
- Create (außerhalb): `C:/Users/tomho/Desktop/Claude Code Cowork/shop-bauplan/` mit `core/`, `tests/`, `site/` (Demo), `README.md`, `.gitignore`, `requirements-dev.txt`, `docs/superpowers/specs/…`

- [ ] **Step 1: Kopieren**

```bash
B="/c/Users/tomho/Desktop/Claude Code Cowork/shop-bauplan"
G="/c/Users/tomho/Desktop/Claude Code Cowork/gpeptides"
mkdir "$B" && cd "$G"
git archive HEAD core tests README.md .gitignore requirements-dev.txt docs | tar -x -C "$B"
mkdir -p "$B/site/thumbs" "$B/site/deploy" "$B/site/golden"
cp site/admins.example.json "$B/site/"
```

- [ ] **Step 2: Demo-Site anlegen**

`$B/site/site.json`:
```json
{
  "id": "demolabs",
  "name": "Demo Labs",
  "short": "DL",
  "domain": "demo-labs.example",
  "features": {"cases": false, "events": true, "affiliate": true, "discord": false, "spin": false}
}
```
`$B/site/products.json`: `{"currency": "EUR", "updated": "2026-10-06", "products": [...], "cases": []}` mit drei Produkten (`demo-a`, `demo-b`, `demo-water`) im Schema von GPeptides (`slug, sku "DL-0000"…, name, cls, variants, purity, accent, tags, image "", certificate "", shopUrl "", research{short,intro,focus,stage}` – neutrale Texte wie „Beispielprodukt A“). `$B/site/texts.json`: `{}`. `$B/site/case.json`: `{}`. `$B/site/deploy/`: Kopie von `core/deploy/`. `$B/site/README.md`: „Demo-Projekt – beim Anlegen eines neuen Shops ersetzen.“
`$B/site/golden/`: leer lassen; `tests/test_snapshot.py` so anpassen, dass er sich mit `pytest.skip("kein Golden-Master für dieses Projekt")` überspringt, wenn `golden.json` fehlt (diese Änderung auch in GPeptides übernehmen, siehe Step 5).

- [ ] **Step 3: Smoke-Test für den Bauplan** – `$B/tests/test_smoke.py`

```python
import harness


def test_demo_shop_runs(tmp_path):
    app = harness.load_app(tmp_path)
    c = app.app.test_client()
    page = c.get("/de/").get_data(as_text=True)
    assert c.get("/de/").status_code == 200 and "Demo Labs" in page and "@@" not in page
    assert c.get("/de/demo-a/").status_code == 200
    assert c.get("/de/cases/").status_code == 404
    q = c.post("/api/quote", json={"items": [{"slug": "demo-a", "vi": 0, "qty": 1}], "country": "DE"}).get_json()
    assert q["lines"] and q["total"] > 0
```
`tests/test_site.py`-Tests, die GPeptides-Werte prüfen (`test_load_gpeptides`, `test_tokens_and_apply`, `test_product_block_matches_reference`), im Bauplan mit `pytest.skip`, wenn `site.json` nicht `id == "gpeptides"` hat – sauberer: diese drei Tests in GPeptides nach `site/tests/test_gpeptides.py` verschieben (eigener `conftest.py` mit Pfad auf `tests/`), sodass `tests/` im Kern projektneutral ist. `pytest` aus dem Repo-Root mit `testpaths = tests site/tests` in neuer `pytest.ini` (Kern-Datei, beide Repos).

- [ ] **Step 4: Tests im Bauplan**

```bash
cd "$B" && python -m venv .venv && .venv/Scripts/python.exe -m pip install -q -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
```
Expected: alle bestanden (Snapshot übersprungen).

- [ ] **Step 5: Gleiche Kern-Änderungen in GPeptides** (Skip bei fehlendem Golden, `pytest.ini`, verschobene GPeptides-Tests) – dort `pytest -q` → alle bestanden; Commit „Tests: Kern projektneutral, GPeptides-Tests in site/tests“. Danach im Bauplan `core/`, `tests/`, `pytest.ini` erneut aus GPeptides kopieren, sodass sie identisch sind:
`diff -r "$G/core" "$B/core" && diff -r "$G/tests" "$B/tests"` → keine Ausgabe.

- [ ] **Step 6: Geheimnis-Prüfung**

```bash
cd "$B" && grep -rn -i "gpeptides\|nexoform\|ruffy\|scrypt:32768\|discord.gg\|TOM10\|pwaEYzeDr" --exclude-dir=.venv . | grep -v "docs/superpowers"
```
Expected: keine Treffer. (`docs/superpowers/` enthält Spec und Plan dieses Umbaus mit GPeptides-Bezug → **nicht** in den Bauplan kopieren: `rm -rf "$B/docs/superpowers"`; danach Befehl ohne `grep -v` wiederholen → keine Treffer.)

- [ ] **Step 7: Repo erstellen und pushen** (nur nach Freigabe durch den Menschen)

```bash
cd "$B" && git init -b main && git add -A && git commit -m "Shop-Bauplan: Kern und Demo-Projekt

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
gh repo create xyztommixyz/shop-bauplan --private --source . --push
gh repo edit xyztommixyz/shop-bauplan --template
gh repo view xyztommixyz/shop-bauplan --json visibility,isTemplate
```
Expected: `{"isTemplate":true,"visibility":"PRIVATE"}`.

---

### Task 11: GPeptides mit dem Bauplan verbinden

- [ ] **Step 1: Remote und einmaliger Merge**

```bash
cd "/c/Users/tomho/Desktop/Claude Code Cowork/gpeptides"
git remote add bauplan https://github.com/xyztommixyz/shop-bauplan.git
git fetch bauplan
git merge --allow-unrelated-histories -s ours bauplan/main -m "Bauplan als Basis verbunden (einmalig, Inhalt bleibt)"
```

- [ ] **Step 2: Prüfen, dass der Kern identisch ist**

Run: `git diff bauplan/main HEAD --stat -- core tests pytest.ini requirements-dev.txt`
Expected: keine Ausgabe.
Run: `.venv/Scripts/python.exe -m pytest -q` → alle bestanden.

- [ ] **Step 3: Probe-Update** (beweist, dass Merges funktionieren, ohne etwas zu ändern)

```bash
git merge bauplan/main
```
Expected: `Already up to date.`

---

### Task 12: Abschluss

- [ ] **Step 1: Lokal im Browser prüfen**

```bash
cd core/server && ../../.venv/Scripts/python.exe app.py
```
http://localhost:8000: Startseite (3D-Vial mit „GPEPTIDES“), Produkt öffnen, in den Warenkorb, Kasse bis Bestellübersicht, `/de/cases/` Konfigurator, Sprache EN, `/admin/` Login-Seite. Server stoppen.

- [ ] **Step 2: Obsidian-Vault aktualisieren** (`C:/Users/tomho/Documents/GPeptides Vault`)

- `Bauplan/Bauplan Übersicht.md`: Baum durch den neuen (`core/`, `site/`, `tests/`) ersetzen; Abschnitt „Projektdaten (`site/`)“ mit Tabelle der `site.json`-Felder und Schalter; Repo-Link `xyztommixyz/shop-bauplan`.
- Modulnotizen: Property `dateien` auf `core/…`- bzw. `site/…`-Pfade; bei optionalen Modulen Zeile „Schalter: `features.<name>` in `site.json`“.
- `Checklisten/Neues Projekt aus dem Bauplan.md`: Schritte 2–3 ersetzen durch „Auf GitHub: shop-bauplan → Use this template → privat“, „`git remote add bauplan …`“, „`site/` füllen, `admins.json` anlegen“.
- `Checklisten/Go-Live.md`: Punkt „Pfade `core/server`, `core/public`, `site/thumbs` in Service/Caddy“.
- `Projekte/GPeptides/GPeptides.md`: `repo`, Abschnitt „Bauplan-Updates holen“.

- [ ] **Step 3: Endstand dem Menschen vorlegen** – Zusammenfassung, Testergebnis, offene Punkte (Live-Server-Umzug, alte `server/.venv` löschbar). **Push von `bauplan-split` erst nach Freigabe**, dann Merge nach `main` nach Wunsch des Menschen.
