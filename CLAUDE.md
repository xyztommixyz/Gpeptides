# Shop-Projekt auf Basis von shop-bauplan

Aufbau: `core/` = Kern aus dem Repo **shop-bauplan** (in allen Shops gleich), `site/` = nur dieses Projekt
(site.json, products.json, texts.json, case.json). Details: `README.md`.

## Regeln

- **Kern nur im Bauplan ändern:** Änderungen an `core/`, `tests/`, `setup.*`, `start.*`, `README.md`, `CLAUDE.md`,
  `.gitattributes`, `.gitignore` zuerst im Repo shop-bauplan machen und committen, dann im Projekt übernehmen:
  `git fetch bauplan` + `git merge bauplan/main`. Im Projekt selbst nur `site/` ändern.
- **Keine Projektdaten im Kern:** Namen, Domains, Partner, Codes und Links kommen aus `site/site.json` über Platzhalter
  `@@NAME@@` (in `core/public/index.html`, `core/server/admin.html`) bzw. `SITE[...]` in `core/server/app.py`.
- **Tests müssen grün sein:** `.venv\Scripts\python -m pytest -q`. Der Golden-Master (`site/golden/`) prüft, dass sich der
  Shop nicht ungewollt ändert. Neu aufnehmen (`python tests/record_golden.py`) nur nach geprüftem Diff
  (`site/golden/bodies` vs. `site/golden/actual`).
- **Nie committen:** `site/admins.json`, `core/server/*.db`, `core/server/.env`, `core/server/backups/`.
- Neuer Rechner: `setup.cmd` (Umgebung, Pakete, Update-Quelle, lokaler Admin, Tests). Shop starten: `start.cmd`.

## Projekt

@site/CLAUDE.md
