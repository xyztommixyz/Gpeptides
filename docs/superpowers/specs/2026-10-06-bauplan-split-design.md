# Konzept: GPeptides in Bauplan (Kern) und Projekt (site) aufteilen

Stand: 2026-10-06 · Branch: `bauplan-split` · Ausgangs-Commit: `9efb7ea`

## Ziel

Aus dem GPeptides-Shop wird ein wiederverwendbarer **Bauplan** für ähnliche Shops (Forschungsprodukte in
Fläschchen, 3D-Darstellung, Forschungsprofil, Hinweis „nur für Forschungszwecke“). GPeptides wird das erste
Projekt, das auf dem Bauplan aufbaut. Verbesserungen am Kern sollen per Git-Merge in alle Projekte fließen.

**Erfolgskriterien**

1. GPeptides verhält sich nach dem Umbau inhaltlich identisch zu `9efb7ea` (nachgewiesen durch Snapshot-Tests).
2. Ein privates Repo `shop-bauplan` existiert mit frischer Historie, ohne GPeptides-Daten, Passwort-Hashes oder Produktbilder, und läuft lokal mit einem Demo-Shop.
3. Das GPeptides-Repo hat `shop-bauplan` als Remote `bauplan`; `git merge bauplan/main` funktioniert ohne Konflikte, solange nur `core/` im Bauplan geändert wurde.

**Nicht-Ziele**

- Kein Umbau für beliebige Produktarten (Kleidung o. Ä.). 3D-Vial und Forschungsprofil bleiben Kern.
- Keine neuen Funktionen, keine Änderungen am Aussehen.
- Kein Deploy auf den Live-Server im Rahmen dieser Arbeit.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Zielgruppe des Bauplans | ähnliche Shops (Variante A) |
| Case-/Nexo-Modul | im Bauplan, per Schalter, Standard aus |
| Verbindung der Repos | Bauplan als Upstream-Remote, Projekt-Repo mit `core/` + `site/` (Variante 1) |

## Aufbau

```
<repo>/
├── core/                      ← in allen Projekten identisch, kommt aus shop-bauplan
│   ├── public/index.html      ← ohne feste Marken-, Produkt- und Case-Daten
│   ├── public/fonts/
│   ├── server/app.py, admin.html, pdfdoc.py, qrcodegen.py, make_thumbs.py, requirements.txt
│   ├── server/.env.example
│   └── deploy/                ← Vorlagen mit Platzhaltern
├── site/                      ← nur dieses Projekt
│   ├── site.json
│   ├── products.json
│   ├── texts.json
│   ├── case.json              (nur wenn Case-Modul an)
│   ├── admins.json            (nicht in Git, .gitignore)
│   ├── thumbs/
│   └── deploy/                ← Caddyfile / Service mit echter Domain
├── tests/                     ← Snapshot- und Smoke-Tests (Kern)
├── docs/
└── README.md                  ← Kern-Doku; projektspezifisches in site/README.md
```

Laufzeitdaten (`*.db`, `backups/`, `.env`) bleiben wie heute außerhalb von Git, Standardort `server/` unter `core/`
bzw. per `DB_PATH`, `BACKUP_DIR`. Neu: `SITE_DIR` (Standard `../../site` relativ zu `core/server`).

## site.json (Schema)

```json
{
  "name": "GPeptides",
  "short": "GP",
  "domain": "gpeptides.net",
  "title": "GPeptides | Research-Grade Peptide",
  "cookiePrefix": "gp",
  "orderPrefix": "GP",
  "skuPrefix": "GP",
  "brandColor": "#2A41E8",
  "mailFrom": "GPeptides <no-reply@gpeptides.net>",
  "imageBase": "https://gpeptides.net/product_images/",
  "certificateUrl": "https://gpeptides.net/de/laborzertifikate/",
  "legalBase": "https://gpeptides.net/{lang}/",
  "discordUrl": "https://discord.gg/pwaEYzeDr",
  "spinCode": "TOM10",
  "cspImgHosts": ["https://gpeptides.net"],
  "features": {
    "cases": true,
    "events": true,
    "affiliate": true,
    "discord": true,
    "spin": true
  },
  "cases": { "partner": "NexoForm", "partnerShort": "Nexo" }
}
```

Werte aus `.env` haben weiterhin Vorrang (z. B. `MAIL_FROM`, `DISCORD_URL`), damit bestehende Server-Konfigurationen
unverändert gelten. Die genaue Feldliste wird beim Umbau aus den tatsächlichen Fundstellen abgeleitet; Felder ohne
Fundstelle werden nicht angelegt.

## Wie der Kern die site-Daten nutzt

- **Server (`app.py`):** lädt `site.json` beim Start; alle festen „GPeptides“-Stellen (Mails, Rechnungen, Backups,
  TOTP-Issuer, SEO-Marke, CSP, Cookie-Namen, Bestellnummern, CSV-Dateinamen) lesen daraus. Produkte aus
  `site/products.json`, Bilder aus `site/thumbs/`. Start-Admins aus `site/admins.json` statt `DEFAULT_ADMINS` /
  `ROLE_ADMINS` im Code. Ist ein Modul per `features` aus, liefern seine Routen 404 und das Admin-Menü blendet es aus.
- **Seite (`index.html`):** enthält leere JSON-Blöcke (`siteData`, `nexoCaseData`) bzw. Platzhalter. Der Server
  füllt sie beim Ausliefern – wie heute schon für `i18nData`. Die doppelte Produktliste im Skript (`P`, `EXTRA`,
  `BUNDLES`) entfällt; die Seite nutzt nur noch die vom Server gelieferten Produktdaten.
  Marke im Logo, Footer, Titel und auf der 3D-Vial-Textur (`GPEPTIDES`, `GPEPTIDES.NET`) kommt aus `siteData`.
- **Texte:** In den Übersetzungen wird „GPeptides“ zu `{shop}`. Projekttexte (Hero, Footer-Claim) können in
  `site/texts.json` je Sprache überschrieben werden; fehlt ein Eintrag, gilt der Kern-Text.
- **Admin (`admin.html`):** Markenname und Partner-Name aus einer vom Server gelieferten Konfiguration.

Folge: Die Seite lässt sich nicht mehr per Doppelklick als Datei öffnen, nur noch über den Server
(README beschreibt schon heute den Serverbetrieb).

## Prüfung

1. **Snapshot vorher** (auf `9efb7ea`): Server lokal mit Kopie der DB und Dev-Mode (kein SMTP). Aufgezeichnet werden
   - Seiten: `/`, `/de/`, `/en/`, `/pl/`, Produktseiten (`/de/bpc-157/`, `/en/glow-stack/`), `/de/cases/`, 404-Seite
   - `/sitemap.xml`, `/robots.txt`, `/products.json`, ausgelieferte `/assets/*.js|css`, `/i18n/*`
   - API: Login-Anfrage (Dev-Link), Verify, `/api/me`, Warenkorb lesen/schreiben, Bestellung Vorkasse DE,
     mit `TOM10`, mit Express, EU-Land, mit Case
   - Mails (Dev-Mode-Ausgabe), Rechnungs-PDF (Text-Inhalt), Admin-Login-Seite, Nexo-Ansicht
2. **Snapshot nachher:** dieselben Aufrufe. Normalisiert werden Zeitstempel, zufällige Bestell-/Token-Werte und
   Prüfsummen in Asset-Dateinamen; alles andere muss gleich sein.
3. Die Aufzeichnung wird zu `tests/` (pytest), läuft gegen `site/` des jeweiligen Projekts. Im Bauplan gibt es
   zusätzlich einen Smoke-Test gegen den Demo-Shop (Seiten laden, Bestellung möglich, Case-Routen 404).
4. Abschließend manueller Durchlauf im Browser: Startseite, Produkt, Warenkorb, Kasse, Cases, Sprache wechseln.

## Repos

1. Umbau auf Branch `bauplan-split` im GPeptides-Repo, in kleinen Commits. Push erst nach Freigabe.
2. `shop-bauplan`: neues privates GitHub-Repo (per `gh`), ein Initial-Commit mit `core/`, `tests/`, Demo-`site/`
   („Demo Labs“, drei Beispielprodukte, Case-Modul aus), README.
   Vor dem Commit Prüfung: keine Hashes, keine GPeptides-Produktdaten, keine echten Adressen/Links.
3. GPeptides: `git remote add bauplan <url>`, einmalig
   `git merge --allow-unrelated-histories -s ours bauplan/main`, damit die Historien verbunden sind und `core/`
   als gemeinsame Basis gilt. Danach ist `core/` in beiden Repos identisch (wird geprüft).
4. Alltag: `git fetch bauplan` + `git merge bauplan/main` (in IntelliJ: Git → Fetch, Git → Merge).
   Rückfluss von Kern-Fixes aus Projekten per Cherry-Pick in `shop-bauplan`.

## Folgearbeiten

- Obsidian-Vault: Bauplan-Notizen auf die neue Struktur aktualisieren (Pfade in Modulnotizen, Checkliste
  „Neues Projekt aus dem Bauplan“, Go-Live: Pfade `core/` und `site/`).
- Live-Server beim nächsten Deploy: systemd `WorkingDirectory` → `core/server`, Caddy-`root` für Schriften →
  `core/public`, für Bilder → `site/thumbs`; `site/admins.json` anlegen bzw. bestehende DB weiterverwenden
  (Admins sind dort schon angelegt).

## Risiken

| Risiko | Umgang |
|---|---|
| `index.html` ist 740 KB in einem Stück; Ersetzungen können Stellen übersehen | Fundstellen per Suche vollständig auflisten, Snapshot-Vergleich deckt Abweichungen auf |
| Asset-Prüfsummen ändern sich | erlaubt; Inhalt der Assets wird verglichen |
| Live-Server bricht beim nächsten Deploy wegen neuer Pfade | Deploy-Hinweise in README und Go-Live-Checkliste |
| Merge-Konflikte, wenn im Projekt am Kern geändert wird | Regel in README: Kern-Änderungen im Bauplan machen, dann mergen |
