## GPeptides

- Shop für Forschungspeptide, Domain gpeptides.net. Repo `xyztommixyz/Gpeptides` (privat), Kern aus `xyztommixyz/shop-bauplan`
  (Remote `bauplan`; lokal liegt der Bauplan meist daneben unter `..\shop-bauplan`).
- Team (Admin-Zugänge auf dem Server): Ruffy, Tom, ZUP. Case-Partner: NexoForm („Nexo“, eigener Admin-Zugang mit Rolle `nexo`),
  Provision 15 % vom Case-Warenwert.
- Alle Module sind an (`site/site.json` → `features`). Spin-Code `TOM10`, kostenloser Versand ab 100 € Warenwert.
- Live-Server: läuft noch mit der alten Ordnerstruktur (`server/`, `public/`) und ist noch nicht der offizielle Shop. Beim nächsten
  Deploy auf `core/` + `site/` umstellen (README „Umzug eines Servers“, Vorlagen in `site/deploy/`), dabei `FREE_SHIPPING_FROM=100`
  in der Live-`.env` prüfen.
- Obsidian: Vault `Dokumente\GPeptides Vault` (Bauplan-Notizen unter `Bauplan/`, dieses Projekt unter `Projekte/GPeptides/`),
  synchronisiert per Obsidian Git mit dem privaten Repo `xyztommixyz/obsidian-gpeptides-vault`. Produktnotizen hängen an
  `GPeptides Produkte.base`, nicht an der Projektnotiz.

## Arbeitsweise

- Auf Deutsch antworten. Bei Unsicherheit (wohin, welche Variante, darf etwas überschrieben/gelöscht werden) kurz nachfragen,
  klare Aufgaben direkt erledigen.
- Pushen und neue GitHub-Repos nur nach Rückfrage.
