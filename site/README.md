# GPeptides – 3D-Shop mit Konto & gespeichertem Warenkorb

```
gpeptides/
├── core/                    ← Kern aus dem Bauplan (shop-bauplan), hier nicht direkt ändern
│   ├── public/index.html    ← komplette Seite (3D-Vials, Wasser-Szene, Warenkorb, Konto-Dialog)
│   └── server/              ← Backend (app.py), Admin-Bereich (admin.html)
├── site/                    ← nur GPeptides: site.json, products.json, texts.json, case.json, thumbs/, deploy/
│   └── README.md            ← diese Datei
└── tests/                   ← Golden-Master- und Funktionstests
```

> Allgemeine Doku zu Aufbau, `site.json`, Updates aus dem Bauplan und Tests: `README.md` im Hauptordner.
> Diese Datei beschreibt die GPeptides-Einstellungen und alle Funktionen im Detail.

## Lokal starten (2 Minuten)

```bash
cd core/server
pip install -r requirements.txt
python app.py
```

Dann **http://localhost:8000** öffnen.
Solange in `.env` kein SMTP eingetragen ist, läuft der Server im **Dev-Modus**: Der Bestätigungslink wird
in der Konsole ausgegeben und im Anmelde-Dialog als „Dev-Modus“-Link angezeigt – so lässt sich alles ohne Mailserver testen.

## Produktion

1. `cp .env.example .env` und ausfüllen:
   - `BASE_URL=https://gpeptides.net` (wichtig für die Links in den E-Mails und für sichere Cookies)
   - SMTP-Zugang eures Mail-Anbieters (Port 587 = STARTTLS, oder `SMTP_SSL=1` mit Port 465)
   - Firmenangaben für die Rechnungen: `SHOP_LEGAL_NAME`, `SHOP_ADDRESS`, `SHOP_VAT_ID` bzw. `SHOP_TAX_NO`, Bankdaten
2. Starten mit einem echten WSGI-Server, z. B.
   `gunicorn -w 3 -b 127.0.0.1:8000 app:app` – fertige Vorlage für den automatischen Start: `site/deploy/gpeptides.service`
3. Davor einen HTTPS-Webserver setzen: Vorlagen in `site/deploy/Caddyfile` (am einfachsten, Zertifikat automatisch) oder
   `site/deploy/nginx.conf`. Er liefert Schriften und Produktbilder direkt aus und komprimiert stärker.
4. Datensicherung läuft automatisch (siehe unten). Den Ordner `core/server/backups` zusätzlich auf einen anderen Rechner oder
   Speicher kopieren lassen (z. B. per Hoster-Backup), sonst hilft die Sicherung bei einem Serverausfall nicht.

## Wie Konto & Warenkorb funktionieren

- **Anmeldung ohne Passwort:** Kunde gibt die E-Mail ein → bekommt einen Bestätigungslink (30 min gültig, nur einmal nutzbar) →
  Klick bestätigt die Adresse (Double-Opt-in) und meldet an. Beim ersten Mal wird dabei das Konto angelegt.
- **Warenkorb:** Gäste-Warenkorb liegt im Browser. Nach der Anmeldung wird er mit dem gespeicherten Warenkorb zusammengeführt
  und danach bei jeder Änderung automatisch im Konto gespeichert – auf jedem Gerät, auf dem man sich anmeldet.
- **Sicherheit:** Tokens und Sessions werden nur gehasht gespeichert, Session-Cookie ist HttpOnly/SameSite,
  schreibende Aufrufe brauchen einen eigenen Header (CSRF-Schutz), Rate-Limit für Login-Anfragen.

## API

| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/api/auth/request` | `{email}` → Bestätigungslink senden |
| GET  | `/api/auth/verify?token=…` | Link aus der E-Mail, setzt Session, leitet auf `/?login=ok` |
| POST | `/api/auth/logout` | Abmelden |
| GET  | `/api/me` | `{user, cart}` |
| GET/PUT | `/api/cart` | Warenkorb lesen / speichern `{items:[{slug,vi,qty}]}` |

## Kasse & Bestellungen

- **Vorkasse (Überweisung)** funktioniert sofort: Bestellung wird gespeichert, Kunde bekommt eine Bestätigung mit Bankdaten
  (`BANK_*` in `.env`), optional geht eine Kopie an `ORDER_NOTIFY`.
- **Online-Zahlung über Stripe** schaltet sich ein, sobald `STRIPE_SECRET_KEY` gesetzt ist. Die Zahlung läuft über die sichere
  Stripe-Seite, die Bestellung wird per Webhook (`/api/stripe/webhook`, Event `checkout.session.completed`) auf „bezahlt“ gesetzt.
- Preise, Versand (`SHIPPING_DE`, `SHIPPING_EU`, `FREE_SHIPPING_FROM`) und Verfügbarkeit rechnet **immer der Server** aus `site/products.json`.
- Angemeldete Kunden sehen ihre letzten Bestellungen im Konto.
- Pflicht-Häkchen: AGB/Widerruf/Datenschutz + Bestätigung „nur für Forschungszwecke“; Button „Zahlungspflichtig bestellen“.

## Affiliate-Codes (10 % Rabatt)

- Kunden geben den Code im Warenkorb oder an der Kasse ein **oder** kommen über einen Partner-Link `https://gpeptides.net/?ref=CODE` –
  der Code wird dann automatisch aktiviert und gemerkt.
- Rabatt (`AFFILIATE_DISCOUNT`, Standard 10 %) und Partner-Provision (`AFFILIATE_COMMISSION`, Standard 10 % vom rabattierten Warenwert ohne Versand)
  rechnet der Server. Jede Bestellung speichert Code, Rabatt und Provision.
- Codes verwalten (im Ordner `core/server`):
  ```
  python app.py add-affiliate ANNA10 "Anna Beispiel" anna@example.de   # anlegen → zeigt den Partner-Link
  python app.py list-affiliates                                        # Bestellungen, Umsatz, Provision (bezahlt/offen)
  python app.py disable-affiliate ANNA10                               # deaktivieren
  python app.py list-orders                                            # letzte Bestellungen
  python app.py set-status GP-261003-ABCDE paid                        # z. B. Überweisung eingegangen
  ```
- Bequemer im Browser: **Admin-Bereich** unter `/admin/` (siehe unten).
- Alternativ per Schnittstelle mit `ADMIN_TOKEN`: `GET/POST /api/admin/affiliates`, `POST /api/admin/orders/<nr>` `{status}`.
- Provision zählt als „bezahlt“, sobald die Bestellung bezahlt ist (Stripe automatisch, Vorkasse per `set-status … paid`).

## Produktdaten

`site/products.json` ist die eine Quelle für Seite und Server: Name, Varianten, Preise, Status (`out_of_stock`, `preorder`),
Artikelnummer, Bild, Zertifikat-Link, Bundle-Bestandteile und Forschungsprofil. Änderungen dort wirken ohne Neustart.

Unter `cases` steht das Vial-Case von NexoForm: Preis (`price`, derzeit **24,99 € als vorläufiger Wert**, bitte mit Nexo
abstimmen), Status, die Inlay-Varianten und die Farbnamen. Kunden können eigene Farben wählen (`customColor`).

**Produktbilder:** `site/thumbs/` enthält fertig gerenderte Bilder aller Vials, damit Besucher sie nicht selbst
per 3D-Grafik zeichnen müssen. Nach Änderungen an Namen, Reinheit, Varianten oder neuen Produkten im Ordner `core/server`
`python make_thumbs.py` ausführen (braucht einmalig `pip install playwright` und `python -m playwright install chromium`).
Vergisst man es, ist nichts kaputt: veraltete oder fehlende Bilder erzeugt die Seite dann wie früher selbst.

## SEO

- Jedes Produkt hat eine echte Adresse wie bisher: `/de/bpc-157/` (und je Sprache `/en/bpc-157/` usw.) – mit eigenem Titel, Beschreibung, Canonical,
  Open-Graph-Bild und strukturierten Produktdaten (Preis, Verfügbarkeit) für Google.
- `/sitemap.xml` und `/robots.txt` werden automatisch erzeugt.

## Sprachen (DE · EN · IT · ES · FR · PL)

- Umschalter oben in der Leiste (Globus-Symbol) bzw. im Handy-Menü. Der Wechsel passiert sofort ohne Neuladen –
  auch mitten in Produktansicht, Warenkorb, Kasse oder auf der Cases-Seite; eingetippte Adressdaten bleiben erhalten.
- Jede Sprache hat eigene Adressen: `/de/`, `/en/bpc-157/`, `/fr/cases/` … `/` leitet automatisch in die passende Sprache
  (zuletzt gewählte Sprache, sonst Browsersprache, sonst Deutsch). Für Google gibt es pro Seite `hreflang`-Verweise,
  übersetzte Titel/Beschreibungen und eine mehrsprachige `sitemap.xml`.
- Bestätigungs- und Bestell-E-Mails sowie die Stripe-Zahlseite kommen in der Sprache, in der bestellt wurde.
- Preise, Datumsangaben und Ländernamen werden je Sprache formatiert; Links zu AGB, Widerruf, Datenschutz, Impressum
  und Laborzertifikaten zeigen auf die jeweilige Sprachversion von gpeptides.net.
- **Texte ändern:** alle Übersetzungen stehen in `core/public/index.html` im Block `<script type="application/json" id="i18nData">`.
  Schlüssel ist immer der deutsche Originaltext, z. B. `"In den Warenkorb": "Add to cart"`. Unter `res` stehen die
  Forschungsprofile je Produkt, unter `server` die E-Mail- und SEO-Texte (die liest auch `core/server/app.py`).
  Fehlt eine Übersetzung, erscheint automatisch der deutsche Text.

## Admin-Bereich

- Adresse: `https://gpeptides.net/admin/` (wird nicht in Suchmaschinen aufgenommen).
- Zugänge: **Ruffy**, **Tom** und **ZUP** mit den vereinbarten Passwörtern. Die Passwörter stehen nirgends im Klartext,
  nur als gesalzener scrypt-Hash in der Datenbank. Beim ersten Start legt der Server die drei Zugänge automatisch an.
- Bereiche:
  - **Übersicht:** Umsatz (30 Tage und gesamt), Bestellungen, offene Vorkasse, Kundenkonten, Umsatz pro Tag als Diagramm
    und eine Liste „Zu erledigen“.
  - **Bestellungen:** Suche, Filter nach Status, Detailansicht mit Positionen und Adresse. Status setzen: bezahlt,
    versendet, storniert, zurück auf offen. Export als CSV (öffnet sich in Excel).
  - **Partner-Codes:** Codes anlegen und ändern (Rabatt, Provision), aktivieren oder deaktivieren, Partner-Link kopieren,
    Umsatz und Provision je Partner.
  - **Cases · Nexo:** alle Bestellungen mit Cases, Versandstatus von Nexo, Abrechnung pro Monat und die Provision für
    den Shop (siehe unten).
  - **Statistik:** Besucher, Seitenaufrufe, Weg vom Besuch zur Bestellung, beliebteste Seiten, Herkunft, Geräte und
    Sprachen. Ohne Cookies und ohne Cookie-Banner (siehe unten).
  - **Bestand:** Stückzahl je Variante (siehe unten).
  - **Kunden:** alle Kundenkonten mit Bestellungen und Umsatz.
  - **Zugang:** eigenes Passwort, Zwei-Faktor-Anmeldung, Datensicherung, Übersicht der Admin-Zugänge.
- Discord (https://discord.gg/pwaEYzeDr): im Admin oben in der Übersicht und in der Seitenleiste. Für Kunden im Footer
  (Knopf „Unsere Community auf Discord“ und Link unter „Info“), im Handy-Menü, in der Kontoübersicht und als Zeile unter
  jeder E-Mail. Anderer Link: `DISCORD_URL` in `.env` (für die E-Mails) und in `core/public/index.html` bzw. `core/server/admin.html`.
- „Fehler im Browser der Besucher“ (Übersicht): JavaScript-Fehler, die auf Geräten eurer Kunden auftreten, gleiche Fehler
  zusammengezählt, ohne Personendaten. So fallen Probleme auf iPhone oder alten Android-Geräten auf, ohne dass jemand
  sich meldet.
- Sicherheit: Anmeldung gilt 12 Stunden, Cookie nur für `/admin` (HttpOnly, SameSite=Strict, über HTTPS „Secure“).
  Nach 8 Fehlversuchen pro IP bzw. 10 pro Benutzer sind 15 Minuten Pause. Fehlversuche und Statusänderungen stehen
  im Server-Protokoll.
- **Bitte die Passwörter nach dem ersten Login ändern und die Zwei-Faktor-Anmeldung einschalten** (Bereich „Zugang“:
  QR-Code mit Google Authenticator, Microsoft Authenticator, Authy oder 1Password scannen, Code eingeben). Danach fragt
  die Anmeldung zusätzlich den 6-stelligen Code ab. Handy verloren: `python app.py reset-2fa NAME`.
  Neue Zugänge oder vergessenes Passwort, im Ordner `core/server`:
  ```
  python app.py set-admin NAME      # anlegen oder Passwort neu setzen (fragt das Passwort ab)
  python app.py remove-admin NAME   # löschen
  python app.py list-admins         # anzeigen
  ```

## Cases mit NexoForm (Zugang „Nexo“)

- Das Vial-Case ist jetzt direkt im Shop kaufbar: Im Case-Konfigurator Farben und Inlay wählen, dann „In den Warenkorb“.
  Jede Konfiguration ist eine eigene Position. Im Warenkorb und in der Kasse steht „Versand durch NexoForm“; bei
  gemischten Bestellungen der Hinweis, dass Cases in einem eigenen Paket kommen.
- **Zugang für Nexo:** Benutzer **Nexo** im Admin-Bereich `/admin/` mit dem vereinbarten Passwort (auch hier nur als Hash
  gespeichert). Nexo sieht ausschließlich:
  - Bestellungen, in denen mindestens ein Case steckt,
  - darin nur die Case-Positionen mit Farben und Inlay, Lieferadresse und E-Mail des Kunden (für den Versanddienst),
  - ob die Bestellung bezahlt ist, Case-Warenwert, Provision für den Shop und seine Auszahlung.
  Peptide, andere Bestellungen, Gesamtsummen, Partner-Codes, Kunden und Einstellungen sieht Nexo nicht. Auch über die
  Schnittstelle ist das gesperrt.
- **Aufteilung:** Bei einer Bestellung mit Cases und Peptiden verschickt ihr die Peptide wie bisher; der Case-Teil
  erscheint bei Nexo. Nexo markiert ihn als versendet (optional mit Sendungsnummer). Das geht erst, wenn die Bestellung
  bezahlt ist. Bei reinen Case-Bestellungen wird damit die ganze Bestellung „versendet“. Storniert ihr eine Bestellung,
  ist auch der Case-Teil storniert.
- **E-Mails an Nexo:** bei jeder neuen Case-Bestellung und sobald sie bezahlt ist, nur mit Case-Positionen und
  Lieferadresse. Empfänger: die E-Mail, die Nexo unter „Zugang“ einträgt, und/oder `NEXO_NOTIFY` in `.env`.
  Versendet Nexo, bekommt `ORDER_NOTIFY` eine kurze Meldung.
- **Provision:** Der Shop bekommt **15 %** vom Case-Warenwert (Startwert, `NEXO_COMMISSION` in `.env`). Änderbar im
  Admin-Bereich unter „Cases · Nexo“ (nur das Team). Jede Bestellung merkt sich den Satz, der beim Kauf galt; auf Wunsch
  lässt sich ein neuer Satz auch auf noch nicht bezahlte Bestellungen übertragen.
  Basis ist der Case-Warenwert nach anteiligem Rabatt (z. B. Partner-Code), ohne Versandkosten. Versandkosten bleiben
  beim Shop; eine Partner-Provision auf Bestellungen mit Cases trägt wie bisher der Shop.
- Abrechnung: „Cases · Nexo“ zeigt Case-Umsatz, Provision und Auszahlung an Nexo pro Monat; CSV-Export für beide Seiten.
- **Für das Team (Ruffy, Tom, ZUP):** „Cases · Nexo“ zeigt dieselben Case-Bestellungen wie Nexos Bereich, zusätzlich
  Provision und Auszahlungen. In der Übersicht steht ein Block „Cases · Nexo: neue Bestellungen“ mit den letzten
  Eingängen (bezahlt oder offen, „neu“ = letzte 24 Stunden), Case-Bestellungen und Case-Umsatz der letzten 30 Tage.
  Übersicht und Nexo-Bereich aktualisieren sich jede Minute von selbst.
- **Auszahlung:** Ist ein Monat vorbei und überwiesen, klickt ihr „Als ausgezahlt markieren“. Der Betrag wird
  festgehalten und es entsteht eine Gutschrift (`GS-2026-00001`) als PDF mit allen Bestellungen des Monats. Nexo sieht
  den Status und kann die Gutschrift herunterladen. Nexos Anschrift für die Gutschrift: `NEXO_ADDRESS` in `.env`.
- Weitere Zugänge, die nur Cases sehen: `python app.py set-admin NAME nexo`.

## Events: Sales und Gewinnspiele

Im Admin-Bereich unter „Events“ (nur das Team). Laufende Events stehen in der Übersicht, die Zahl am Menüpunkt zeigt,
wie viele gerade laufen.

- **Sale:** Titel, optional Text, Beginn und Ende. Rabatt **je Produkt einzeln** einstellbar (z. B. BPC-157 25 %,
  KPV 10 %), dazu optional ein Standard-Rabatt für alle übrigen Peptide und ein eigener Rabatt für das Vial-Case.
  Ein Produkt mit 0 % ist vom Sale ausgenommen. Das Banner zeigt dann „bis zu −25 %“, jede Karte ihren eigenen Rabatt.
  - Im Shop erscheinen ab Beginn ein Banner mit Countdown (oben im Hero und über dem Sortiment), ein „−15 %“-Abzeichen auf
    den Karten und durchgestrichene Preise in Karte, Produktansicht, Warenkorb und Kasse. Nach dem Ende verschwindet
    alles von selbst.
  - Der Server rechnet den Sale-Preis; er steht so auch auf der Rechnung („Sale −15 % (statt …)“).
  - „Auch auf Vial-Cases“: senkt den Case-Warenwert und damit Nexos Auszahlung, vorher mit Nexo absprechen.
  - „Mit Partner-Codes kombinierbar“: aus = ein Code gilt nur für Artikel ohne Sale (die Kasse sagt das dem Kunden).
  - Laufen mehrere Sales gleichzeitig, zählt pro Produkt der höchste Rabatt.
  - Auswertung beim Event: Bestellungen mit Sale-Artikeln, deren Umsatz und wie viel Kunden gespart haben.
- **Gewinnspiel:** Titel, Text, Gewinn, Anzahl Gewinner, Zeitraum, **Teilnahmebedingungen (Pflicht zum Veröffentlichen)**.
  Wer in die Ziehung kommt, stellt ihr pro Gewinnspiel ein:
  - **Automatisch aus Bestellungen:** Jede Bestellung im Gewinnspiel-Zeitraum ist ein Los mit der E-Mail des Kunden.
    Wer dreimal bestellt, hat drei Lose. Standard: nur bezahlte Bestellungen zählen (abschaltbar). Kunden müssen nichts
    tun; im Shop erklärt das Banner, dass jede Bestellung ein Los ist.
  - **Teilnahme per Klick** mit Kundenkonto (ein Los pro Konto), optional nur mit Bestellung im Zeitraum.
  - **Beides** zusammen.
- **Zufallsgenerator (pro Gewinnspiel ein eigener):** Beim Öffnen eines Gewinnspiels im Admin seht ihr alle Lose
  (Bestellnummer, E-Mail, wie viele Lose diese E-Mail hat). „Gewinner ziehen“ lässt die E-Mails kurz durchlaufen und
  zeigt dann die Gewinner. Gezogen wird auf dem Server mit echtem Zufall, jedes Los hat dieselbe Chance. Standard: eine
  E-Mail gewinnt höchstens einmal (umstellbar). Gewinner lassen sich wieder entfernen (z. B. nicht erreichbar) und es wird
  nachgezogen. Lose und Gewinner als CSV. Die Gewinner benachrichtigt ihr selbst per E-Mail.
  - Teilnahmebedingungen und Gewinnspiele für Forschungsprodukte bitte rechtlich prüfen lassen (Veranstalter,
    Teilnahme ab 18, ausgeschlossene Länder, keine Barauszahlung).
- Titel und Text optional auch auf Englisch; Besucher in den anderen Sprachen sehen dann die englische Fassung.
- Entwürfe (nicht veröffentlicht) sind im Shop unsichtbar.

## Neuanmeldungen

In der Übersicht: Diagramm „Neue Kundenkonten pro Tag“ (angelegt und davon bestätigt), dazu neu in 7 und 30 Tagen,
Bestätigungsquote, wie viele der Neuen schon bestellt haben und der Vergleich mit den 30 Tagen davor.

## Expressversand

- In der Kasse wählt der Kunde zwischen Standard- und Expressversand. Aufpreis: `EXPRESS_DE` (Standard 9,90 €) in `.env`;
  ins EU-Ausland nur, wenn `EXPRESS_EU` gesetzt ist. Der Aufpreis gilt auch, wenn der normale Versand kostenlos ist.
- Im Admin sind Express-Bestellungen rot markiert („EXPRESS“). Bezahlte, noch nicht versendete stehen in der Liste immer
  ganz oben, eigener Filter „Express offen“, in der Übersicht ein eigener Punkt „⚡ Express, noch nicht versendet“.
  In der Bestellung steht ein deutlicher Hinweis, bevorzugt zu versenden.
- Auch Nexo sieht bei Case-Bestellungen „EXPRESS“, sie stehen dort ebenfalls oben, und die Mail an Nexo sagt es.
- Mail an den Kunden, Benachrichtigung an `ORDER_NOTIFY` (Betreff „[EXPRESS]“), Rechnung und Kundenkonto zeigen „Express“.

## Rechnungen und Versand

- **Rechnung:** Sobald eine Bestellung bezahlt ist (Stripe meldet es, oder ihr klickt „Als bezahlt markieren“), vergibt
  der Shop eine fortlaufende Rechnungsnummer (`RE-2026-00001` …) und schickt dem Kunden die Zahlungsbestätigung mit der
  Rechnung als PDF im Anhang. Der Kunde findet sie zusätzlich in seinem Konto, ihr im Admin-Bereich bei der Bestellung.
  Die PDFs entstehen ohne Zusatzprogramme; Inhalt: eure Firmenangaben aus `.env`, Kundenadresse, Positionen, Rabatt,
  Versand, Netto und enthaltene Umsatzsteuer (`VAT_RATE`, Standard 19 %). Kleinunternehmer: `SMALL_BUSINESS=1`.
  Bestellungen auf Deutsch bekommen eine deutsche Rechnung, alle anderen eine englische.
- **Storno:** Wird eine bereits berechnete Bestellung storniert, entsteht automatisch eine Stornorechnung (`ST-…`).
  Danach lässt sich der Status nicht mehr ändern (für eine neue Lieferung eine neue Bestellung anlegen).
- **Bitte mit dem Steuerberater klären:** Steuersatz, ob für EU-Kunden andere Sätze gelten (OSS), und ob die Cases über
  euch oder im Namen von NexoForm verkauft werden. Die Rechnung weist derzeit alles als Verkauf durch euch aus.
- **Versand:** Beim Klick auf „Als versendet markieren“ könnt ihr eine Sendungsnummer eintragen; der Kunde bekommt
  eine Versandmail. Mit `TRACKING_URL` in `.env` (z. B. DHL) enthält sie einen „Sendung verfolgen“-Knopf. Versendet Nexo
  das Case, bekommt der Kunde dafür eine eigene Versandmail mit Nexos Sendungsnummer.
- **Kundenkonto:** Bestellungen lassen sich aufklappen: Positionen, Versandstatus mit Sendungsnummer (Peptide und
  Case getrennt), Rechnung und Stornorechnung als PDF.

## Bestand

- Im Admin-Bereich unter „Bestand“ je Variante eine Stückzahl eintragen. Leer = nicht gezählt (wie bisher).
- Jede Bestellung zieht sofort ab, eine Stornierung bucht zurück. Bei 0 zeigt der Shop „Ausverkauft“; einzelne
  ausverkaufte Varianten sind in der Produktansicht durchgestrichen. Bei wenigen Stück steht „Nur noch 3 Stück verfügbar“.
- Bestellt jemand mehr, als da ist, passt die Kasse die Menge an und sagt es dem Kunden. Zwei gleichzeitige
  Bestellungen um das letzte Stück: die zweite bekommt einen Hinweis statt einer doppelten Zusage.
- „Bald ausverkauft“ (Übersicht, Zahl am Menüpunkt): alles mit höchstens `STOCK_LOW` Stück (Standard 5).
- Cases werden auf Bestellung gefertigt und haben keinen Bestand.

## Datensicherung

- Der Server sichert die Datenbank automatisch alle 24 Stunden (`BACKUP_EVERY_HOURS`) nach `core/server/backups`
  (`BACKUP_DIR`), komprimiert. Die letzten 14 bleiben erhalten (`BACKUP_KEEP`).
- Im Admin-Bereich unter „Zugang“: „Jetzt sichern“ und die letzten Sicherungen zum Herunterladen. In der Übersicht steht,
  wann zuletzt gesichert wurde (orange, wenn es länger als zwei Tage her ist).
- Von Hand: `python app.py backup`. Zurückspielen: Server stoppen, Datei entpacken (`gunzip`), als `gpeptides.db`
  ablegen, Server starten.

## Partner und Team in der Kontoübersicht

- **Partner-Dashboard:** Meldet sich ein Partner im Shop mit der E-Mail an, die bei seinem Partner-Code hinterlegt ist
  (per Bestätigungslink, ohne Passwort), erscheint in seiner Kontoübersicht der „Partner-Bereich“: Code und Partner-Link
  zum Kopieren, Bestellungen, Umsatz, Provision bezahlt und offen, Monatsübersicht und letzte Bestellungen.
  Kundendaten (Namen, Adressen, E-Mails) sieht der Partner nicht.
- **Partner-Verwaltung fürs Team:** Wer sich mit einer Admin-E-Mail im Shop anmeldet, sieht in der Kontoübersicht alle
  Partner-Codes mit Zahlen und kann neue Codes anlegen (bestehende ändern geht im Admin-Bereich).
  Admin-E-Mail festlegen: im Admin-Bereich unter „Zugang“ die eigene Shop-E-Mail eintragen, oder in `.env`
  `ADMIN_EMAILS=ruffy@…,tom@…` setzen.
- Der Admin-Bereich `/admin/` selbst bleibt mit Benutzername und Passwort geschützt.

## Handy

- Startseite: Auf dem Handy steht das 3D-Vial auf einer eigenen Bühne unter den Buttons (Lichtkreis, langsam drehender
  Schriftring, Sockel und die Kennzahlen „≥98 % Reinheit“ und „HPLC + MS“ als Hinweisfelder). Die Bühne passt sich
  automatisch an jede Bildschirmgröße an. Beim Laden steigt das Vial von unten auf die Bühne.
- Beim Scrollen bewegt sich das Vial mit seinem Abschnitt, taucht zwischen zwei Abschnitten kurz ab (kleiner werden
  und drehen) und erscheint unter der nächsten Überschrift wieder. So überdeckt es nie Text.
- Flüssigkeit: Das Vial klebt beim Scrollen ohne Nachziehen an seinem Abschnitt; nur Drehung und Größe werden weich
  übergeblendet. Das Ein- und Ausblenden der Adressleiste lässt das Vial nicht mehr springen. Auf dem Handy gibt es
  keine Live-Unschärfe (Menüleiste, Hinweisfelder) über der 3D-Grafik, das spart pro Bild deutlich Rechenzeit.
- Cases: Das Case bleibt oben stehen, nur die Einstellungen darunter scrollen.
  So sieht man jede Änderung sofort am 3D-Modell, und der Schließen-Knopf liegt nie über einem Feld.
- Produktansicht: Sobald der Kaufen-Knopf aus dem Bild scrollt, erscheint unten eine Leiste mit Name, Preis und
  „In den Warenkorb“. Wischen über die Infokarte wechselt zum nächsten oder vorherigen Produkt; oben gibt es dafür
  auch Pfeil-Knöpfe (am Desktop zusätzlich die Tasten `[` und `]`).
- Case-Konfigurator: Preis und „In den Warenkorb“ bleiben unten am Panel stehen.
- Tablets im Hochformat bekommen den Handy-Aufbau mit Bühne (sonst wäre das Vial riesig und läge über dem Text).
  Handys im Querformat: Überschrift richtet sich nach der Höhe, das Vial steht kleiner rechts daneben.
- Sparmodus für schwache Handys: Schafft ein Gerät trotz kleinster Auflösung keine flüssige Bildrate oder ist
  „Datensparen“ an, steht ein Standbild des Vials auf der Bühne. Produktansicht und Cases bleiben 3D.
- Eingabefelder haben mindestens 16 px Schrift, damit iPhones beim Antippen nicht hineinzoomen.
- Größere Tippflächen im Footer und im Warenkorb, Kasse passt auch auf schmale Geräte (360 px).

## Ladezeit

- Über den Server bekommt der Browser nur die gewählte Sprache; andere Sprachen und das 3D-Modell des Cases werden erst
  geladen, wenn man sie braucht.
- Skript und Stylesheet liefert der Server als eigene Dateien (`/assets/app.<prüfsumme>.js|css`), die ein Jahr im
  Browser bleiben. Wiederkehrende Besucher laden nur noch die Seite selbst: rund 9 KB statt 90 KB. Ändert sich
  `index.html`, ändert sich die Prüfsumme und der Browser holt automatisch die neue Version.
- Produktbilder laden erst, wenn eine Karte in die Nähe des Bildschirms kommt.
- Schriften als WOFF2 (rund 20 % kleiner), WOFF als Rückfall für alte Browser.
- Die Seite ist sofort bedienbar: Sie wartet nicht mehr darauf, dass alle Produktbilder per WebGL gezeichnet sind
  (fertige Bilder aus `site/thumbs/`, siehe Produktdaten).
- Schriften liegen auf dem eigenen Server (`core/public/fonts/`, nur lateinische Zeichen, Polnisch extra) statt bei Google.
- Seiten bekommen einen ETag: Ist die Seite unverändert, antwortet der Server nur mit „304“ und schickt nichts erneut.
- Bilder und Schriften werden 7 Tage im Browser zwischengespeichert, `products.json` 5 Minuten.
- Verliert das Handy oder der Grafiktreiber die 3D-Grafik (WebGL-Kontext), baut die Seite die Szene automatisch neu auf.

## Desktop und große Bildschirme

- Am Desktop steht das Vial ebenfalls vor Lichtkreis und Schriftring. Bei schmaleren Fenstern rückt es nach rechts.
- Auf 1440p-, 4K- und Ultrawide-Monitoren passt die Überschrift wieder vollständig, Text und Knöpfe wachsen mit.
- Tastatur: sichtbare Fokus-Rahmen, „Zum Sortiment springen“-Link, 3D-Ansichten mit den Pfeiltasten drehbar,
  Dialoge halten den Fokus.

## Suche, 404 und Statistik

- Über dem Sortiment gibt es eine Suche (Name, Kürzel, Artikelnummer, Klasse, Menge). Sie wirkt zusammen mit den Filtern.
- Unbekannte Adressen zeigen eine eigene 404-Seite mit Suchfeld (vorausgefüllt aus der Adresse) über dem Sortiment.
- Statistik ohne Cookies: gezählt werden Seitenaufrufe sowie „In den Warenkorb“, „Kasse geöffnet“ und Suchen.
  Für „Besucher pro Tag“ bildet der Server aus IP, Browser-Kennung und einem täglich neuen Zufallswert eine Prüfsumme;
  sie wird am Folgetag gelöscht, gespeichert bleibt nur die Anzahl. IP-Adressen werden nicht gespeichert, Bots und
  Browser mit „Do Not Track“ oder „Global Privacy Control“ werden nicht gezählt. Text dazu in `DATENSCHUTZ-ERGAENZUNG.md`.

## Sicherheit

- Strenge Sicherheits-Header auch für den Shop: Content-Security-Policy (nur eigene Skripte, Schriften und Verbindungen;
  Bilder zusätzlich von gpeptides.net), Permissions-Policy (keine Kamera, kein Mikrofon, kein Standort), über HTTPS
  zusätzlich HSTS (Browser verbindet sich nur noch verschlüsselt).
- Zwei-Faktor-Anmeldung für den Admin-Bereich (siehe Admin-Bereich).

## Noch anzubinden

- **Euer Shopsystem:** Sobald feststeht, worauf der Shop läuft, können `products.json` und die Bestellungen direkt daraus kommen bzw. dorthin gehen.
- **Versandkosten & Bankdaten:** In `.env` stehen Beispielwerte – bitte durch eure echten ersetzen.
- **Datenschutz:** Die Textbausteine in `DATENSCHUTZ-ERGAENZUNG.md` prüfen lassen und in die Datenschutzerklärung übernehmen
  (neu: Statistik, Weitergabe an NexoForm bei Case-Bestellungen; Google Fonts entfällt).
- **Case-Preis und Vertrag mit Nexo:** Preis in `products.json` bestätigen; Provision und Versand mit Nexo schriftlich festhalten.
- **SMTP:** Ohne SMTP-Zugang gehen keine E-Mails raus (auch nicht an Nexo).
- **Firmenangaben für Rechnungen** in `.env` eintragen und die erste Rechnung vom Steuerberater ansehen lassen.
- **Auf echten Geräten testen** (siehe Checkliste unten).

## Checkliste für den Test auf echten Geräten

Auf einem iPhone (Safari), einem älteren Android-Handy (Chrome) und einem iPad jeweils kurz durchgehen:

1. Startseite laden: Vial steigt auf die Bühne, Ring dreht sich, nichts überdeckt Text.
2. Langsam und schnell scrollen: Vial bleibt am Abschnitt, taucht zwischen den Abschnitten ab, kein Ruckeln oder Springen.
   Auch die Adressleiste ein- und ausblenden lassen (kurz nach oben scrollen).
3. Handy quer drehen und zurück: Layout passt sich an.
4. Produkt öffnen, nach unten scrollen: Kaufen-Leiste erscheint unten. Über die Infokarte nach links/rechts wischen:
   nächstes Produkt. In den Warenkorb legen.
5. Cases öffnen: Farben und Inlay wählen, „In den Warenkorb“. Warenkorb oben rechts öffnen: Case mit Vorschau sichtbar.
6. Kasse bis zur Bestellung durchspielen (Vorkasse), E-Mail kommt an.
7. Im Admin die Bestellung auf „bezahlt“ setzen: Mail mit Rechnungs-PDF kommt an, PDF öffnet sich auf dem Handy.
8. Sprache wechseln (z. B. Englisch), Hell/Dunkel umschalten.
9. Danach im Admin unter Übersicht „Fehler im Browser der Besucher“ ansehen: Steht dort etwas, mir die Meldung schicken.
