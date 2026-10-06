"""Beim Deploy: Preise kommen immer vom Server (im Admin unter „Preise & Versand“ geändert), alles andere aus Git.

    python3 keep_prices.py SERVER/site/products.json NEU/site/products.json

Bestehende Produkt-Varianten (gleicher slug + gleiches Varianten-Label) und Cases (gleicher slug) behalten den Preis
vom Server. Neue Produkte und Varianten bekommen den Preis aus Git. Die neue Datei wird an Ort und Stelle geändert.
"""
import json
import sys


def keep_prices(server, new):
    """Preise aus server in new übernehmen. Gibt die Liste der Abweichungen zurück (Text je Preis)."""
    old = {(p["slug"], v["label"]): v["price"] for p in server.get("products", []) for v in p.get("variants", [])}
    old_cases = {c["slug"]: c["price"] for c in server.get("cases", []) if "price" in c}
    notes = []
    for p in new.get("products", []):
        for v in p.get("variants", []):
            k = (p["slug"], v["label"])
            if k in old and old[k] != v["price"]:
                notes.append(f"{p['name']} ({v['label']}): {old[k]} statt {v['price']} aus Git")
                v["price"] = old[k]
    for c in new.get("cases", []):
        if c.get("slug") in old_cases and old_cases[c["slug"]] != c.get("price"):
            notes.append(f"{c['name']}: {old_cases[c['slug']]} statt {c.get('price')} aus Git")
            c["price"] = old_cases[c["slug"]]
            c.pop("note", None)  # wie beim Speichern im Admin
    return notes


def main(server_path, new_path):
    try:
        with open(server_path, encoding="utf-8") as fh:
            server = json.load(fh)
    except FileNotFoundError:
        print("keep_prices: keine products.json auf dem Server, Preise aus Git")
        return
    with open(new_path, encoding="utf-8") as fh:
        new = json.load(fh)
    notes = keep_prices(server, new)
    if notes:
        with open(new_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(new, fh, ensure_ascii=False, indent=1)
    print(f"keep_prices: {len(notes)} Preis(e) vom Server behalten")
    for n in notes:
        print("  " + n)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
