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
