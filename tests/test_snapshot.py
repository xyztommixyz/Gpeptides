import json

import harness

GOLDEN = harness.site_dir() / "golden" / "golden.json"


def test_matches_golden(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rec = harness.run(tmp_path)
    actual = harness.strip(rec)
    diff = sorted(k for k in set(golden) | set(actual) if golden.get(k) != actual.get(k))
    if diff:
        harness.dump_bodies({k: rec[k] for k in diff if k in rec}, harness.site_dir() / "golden" / "actual")
    assert not diff, "Abweichungen (Vergleich: site/golden/bodies vs. site/golden/actual): " + ", ".join(diff)
