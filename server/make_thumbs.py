"""Produktbilder vorab erzeugen (public/thumbs/*.webp + manifest.json).

Warum: Ohne diese Dateien zeichnet jeder Besucher beim ersten Laden alle Vials selbst per WebGL.
Mit den Dateien lädt der Browser nur kleine Bilder und die Seite ist sofort bedienbar.

Wann ausführen: nach Änderungen an Produktnamen, Reinheit, Varianten oder neuen Produkten.
Vergisst man es, ist nichts kaputt: die Seite erzeugt fehlende oder veraltete Bilder dann wie früher selbst.

Voraussetzung (einmalig):  pip install playwright  &&  python -m playwright install chromium
Aufruf (Server muss laufen): python make_thumbs.py [http://localhost:8000]
"""
import base64
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "thumbs")


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.set_default_timeout(15 * 60 * 1000)
        pg.goto(BASE + "/de/?thumbs=export")
        pg.wait_for_function("window.GP_THUMBS")
        data = pg.evaluate("window.GP_THUMBS")
        b.close()
    sig = {}
    for slug, t in data.items():
        raw = base64.b64decode(t["data"].split(",", 1)[1])
        with open(os.path.join(OUT, slug + ".webp"), "wb") as fh:
            fh.write(raw)
        sig[slug] = t["sig"]
        print(f"{slug:<24} {len(raw) // 1024:>4} KB")
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"sig": sig}, fh, indent=1)
    print(f"{len(sig)} Bilder in {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
