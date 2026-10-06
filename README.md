# Shop-Bauplan – 3D-Shop mit Konto, Kasse und Admin

Wiederverwendbarer Shop für Forschungsprodukte in Fläschchen: 3D-Darstellung, Kundenkonto per E-Mail-Link,
gespeicherter Warenkorb, Kasse (Vorkasse, optional Stripe), Rechnungen, Partner-Codes, Events, Bestand,
sechs Sprachen und Admin-Bereich. Python/Flask + SQLite, keine Fremddienste nötig.

Jedes Projekt (jeder Shop) besteht aus dem gemeinsamen **Kern** (`core/`) und seinen eigenen **Projektdaten** (`site/`).

## Aufbau

```
<projekt>/
├── core/                      ← Kern, in allen Projekten gleich (kommt aus shop-bauplan)
│   ├── public/index.html      ← komplette Seite mit Platzhaltern @@…@@
│   ├── public/fonts/
│   ├── server/app.py          ← Backend
│   ├── server/shopsite.py     ← liest site/ und ersetzt die Platzhalter
│   ├── server/admin.html      ← Admin-Bereich /admin/
│   ├── server/pdfdoc.py, qrcodegen.py, make_thumbs.py, requirements.txt, .env.example
│   └── deploy/                ← Vorlagen für Caddy, nginx, systemd
├── site/                      ← nur dieses Projekt
│   ├── site.json              ← Name, Domain, Kürzel, Links, Modul-Schalter
│   ├── products.json          ← Produkte, Preise, Varianten, Forschungsprofil (+ "cases")
│   ├── texts.json             ← eigene Texte statt der Kern-Texte (optional)
│   ├── case.json              ← 3D-Daten des Case-Konfigurators (nur mit Modul "cases")
│   ├── admins.json            ← Start-Zugänge für den Admin (nicht in Git!)
│   ├── thumbs/                ← vorgerenderte Produktbilder
│   ├── deploy/                ← Caddy/nginx/systemd mit echter Domain
│   ├── golden/golden.json     ← Golden-Master dieses Projekts (Tests)
│   └── README.md              ← Projekt-Doku
└── tests/                     ← Tests (Kern)
```

Laufzeitdaten (`core/server/*.db`, `core/server/backups/`, `core/server/.env`, `site/admins.json`) stehen nie in Git.

## site.json

| Feld | Bedeutung | Standard |
|---|---|---|
| `id` | technischer Name: Datenbank `<id>.db`, Backups, CSV-Dateinamen | – (Pflicht) |
| `name` | Shop-Name in Seite, Mails, Rechnungen, SEO, Zwei-Faktor-App | – (Pflicht) |
| `short` | Kürzel im Logo und auf dem Vial-Etikett | – (Pflicht) |
| `domain` | Domain ohne `https://` | – (Pflicht) |
| `cookiePrefix` | Präfix der Cookies (`<präfix>_session`, `<präfix>_admin`) | erste 8 Zeichen von `id` |
| `orderPrefix`, `skuPrefix` | Bestellnummern `XX-260101-ABCDE`, Artikelnummern `XX-0001` | `short` |
| `brandColor` | Kopfzeile der E-Mails | `#2A41E8` |
| `mailFrom` | Absender (`.env` `MAIL_FROM` hat Vorrang) | `Name <no-reply@domain>` |
| `imageBase` | Adresse der Produktbilder (`prod_<nr>_<hash>.webp`) | `https://domain/product_images/` |
| `certificateUrl` | Link „Laborzertifikate“ | leer |
| `legalBase` | Basis der Rechtsseiten (`<legalBase><sprache>/impressum/` …) | `https://domain/` |
| `discordUrl` | Community-Link (`.env` `DISCORD_URL` hat Vorrang) | leer |
| `spinCode` | Rabattcode aus dem Vial-Spin-Easter-Egg | leer |
| `cspImgHosts` | fremde Bild-Domains für die Content-Security-Policy | `[]` |
| `features` | Modul-Schalter, siehe unten | alle aus |
| `cases.partner`, `cases.partnerShort`, `cases.partnerUrl` | Case-Partner (Name in Seite/Mails, Kurzname, Website) | leer |

**Modul-Schalter** (`features`): `cases` (Case-Konfigurator mit Partner-Fulfillment), `events` (Sales und
Gewinnspiele), `affiliate` (Partner-Codes), `discord` (Community-Links), `spin` (Easter Egg mit Rabattcode).
Ausgeschaltete Module liefern 404, ihre Bedienelemente sind in Shop und Admin ausgeblendet.

**Eigene Texte** (`texts.json`): `{"ui": {"de": {"<deutscher Originaltext>": "<neu>"}}, "server": {"de": {"home_title": "…"}}}`.
Fehlt ein Eintrag, gilt der Kern-Text. Eine ungültige Datei wird ignoriert (Hinweis `[TEXTS]` im Log).

## Lokal starten

**Windows, einmal pro Rechner:** `setup.cmd` (Doppelklick oder im Terminal). Legt die Python-Umgebung `.venv` an,
installiert die Pakete, trägt im Projekt die Update-Quelle `bauplan` ein, legt bei leerer Datenbank einen lokalen
Admin-Zugang „Lokal“ an und lässt die Tests laufen. Mehrfach ausführbar.

**Starten:** `start.cmd` (anderer Port: `start.cmd -Port 8001`), dann **http://localhost:8000** öffnen.

Ohne die Skripte (Linux/Mac):
```bash
python -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
cd core/server && ../../.venv/bin/python app.py
```

Ohne SMTP in `core/server/.env` läuft der Server im **Dev-Modus**: Anmeldelinks und Mails erscheinen in der Konsole.
Für die Produktbilder (`make_thumbs.py`) zusätzlich: `.venv\Scripts\python -m pip install playwright` und
`.venv\Scripts\python -m playwright install chromium`.

## Module im Überblick

- **Konto & Login per Link:** Double-Opt-in, Link 30 min gültig, Session-Cookie HttpOnly/SameSite, Rate-Limit.
- **Warenkorb:** Gast im Browser, nach Anmeldung im Konto gespeichert und zusammengeführt.
- **Kasse:** Vorkasse sofort; Stripe Checkout, sobald `STRIPE_SECRET_KEY` gesetzt ist (Webhook `/api/stripe/webhook`).
  Preise, Rabatte, Versand und Bestand rechnet immer der Server.
- **Versand:** `SHIPPING_DE`, `SHIPPING_EU`, `FREE_SHIPPING_FROM` (Warenwert nach Rabatt), Express (`EXPRESS_DE/EU`), `TRACKING_URL`.
  Die Versandwerte aus `.env` sind nur Startwerte; im Admin unter „Preise & Versand“ gespeicherte Werte haben Vorrang.
- **Preise & Versand** (Admin): Produktpreise je Variante, Versand DE/EU, „versandkostenfrei ab“, Express-Aufpreis; der
  Case-Partner (Rolle `nexo`) darf nur den Case-Preis ändern, die jeweils andere Seite bekommt eine Mail. Erlaubt sind
  0,50 € bis 10.000 € je Preis, beim Versand 0 bis 1.000 €. Gilt sofort für neue Bestellungen. Jede Änderung steht im
  Verlauf (Zeit, Person, alt → neu). Vor jeder Preisänderung wird `site/products.json` nach `BACKUP_DIR/products/`
  gesichert (die letzten 200). Preise werden nur im Admin geändert: das automatische Deploy behält für bestehende
  Produkte immer den Preis vom Server (siehe „Automatisches Deploy“). Wer `site/products.json` von Hand auf den
  Server kopiert, überschreibt dagegen die Admin-Preise.
- **Rechnungen:** fortlaufende PDF-Rechnungen und Stornorechnungen, Firmenangaben aus `.env`.
- **Partner-Codes** (`affiliate`): Rabatt und Provision, Partner-Links `/?ref=CODE`, Partner-Dashboard im Konto.
- **Events** (`events`): Sales mit Rabatt je Produkt und Countdown, Gewinnspiele mit Ziehung auf dem Server.
- **Bestand:** Stückzahl je Variante, „Ausverkauft“, „Nur noch 3 Stück“.
- **Case-Konfigurator** (`cases`): Partner fertigt und versendet; eigener Admin-Zugang (Rolle `nexo`), Provision, Gutschriften.
- **Admin `/admin/`:** Übersicht, Bestellungen, Kunden, Statistik ohne Cookies, Bestand, Datensicherung, Zwei-Faktor.
- **Sprachen:** DE, EN, IT, ES, FR, PL; Übersetzungen im `i18nData`-Block von `core/public/index.html`.
- **SEO & Ladezeit:** echte Produkt-URLs je Sprache, Sitemap, strukturierte Daten; Assets mit Prüfsumme, ETag, Lazy Loading.

Wichtige Befehle (im Ordner `core/server`):
```
python app.py set-admin NAME [owner|nexo]   # Admin-Zugang anlegen / Passwort ändern
python app.py hash-password                 # Passwort-Hash für site/admins.json
python app.py add-affiliate CODE "Name" mail # Partner-Code anlegen
python app.py list-orders | backup | reset-2fa NAME
```

## Neues Projekt aus dem Bauplan

1. Auf GitHub `shop-bauplan` → **Use this template** → neues **privates** Repo.
2. Klonen und `setup.cmd` ausführen (trägt den Bauplan als Update-Quelle `bauplan` ein).
3. `site/` füllen: `site.json`, `products.json`, Produktbilder (`python core/server/make_thumbs.py` bei laufendem Server),
   bei Bedarf `texts.json` und `case.json`, `site/deploy/` mit echter Domain, `site/README.md`.
4. Admin-Zugang für den Server: `site/admins.example.json` nach `site/admins.json` kopieren, Hash mit `python core/server/app.py hash-password`.
   Lokal reicht der Zugang „Lokal“ aus `setup.cmd`.
5. `core/server/.env` aus `.env.example` anlegen (SMTP, Bank, Firma, Versand).
6. Golden-Master für das Projekt aufnehmen: `python tests/record_golden.py`.

## Updates aus dem Bauplan holen

```bash
git fetch bauplan
git merge bauplan/main
python -m pytest -q
```

In IntelliJ: **Git → Fetch**, dann **Git → Merge…** → `bauplan/main`.
**Regel:** Änderungen an `core/` und `tests/` werden im Bauplan gemacht und dann in die Projekte gemergt. Im Projekt nur
`site/` ändern. Ein Fehler, der in einem Projekt behoben wurde, wird per Cherry-Pick in den Bauplan übernommen.

## Tests

```bash
python -m pytest -q                 # alle Tests
python tests/record_golden.py       # Golden-Master neu aufnehmen (nach gewollten Änderungen)
```

Der Golden-Master ruft rund 50 Seiten und Abläufe auf (Seiten, Login, Bestellungen, Mails, Rechnungs-PDF, Admin)
und vergleicht sie mit `site/golden/golden.json`. Bei Abweichungen liegen die Inhalte zum Vergleich in
`site/golden/bodies/` (Aufnahme) und `site/golden/actual/` (aktueller Lauf).

## Deploy

Vorlagen in `core/deploy/`, Projekt-Fassung in `site/deploy/`:
- systemd: `WorkingDirectory=/srv/<projekt>/core/server`, `EnvironmentFile=…/core/server/.env`,
  `gunicorn -w 3 -b 127.0.0.1:8000 app:app`.
- Caddy/nginx: `/fonts/*` aus `core/public`, `/thumbs/*` aus `site`, alles andere an den Python-Server.

**Umzug eines Servers mit der alten Struktur** (`public/`, `server/`):
1. Code neu auschecken (Ordner `core/` und `site/`).
2. Bestehende `server/.env`, Datenbank und `backups/` nach `core/server/` verschieben – oder `DB_PATH` und `BACKUP_DIR` in `.env` setzen.
3. systemd-Dienst und Caddy/nginx auf die neuen Pfade umstellen, `systemctl daemon-reload`, Dienst und Webserver neu starten.
4. `site/admins.json` ist nicht nötig, wenn die Datenbank schon Admin-Zugänge hat.

**Automatisches Deploy** (GitHub Actions): `core/deploy/deploy.yml` im Projekt nach `.github/workflows/deploy.yml`
kopieren. Bei jedem Push auf `main` laufen die Tests; nur wenn alle grün sind, lädt GitHub den Stand per SSH hoch und
`core/deploy/deploy.sh` spielt ihn ein:
- Dienst stoppen, Preise vom Server behalten (`keep_prices.py`: bestehende Varianten und Cases behalten den
  Server-Preis, neue Produkte/Varianten nehmen den Preis aus Git), `.env`, Datenbank, `backups/` und
  `site/admins.json` in die neue Version verschieben, `core/` und `site/` austauschen, Pakete installieren, starten.
- Antworten `/de/`, `/admin/` und `/api/config` nach 20 s nicht mit 200, kommt automatisch die alte Version zurück.
- Die letzten 5 Versionen liegen unter `APP_DIR/releases/`.

Einrichtung (einmalig):
1. Schlüsselpaar nur für GitHub erzeugen: `ssh-keygen -t ed25519 -N "" -C github-deploy -f deploy_key`.
2. Auf dem Server: öffentlichen Schlüssel beim Dienst-Benutzer eintragen
   (`~/.ssh/authorized_keys`, Zeile mit `restrict ` davor) und ihm per sudo nur den Dienst erlauben:
   `/etc/sudoers.d/<dienst>-deploy` mit
   `<benutzer> ALL=(root) NOPASSWD: /usr/bin/systemctl stop <dienst>, /usr/bin/systemctl start <dienst>`.
   Der Benutzer braucht eine Login-Shell (`/bin/bash`) und muss `APP_DIR` besitzen.
3. In GitHub (Settings → Secrets and variables → Actions): Secret `DEPLOY_SSH_KEY` = privater Schlüssel; Variablen
   `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_DIR` (z. B. `/srv/shop`), `DEPLOY_SERVICE`, `DEPLOY_KNOWN_HOSTS`
   (Ausgabe von `ssh-keyscan HOST`). Ohne `DEPLOY_HOST` laufen nur die Tests.

Von Hand geht es auch: `bash core/deploy/deploy.sh ARCHIV.tar.gz APP_DIR DIENST [PORT]`.
