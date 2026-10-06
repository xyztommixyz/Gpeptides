#!/usr/bin/env bash
# Neue Version auf dem Server einspielen (ruft der GitHub-Workflow auf, geht auch von Hand):
#
#   bash deploy.sh ARCHIV.tar.gz APP_DIR DIENST [PORT]
#   z. B. bash deploy.sh /tmp/shop-deploy.tar.gz /srv/shop shop 8000
#
# Läuft als Benutzer des Dienstes (dem gehört APP_DIR). Der braucht per sudo nur
#   systemctl stop|start DIENST   (siehe README „Automatisches Deploy“).
#
# Ablauf: Archiv auspacken, Dienst stoppen, Preise vom Server behalten (keep_prices.py), Laufzeitdaten
# (.env, Datenbank, backups/, site/admins.json) in die neue Version verschieben, core/ und site/ austauschen,
# Pakete installieren, starten und prüfen. Antwortet der Shop nicht, kommt automatisch die alte Version zurück.
# Die letzten 5 Versionen bleiben unter APP_DIR/releases/.
set -Eeuo pipefail

ARCHIVE=$1
APP=$2
SERVICE=$3
PORT=${4:-8000}
STAMP=$(date +%Y%m%d-%H%M%S)
NEW="$APP/.deploy-$STAMP"
OLD="$APP/releases/$STAMP"
# Laufzeitdaten relativ zu APP (Muster werden von der Shell aufgelöst)
DATA=(core/server/.env "core/server/*.db" "core/server/*.db-*" core/server/backups site/admins.json)

log() { echo "[deploy] $*"; }

move_data() {  # move_data VON NACH: Laufzeitdaten von einer Version in die andere verschieben
    local from=$1 to=$2 pat f
    for pat in "${DATA[@]}"; do
        for f in $from/$pat; do
            [ -e "$f" ] || continue
            mkdir -p "$to/$(dirname "$pat")"
            mv "$f" "$to/$(dirname "$pat")/"
        done
    done
}

healthy() {
    local i p
    for i in $(seq 1 20); do
        sleep 1
        for p in /de/ /admin/ /api/config; do
            [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$p")" = 200 ] || continue 2
        done
        return 0
    done
    return 1
}

log "Archiv auspacken nach $NEW"
mkdir -p "$NEW" "$APP/releases"
tar xzf "$ARCHIVE" -C "$NEW"

STATE=start
restore() {  # Schritte genau rückwärts auflösen, je nachdem wie weit der Deploy kam
    trap - ERR
    log "FEHLER (Stand: $STATE): alte Version wird wiederhergestellt"
    sudo systemctl stop "$SERVICE" || true
    case $STATE in
        new_in) mv "$APP/site" "$NEW/site" ;&
        new_core_in) mv "$APP/core" "$NEW/core" ;&
        old_site_out) mv "$OLD/site" "$APP/site" ;&
        old_core_out) mv "$OLD/core" "$APP/core" ;&
        data_in_new) move_data "$NEW" "$APP" ;;
    esac
    rmdir "$OLD" 2>/dev/null || true
    rm -rf "$NEW"
    sudo systemctl start "$SERVICE"
    healthy && log "alte Version läuft wieder" || log "ACHTUNG: auch die alte Version antwortet nicht"
    exit 1
}
trap restore ERR

log "Dienst $SERVICE stoppen"
sudo systemctl stop "$SERVICE"
STATE=stopped

python3 "$NEW/core/deploy/keep_prices.py" "$APP/site/products.json" "$NEW/site/products.json"
STATE=data_in_new  # ab hier zählt: auch ein halb verschobener Stand wird zurückgeholt
move_data "$APP" "$NEW"

log "Version austauschen (alte nach $OLD)"
mkdir -p "$OLD"
mv "$APP/core" "$OLD/core"; STATE=old_core_out
mv "$APP/site" "$OLD/site"; STATE=old_site_out
mv "$NEW/core" "$APP/core"; STATE=new_core_in
mv "$NEW/site" "$APP/site"; STATE=new_in

if [ -x "$APP/venv/bin/pip" ]; then
    "$APP/venv/bin/pip" install -q -r "$APP/core/server/requirements.txt"
fi

log "Dienst starten"
sudo systemctl start "$SERVICE"
healthy || { log "Shop antwortet nicht"; false; }

trap - ERR
rm -rf "$NEW" "$ARCHIVE"
ls -1d "$APP"/releases/*/ 2>/dev/null | sort | head -n -5 | xargs -r rm -rf
log "fertig: neue Version läuft"
