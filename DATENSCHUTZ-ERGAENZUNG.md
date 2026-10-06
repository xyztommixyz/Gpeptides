# Textbausteine für die Datenschutzerklärung

Diese Abschnitte beschreiben, was der neue Shop technisch speichert. Sie sind als Ergänzung zur bestehenden
Datenschutzerklärung auf gpeptides.net gedacht. **Bitte vor dem Veröffentlichen von eurem Datenschutz-Berater oder
Anwalt prüfen lassen** und Platzhalter in eckigen Klammern ausfüllen. Dies ist keine Rechtsberatung.

---

## Kundenkonto und Anmeldung per E-Mail-Link

Du kannst ein Kundenkonto anlegen, indem du deine E-Mail-Adresse eingibst. Wir senden dir daraufhin einen
Bestätigungslink (Double-Opt-in). Erst mit dem Klick auf diesen Link wird dein Konto bestätigt und du wirst angemeldet.
Ein Passwort wird nicht gespeichert.

Gespeichert werden: E-Mail-Adresse, Zeitpunkt der Registrierung und der Bestätigung. Der Anmeldelink ist 30 Minuten
gültig und nur einmal nutzbar; in unserer Datenbank liegt er ausschließlich als Prüfsumme (Hash).

Nach der Anmeldung setzen wir ein Cookie (`gp_session`, HttpOnly, 30 Tage), damit du angemeldet bleibst. Dieses Cookie
ist für die von dir gewünschte Funktion technisch erforderlich (§ 25 Abs. 2 Nr. 2 TDDDG).

Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Vertrag bzw. vorvertragliche Maßnahmen). Das Konto wird gelöscht, sobald
du uns darum bittest, soweit keine gesetzlichen Aufbewahrungspflichten entgegenstehen.

## Gespeicherter Warenkorb

Ohne Anmeldung liegt dein Warenkorb nur in deinem Browser (Local Storage). Nach der Anmeldung speichern wir den
Warenkorb (Produkt, Variante, Menge) in deinem Konto, damit er auf allen Geräten verfügbar ist.
Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO.

## Bestellungen

Für die Abwicklung einer Bestellung verarbeiten wir: Name, ggf. Firma, Lieferadresse, E-Mail-Adresse, bestellte
Produkte, Preise, Zahlart, Bestellstatus, Sprache der Bestellung sowie einen eingelösten Partner-Code.
Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO; für die Aufbewahrung Art. 6 Abs. 1 lit. c DSGVO in Verbindung mit den
handels- und steuerrechtlichen Aufbewahrungsfristen (§ 257 HGB, § 147 AO).

Bestellbestätigungen versenden wir per E-Mail über [Name des E-Mail-Anbieters / SMTP-Dienst, Sitz].

## Online-Zahlung über Stripe

Wählst du „Online bezahlen“, wirst du zur Zahlungsseite der Stripe Payments Europe, Ltd., 1 Grand Canal Street Lower,
Grand Canal Dock, Dublin, Irland, weitergeleitet. Dabei übermitteln wir Bestellnummer, E-Mail-Adresse und die
Bestellpositionen mit Preisen. Deine Zahlungsdaten gibst du direkt bei Stripe ein; wir erhalten sie nicht.
Stripe kann Daten auch in die USA übermitteln; Stripe ist unter dem EU-US Data Privacy Framework zertifiziert.
Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO. Datenschutzhinweise von Stripe: https://stripe.com/de/privacy

## Partner-Codes (Affiliate)

Rufst du die Seite über einen Partner-Link auf (z. B. `?ref=CODE`) oder gibst du einen Rabattcode ein, speichern wir den
Code in deinem Browser (Local Storage, `gp_ref`), damit der Rabatt bis zur Bestellung erhalten bleibt. Bei einer
Bestellung wird der Code mit der Bestellung gespeichert, um den Rabatt zu gewähren und die Provision des Partners zu
berechnen. Der Partner erhält keine personenbezogenen Daten von dir, nur die Anzahl und den Wert der Bestellungen.
Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Rabatt) und Art. 6 Abs. 1 lit. f DSGVO (Abrechnung mit Partnern).

## Speicherung im Browser (Local Storage)

Die Seite speichert folgende Einstellungen nur in deinem Browser. Sie werden nicht an uns übertragen, außer der
Warenkorb nach der Anmeldung:

| Schlüssel | Zweck |
|---|---|
| `gp_cart` | Warenkorb |
| `gp_lang` | gewählte Sprache (zusätzlich als Cookie `gp_lang`, damit Seiten direkt in deiner Sprache ausgeliefert werden) |
| `gp_theme` | heller oder dunkler Modus |
| `gp_ref` | eingelöster Partner-Code |
| `gp_case_colors`, `gp_case_inlay` | gewählte Farben und Inlay im Case-Konfigurator |

Diese Speicherungen sind für die von dir aufgerufenen Funktionen erforderlich (§ 25 Abs. 2 Nr. 2 TDDDG). Du kannst sie
jederzeit über die Einstellungen deines Browsers löschen.

## Server-Protokolle und Missbrauchsschutz

Beim Aufruf der Seite verarbeitet unser Server technisch notwendige Daten (IP-Adresse, Zeitpunkt, aufgerufene Adresse,
Browser-Kennung). Zum Schutz vor Missbrauch begrenzen wir die Anzahl von Anmelde-, Code- und Bestellversuchen pro
IP-Adresse; dafür wird die IP-Adresse kurzzeitig im Arbeitsspeicher gehalten und nicht dauerhaft gespeichert.
Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (Sicherheit und Stabilität des Angebots).
[Speicherdauer der Webserver-Logs eures Hosters ergänzen.]

## Cases von NexoForm

Bestellst du ein Vial-Case, wird es von [Firmenname und Anschrift von NexoForm] gefertigt und direkt an dich versendet.
Dafür übermitteln wir NexoForm nur die Angaben, die für Herstellung und Versand des Cases nötig sind: Bestellnummer,
die Case-Positionen (Farben, Inlay, Menge), Name, ggf. Firma, Lieferadresse und E-Mail-Adresse (für die
Versandbenachrichtigung) sowie, ob die Bestellung bezahlt ist. Andere Produkte deiner Bestellung erfährt NexoForm nicht.
Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung). [Prüfen lassen: eigenständige Verantwortung von
NexoForm oder Auftragsverarbeitung, ggf. Vertrag nach Art. 28 DSGVO.]

## Gewinnspiele

Nimmst du an einem Gewinnspiel teil, speichern wir mit deinem Kundenkonto die Teilnahme (E-Mail-Adresse, Zeitpunkt) und
ggf. den Gewinn. Wir nutzen die Daten nur zur Durchführung des Gewinnspiels und zur Benachrichtigung der Gewinner und
löschen die Teilnahmen [3 Monate] nach Ende des Gewinnspiels. Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO
(Teilnahme nach den Teilnahmebedingungen).

## Rechnungen

Für jede bezahlte Bestellung erstellen wir eine Rechnung mit Name, ggf. Firma, Anschrift, Bestellpositionen und Beträgen
und senden sie dir per E-Mail. Rechnungen bewahren wir nach den gesetzlichen Fristen auf (§ 147 AO, § 257 HGB: in der
Regel 10 Jahre). Rechtsgrundlage: Art. 6 Abs. 1 lit. b und lit. c DSGVO.

## Fehlerberichte der Seite

Tritt beim Laden oder Bedienen der Seite ein technischer Fehler im Browser auf, sendet die Seite eine kurze Meldung an
unseren Server: Fehlermeldung, betroffene Datei und Zeile, aufgerufene Seite und den Browsertyp (z. B. „Safari iOS“).
Es werden keine IP-Adressen, Cookies oder Eingaben gespeichert; Meldungen werden nach 30 Tagen gelöscht.
Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einer fehlerfreien Seite).

## Datensicherung

Zum Schutz vor Datenverlust sichern wir die Datenbank des Shops täglich; Sicherungen werden nach [14] Tagen gelöscht.

## Reichweitenmessung ohne Cookies

Um zu verstehen, welche Seiten genutzt werden, zählen wir Seitenaufrufe sowie, wie oft Produkte in den Warenkorb
gelegt, die Kasse geöffnet und die Suche genutzt wird. Dabei werden keine Cookies gesetzt und nichts auf deinem Gerät
gespeichert. Gespeichert werden: aufgerufene Seite, Datum, Sprache, Gerätetyp (Handy, Tablet, Desktop, abgeleitet aus
der Fensterbreite) und die Domain der verweisenden Seite. Um Besucher pro Tag zu zählen, bildet der Server aus
IP-Adresse, Browser-Kennung und einem täglich wechselnden Zufallswert eine Prüfsumme. Die IP-Adresse selbst wird nicht
gespeichert, die Prüfsummen und der Zufallswert werden nach Ablauf des Tages gelöscht. Ein Personenbezug lässt sich
danach nicht mehr herstellen. Ist in deinem Browser „Do Not Track“ oder „Global Privacy Control“ aktiv, zählen wir
dich nicht. Die Auswertung erfolgt nur auf unserem eigenen Server, es werden keine Daten an Dritte übermittelt.
Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einer funktionierenden, nutzerfreundlichen Seite).

## Schriftarten

Die Schriften Archivo, Oswald und JetBrains Mono liegen auf unserem eigenen Server. Beim Aufruf der Seite wird keine
Verbindung zu Google oder anderen Schriftanbietern hergestellt.
[Hinweis für euch: Einen bisherigen Abschnitt zu Google Fonts in der Datenschutzerklärung könnt ihr streichen, sobald
diese Version live ist.]
