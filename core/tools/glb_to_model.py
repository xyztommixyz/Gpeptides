"""3D-Modell (glTF 2.0, .glb oder .gltf) in das Modell-Format des Shops umwandeln (site/models/<slug>.json).

Aufruf:  python core/tools/glb_to_model.py EINGABE.glb site/models/<slug>.json [--z-up] [--flat]
  --z-up   Quelle ist Z-oben (z. B. aus CAD) statt Y-oben wie im glTF-Standard: wird nach Y-oben gedreht
  --flat   fehlende Normalen flach (kantig) statt weich berechnen

Was passiert:
- Knoten-Hierarchie (matrix bzw. translation/rotation/scale) wird eingerechnet, alle Meshes der Szene kommen hinein.
- Dreiecke (auch Strips/Fans) mit POSITION, NORMAL (fehlt sie: berechnet) und Indizes.
- Je Material ein Teil: baseColorFactor (in sRGB umgerechnet), metallicFactor, roughnessFactor, Alpha (nur alphaMode BLEND).
- Texturen, UVs, Vertex-Farben, Animationen, Morph-Targets und Skinning werden ignoriert (Hinweis).
- Draco/Meshopt-komprimierte Dateien gehen nicht: in Blender ohne Kompression exportieren.

Ausgabe (Format v1, siehe README „Eigenes 3D-Modell“):
  {"version":1,"parts":[{"name","p","n","i","count","index32","color","metal","rough","alpha"}],"bounds":{"min","max"},"triangles"}
  p/n = base64 float32 xyz (little-endian), i = base64 uint16 (index32 = false) oder uint32, color = sRGB 0..1.
Der Shop rechnet das Modell selbst auf Vial-Größe; Einheiten und Ursprung sind daher egal. Grenzen im Shop: 200 000 Dreiecke,
8 MB JSON, 64 Teile; darüber wird das Standard-Vial gezeigt.

Nur Python-Standardbibliothek.
"""
import argparse
import base64
import json
import math
import os
import struct
import sys
from array import array

MAX_TRIANGLES = 200_000
MAX_BYTES = 8 * 1024 * 1024
MAX_PARTS = 64

COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
NORM_DIV = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0}


def warn(msg):
    print("Hinweis: " + msg, file=sys.stderr)


class GltfError(Exception):
    pass


# ------------------------------------------------------------------ Datei lesen
def read_gltf(path):
    """-> (gltf-JSON, [Puffer als bytes])"""
    with open(path, "rb") as fh:
        data = fh.read()
    base = os.path.dirname(os.path.abspath(path))
    if data[:4] == b"glTF":
        magic, version, length = struct.unpack_from("<4sII", data, 0)
        if version != 2:
            raise GltfError(f"glTF-Version {version} wird nicht unterstützt (nur 2.0)")
        pos, doc, bin_chunk = 12, None, None
        while pos + 8 <= min(length, len(data)):
            clen, ctype = struct.unpack_from("<II", data, pos)
            chunk = data[pos + 8:pos + 8 + clen]
            if ctype == 0x4E4F534A:
                doc = json.loads(chunk.decode("utf-8"))
            elif ctype == 0x004E4942 and bin_chunk is None:
                bin_chunk = bytes(chunk)
            pos += 8 + clen + (-clen % 4)
        if doc is None:
            raise GltfError("GLB ohne JSON-Teil")
    else:
        doc = json.loads(data.decode("utf-8"))
        bin_chunk = None
    buffers = []
    for i, b in enumerate(doc.get("buffers", [])):
        uri = b.get("uri")
        if uri is None:
            if bin_chunk is None:
                raise GltfError("Puffer ohne Daten")
            buffers.append(bin_chunk)
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            p = os.path.normpath(os.path.join(base, uri.replace("%20", " ")))
            with open(p, "rb") as fh:
                buffers.append(fh.read())
    return doc, buffers


def read_accessor(doc, buffers, idx):
    """Accessor als flache Liste von Zahlen (normalisierte Ganzzahlen -> 0..1 bzw. -1..1) + Anzahl Komponenten."""
    acc = doc["accessors"][idx]
    if "sparse" in acc:
        raise GltfError("Sparse-Accessoren werden nicht unterstützt")
    fmt, size = COMP[acc["componentType"]]
    nc, count = NCOMP[acc["type"]], acc["count"]
    if "bufferView" not in acc:
        return [0.0] * (nc * count), nc
    bv = doc["bufferViews"][acc["bufferView"]]
    buf = buffers[bv["buffer"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    elem = size * nc
    stride = bv.get("byteStride") or elem
    if stride == elem:
        arr = array(fmt)
        arr.frombytes(buf[start:start + elem * count])
        if sys.byteorder == "big":
            arr.byteswap()
        out = arr.tolist()
    else:
        st = struct.Struct("<" + fmt * nc)
        out = []
        for k in range(count):
            out.extend(st.unpack_from(buf, start + k * stride))
    if acc.get("normalized") and fmt in NORM_DIV:
        d = NORM_DIV[fmt]
        out = [max(v / d, -1.0) for v in out]
    return out, nc


# ------------------------------------------------------------------ Matrizen (spaltenweise wie glTF)
def mat_mul(a, b):
    o = [0.0] * 16
    for c in range(4):
        for r in range(4):
            o[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return o


IDENT = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def node_matrix(node):
    if "matrix" in node:
        return [float(x) for x in node["matrix"]]
    tx, ty, tz = node.get("translation", [0, 0, 0])
    qx, qy, qz, qw = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    r = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
         2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
         2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy)]
    return [r[0] * sx, r[1] * sx, r[2] * sx, 0, r[3] * sy, r[4] * sy, r[5] * sy, 0,
            r[6] * sz, r[7] * sz, r[8] * sz, 0, tx, ty, tz, 1]


def normal_matrix(m):
    """Inverse-Transponierte des 3x3-Teils (zeilenweise) und Determinante."""
    a, b, c = m[0], m[4], m[8]
    d, e, f = m[1], m[5], m[9]
    g, h, i = m[2], m[6], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-20:
        return [1, 0, 0, 0, 1, 0, 0, 0, 1], det
    # Kofaktormatrix / det = (M^-1)^T
    cof = [e * i - f * h, -(d * i - f * g), d * h - e * g,
           -(b * i - c * h), a * i - c * g, -(a * h - b * g),
           b * f - c * e, -(a * f - c * d), a * e - b * d]
    return [x / det for x in cof], det


# ------------------------------------------------------------------ Umwandlung
def srgb(c):
    c = min(1.0, max(0.0, float(c)))
    return round(c ** (1 / 2.2), 4)


def material_info(doc, mi):
    if mi is None:
        return {"name": "Standard", "color": [0.8, 0.8, 0.8], "metal": 0.0, "rough": 0.5, "alpha": 1.0}
    m = doc["materials"][mi]
    pbr = m.get("pbrMetallicRoughness", {})
    bc = pbr.get("baseColorFactor", [1, 1, 1, 1])
    tex = [k for k in ("baseColorTexture", "metallicRoughnessTexture") if k in pbr]
    tex += [k for k in ("normalTexture", "occlusionTexture", "emissiveTexture") if k in m]
    name = m.get("name") or f"Material {mi}"
    if tex:
        warn(f"Material „{name}“: Texturen ({', '.join(tex)}) werden ignoriert, nur die Farbwerte zählen")
    alpha = float(bc[3]) if m.get("alphaMode") == "BLEND" else 1.0
    return {"name": name, "color": [srgb(x) for x in bc[:3]], "metal": round(float(pbr.get("metallicFactor", 1.0)), 3),
            "rough": round(float(pbr.get("roughnessFactor", 1.0)), 3), "alpha": round(min(1.0, max(0.0, alpha)), 3)}


def triangles(mode, idx):
    if mode == 4:
        return idx[:len(idx) - len(idx) % 3]
    out = []
    if mode == 5:  # Strip
        for k in range(len(idx) - 2):
            a, b, c = idx[k], idx[k + 1], idx[k + 2]
            out += [a, b, c] if k % 2 == 0 else [b, a, c]
    elif mode == 6:  # Fan
        for k in range(1, len(idx) - 1):
            out += [idx[0], idx[k], idx[k + 1]]
    return out


def compute_normals(pos, tri, flat):
    """-> (pos, normals, tri); flach: jedes Dreieck bekommt eigene Punkte."""
    def face(a, b, c):
        ax, ay, az = pos[a * 3:a * 3 + 3]
        ux, uy, uz = pos[b * 3] - ax, pos[b * 3 + 1] - ay, pos[b * 3 + 2] - az
        vx, vy, vz = pos[c * 3] - ax, pos[c * 3 + 1] - ay, pos[c * 3 + 2] - az
        return uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    if flat:
        np_, nn, nt = [], [], []
        for t in range(0, len(tri), 3):
            fx, fy, fz = face(*tri[t:t + 3])
            ln = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
            for v in tri[t:t + 3]:
                nt.append(len(np_) // 3)
                np_ += pos[v * 3:v * 3 + 3]
                nn += [fx / ln, fy / ln, fz / ln]
        return np_, nn, nt
    acc = [0.0] * len(pos)
    for t in range(0, len(tri), 3):
        fx, fy, fz = face(*tri[t:t + 3])  # nach Fläche gewichtet
        for v in tri[t:t + 3]:
            acc[v * 3] += fx
            acc[v * 3 + 1] += fy
            acc[v * 3 + 2] += fz
    nn = []
    for k in range(0, len(acc), 3):
        x, y, z = acc[k:k + 3]
        ln = math.sqrt(x * x + y * y + z * z)
        nn += [x / ln, y / ln, z / ln] if ln > 0 else [0.0, 1.0, 0.0]
    return pos, nn, tri


def collect(doc, buffers, z_up=False, flat=False):
    """-> {Material-Index: {"pos": [...], "nrm": [...], "idx": [...]}} in Welt-Koordinaten (Y oben)."""
    req = set(doc.get("extensionsRequired", []))
    if req & {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}:
        raise GltfError("Komprimierte Meshes (Draco/Meshopt) werden nicht unterstützt: ohne Kompression exportieren")
    for e in sorted(req):
        warn(f"Erweiterung {e} wird ignoriert")
    if doc.get("animations"):
        warn("Animationen werden ignoriert")
    if doc.get("skins"):
        warn("Skinning wird ignoriert (Ruhepose)")
    root = IDENT
    if z_up:  # -90° um X: Z oben -> Y oben
        root = [1.0, 0, 0, 0, 0, 0, -1.0, 0, 0, 1.0, 0, 0, 0, 0, 0, 1.0]
    # ohne "scenes": Wurzeln sind alle Knoten, die nirgends Kind sind (sonst fehlte Kindern die Transformation der Eltern)
    kids = {c for n in doc.get("nodes", []) for c in n.get("children", [])}
    scenes = doc.get("scenes") or [{"nodes": [i for i in range(len(doc.get("nodes", []))) if i not in kids]}]
    scene = scenes[doc.get("scene", 0)]
    groups, seen_uv = {}, False
    stack = [(n, root) for n in scene.get("nodes", [])]
    visited = set()
    while stack:
        ni, parent = stack.pop()
        if ni in visited:
            continue
        visited.add(ni)
        node = doc["nodes"][ni]
        world = mat_mul(parent, node_matrix(node))
        stack += [(c, world) for c in node.get("children", [])]
        if "mesh" not in node:
            continue
        nm, det = normal_matrix(world)
        for prim in doc["meshes"][node["mesh"]].get("primitives", []):
            mode = prim.get("mode", 4)
            if mode not in (4, 5, 6):
                warn(f"Primitive mit mode {mode} (Punkte/Linien) übersprungen")
                continue
            at = prim.get("attributes", {})
            if "POSITION" not in at:
                continue
            if prim.get("targets"):
                warn("Morph-Targets werden ignoriert")
            seen_uv = seen_uv or any(k.startswith(("TEXCOORD", "COLOR")) for k in at)
            pos, _ = read_accessor(doc, buffers, at["POSITION"])
            nv = len(pos) // 3
            idx = [int(x) for x in read_accessor(doc, buffers, prim["indices"])[0]] if "indices" in prim else list(range(nv))
            tri = triangles(mode, idx)
            tri = [x for t in range(0, len(tri), 3) for x in tri[t:t + 3]
                   if max(tri[t:t + 3]) < nv] if tri and max(tri) >= nv else tri
            if not tri:
                continue
            # in Weltkoordinaten
            wp = []
            for k in range(nv):
                x, y, z = pos[k * 3:k * 3 + 3]
                wp += [world[0] * x + world[4] * y + world[8] * z + world[12],
                       world[1] * x + world[5] * y + world[9] * z + world[13],
                       world[2] * x + world[6] * y + world[10] * z + world[14]]
            if det < 0:  # gespiegelt: Umlaufsinn umdrehen
                tri = [x for t in range(0, len(tri), 3) for x in (tri[t], tri[t + 2], tri[t + 1])]
            if "NORMAL" in at:
                nrm, _ = read_accessor(doc, buffers, at["NORMAL"])
                wn = []
                for k in range(nv):
                    x, y, z = nrm[k * 3:k * 3 + 3]
                    a, b, c = nm[0] * x + nm[1] * y + nm[2] * z, nm[3] * x + nm[4] * y + nm[5] * z, nm[6] * x + nm[7] * y + nm[8] * z
                    ln = math.sqrt(a * a + b * b + c * c) or 1.0
                    wn += [a / ln, b / ln, c / ln]
            else:
                wp, wn, tri = compute_normals(wp, tri, flat)
            g = groups.setdefault(prim.get("material"), {"pos": [], "nrm": [], "idx": []})
            base = len(g["pos"]) // 3
            g["pos"] += wp
            g["nrm"] += wn
            g["idx"] += [base + x for x in tri]
    if seen_uv:
        warn("UV-Koordinaten/Vertex-Farben werden ignoriert")
    return groups


def b64(fmt, values):
    a = array(fmt, values)
    if sys.byteorder == "big":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode("ascii")


def convert(doc, buffers, z_up=False, flat=False):
    groups = collect(doc, buffers, z_up, flat)
    if not groups:
        raise GltfError("keine Dreiecke gefunden")
    parts, lo, hi, tris = [], [math.inf] * 3, [-math.inf] * 3, 0
    for mi, g in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        nv = len(g["pos"]) // 3
        for k in range(len(g["pos"])):
            a = k % 3
            lo[a] = min(lo[a], g["pos"][k])
            hi[a] = max(hi[a], g["pos"][k])
        i32 = nv > 65535
        info = material_info(doc, mi)
        parts.append({"name": info.pop("name"), "p": b64("f", g["pos"]), "n": b64("f", g["nrm"]),
                      "i": b64("I" if i32 else "H", g["idx"]), "count": len(g["idx"]), "index32": i32, **info})
        tris += len(g["idx"]) // 3
    r = lambda v: [round(x, 6) for x in v]
    return {"version": 1, "parts": parts, "bounds": {"min": r(lo), "max": r(hi)}, "triangles": tris}


def main(argv=None):
    ap = argparse.ArgumentParser(description="glTF 2.0 (.glb/.gltf) -> Shop-Modell (site/models/<slug>.json)")
    ap.add_argument("eingabe")
    ap.add_argument("ausgabe")
    ap.add_argument("--z-up", action="store_true", help="Quelle ist Z-oben: nach Y-oben drehen")
    ap.add_argument("--flat", action="store_true", help="fehlende Normalen flach statt weich berechnen")
    a = ap.parse_args(argv)
    try:
        doc, buffers = read_gltf(a.eingabe)
        model = convert(doc, buffers, a.z_up, a.flat)
    except (GltfError, OSError, ValueError, KeyError, IndexError, struct.error) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(model, separators=(",", ":"))
    os.makedirs(os.path.dirname(os.path.abspath(a.ausgabe)), exist_ok=True)
    with open(a.ausgabe, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    size = len(text.encode())
    print(f"{a.ausgabe}: {len(model['parts'])} Teile, {model['triangles']} Dreiecke, {size / 1024:.0f} KB")
    for p in model["parts"]:
        print(f"  {p['name']:<24} {p['count'] // 3:>7} Dreiecke  Farbe {p['color']}  metal {p['metal']}  rough {p['rough']}  alpha {p['alpha']}")
    if model["triangles"] > MAX_TRIANGLES:
        print(f"WARNUNG: mehr als {MAX_TRIANGLES} Dreiecke - der Shop zeigt dann das Standard-Vial. In Blender vereinfachen (Decimate).")
    if size > MAX_BYTES:
        print("WARNUNG: größer als 8 MB - der Shop zeigt dann das Standard-Vial. Modell vereinfachen.")
    if len(model["parts"]) > MAX_PARTS:
        print(f"WARNUNG: mehr als {MAX_PARTS} Materialien - der Shop zeigt dann das Standard-Vial. Materialien zusammenfassen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
