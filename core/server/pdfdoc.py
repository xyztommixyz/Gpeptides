"""Kleiner PDF-Erzeuger ohne Zusatzpakete (für Rechnungen, Stornorechnungen und Gutschriften).

Nutzt die Standardschriften Helvetica / Helvetica-Bold, die jeder PDF-Betrachter mitbringt (WinAnsi-Zeichensatz:
deutsche Umlaute, ß, €, ×, – funktionieren). Zeichen außerhalb davon (z. B. polnisches Ł) werden sinnvoll ersetzt.
"""
import unicodedata
import zlib

BRAND = "Shop"  # Shop-Name im PDF-Kopf; app.py setzt ihn aus site/site.json

# Zeichenbreiten (1/1000 em) für ASCII 32..126 aus den Adobe-AFM-Dateien
_W = {
    "F1": [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
           556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667,
           778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222,
           222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
    "F2": [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
           556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667,
           778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278,
           278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
}
_SPECIAL_W = {"€": 556, "×": 584, "–": 556, "—": 1000, "·": 278, "•": 350, "ß": 611, "„": 333, "“": 333, "”": 333, "‚": 222,
              "‘": 222, "’": 222, "°": 400, "§": 556, "%": 889}
_REPL = {"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "≥": ">=", "≤": "<=", "→": "->", "✦": "*", " ": " ", " ": " ", " ": " "}


def clean(s):
    """Text auf den WinAnsi-Zeichensatz bringen."""
    out = []
    for ch in str(s):
        ch = _REPL.get(ch, ch)
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", ch).encode("cp1252", "ignore").decode("cp1252")
            out.append(base or "?")
    return "".join(out)


def width(s, font="F1", size=10):
    w = 0
    for ch in clean(s):
        o = ord(ch)
        if 32 <= o <= 126:
            w += _W[font][o - 32]
        elif ch in _SPECIAL_W:
            w += _SPECIAL_W[ch]
        else:
            base = unicodedata.normalize("NFKD", ch)[:1]
            w += _W[font][ord(base) - 32] if base and 32 <= ord(base) <= 126 else 556
    return w * size / 1000


def wrap(s, max_w, font="F1", size=10):
    words, lines, cur = clean(s).split(" "), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if width(test, font, size) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


def _esc(s):
    return clean(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


class Page:
    """Eine DIN-A4-Seite, Koordinaten in Punkt, Ursprung oben links (y wächst nach unten)."""
    W, H = 595.28, 841.89

    def __init__(self):
        self.ops = []

    def text(self, x, y, s, size=10, font="F1", color=(0.04, 0.06, 0.18), align="left"):
        if align == "right":
            x -= width(s, font, size)
        elif align == "center":
            x -= width(s, font, size) / 2
        r, g, b = color
        self.ops.append(b"BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td (" % (r, g, b, font.encode(), size, x, self.H - y)
                        + _esc(s) + b") Tj ET")

    def rect(self, x, y, w, h, fill=(0.96, 0.97, 0.99)):
        r, g, b = fill
        self.ops.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (r, g, b, x, self.H - y - h, w, h))

    def line(self, x1, y1, x2, y2, w=0.6, color=(0.85, 0.87, 0.93)):
        r, g, b = color
        self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (r, g, b, w, x1, self.H - y1, x2, self.H - y2))


def build(pages, title="Dokument"):
    """Seiten zu einer PDF-Datei (bytes) zusammensetzen."""
    objs = []

    def add(b):
        objs.append(b)
        return len(objs)

    cat = add(None)
    pages_id = add(None)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for pg in pages:
        data = zlib.compress(b"\n".join(pg.ops))
        cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                        % (pages_id, Page.W, Page.H, f1, f2, cid)))
    objs[cat - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    info = add(b"<< /Title (" + _esc(title) + b") /Producer (" + _esc(BRAND + " Shop") + b") >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, info, xref)
    return bytes(out)


# ------------------------------------------------------------------ Belege
INK, MUTED, BLUE = (0.04, 0.06, 0.18), (0.42, 0.44, 0.58), (0.16, 0.25, 0.91)


def money(c, lang="de"):
    v = f"{abs(c) / 100:,.2f}"
    if lang != "en":
        v = v.replace(",", "X").replace(".", ",").replace("X", ".")
    sg = "-" if c < 0 else ""
    return (sg + "€" + v) if lang == "en" else (sg + v + " €")


def document(kind, seller, buyer_lines, meta, rows, totals, notes, footer, lang="de", heads=None):
    """Allgemeiner Beleg: Kopf, Adressen, Kenndaten, Positionstabelle, Summen, Hinweise, Fußzeile.

    rows: Liste von (Menge, Bezeichnung, Zusatz, Einzelpreis-Text, Gesamt-Text)
    totals: Liste von (Text, Betrag-Text, fett)
    """
    pages = [Page()]
    p = pages[0]
    L, R = 56, Page.W - 56

    def head(pg):
        pg.rect(0, 0, Page.W, 6, fill=BLUE)
        pg.text(L, 52, BRAND, 22, "F2", INK)
        y = 40
        for ln in seller[:5]:
            pg.text(R, y, ln, 8, "F1", MUTED, "right")
            y += 11

    def foot(pg, n, total):
        pg.line(L, Page.H - 70, R, Page.H - 70)
        y = Page.H - 56
        for ln in footer[:3]:
            pg.text(L, y, ln, 7.2, "F1", MUTED)
            y += 10
        pg.text(R, Page.H - 56, f"{'Seite' if lang != 'en' else 'Page'} {n}/{total}", 7.2, "F1", MUTED, "right")

    head(p)
    # Absenderzeile + Empfänger
    p.text(L, 128, seller[0] + (" · " + seller[1] if len(seller) > 1 else ""), 7, "F1", MUTED)
    y = 146
    for ln in buyer_lines:
        p.text(L, y, ln, 10.5, "F1", INK)
        y += 14
    # Kenndaten rechts
    my = 146
    for k, v in meta:
        p.text(360, my, k, 8.5, "F1", MUTED)
        p.text(R, my, v, 8.5, "F2", INK, "right")
        my += 13
    # Titel
    y = max(y, my) + 26
    p.text(L, y, kind, 20, "F2", INK)
    y += 22
    # Tabelle
    cols = (L, L + 34, 360, 440, R)

    def thead(pg, y):
        pg.rect(L - 6, y - 12, R - L + 12, 20, fill=(0.95, 0.96, 0.99))
        lab = heads or (("Menge", "Bezeichnung", "Einzelpreis", "", "Gesamt") if lang != "en" else ("Qty", "Description", "Unit price", "", "Total"))
        pg.text(cols[0], y, lab[0], 8, "F2", MUTED)
        pg.text(cols[1], y, lab[1], 8, "F2", MUTED)
        pg.text(cols[3] + 30, y, lab[2], 8, "F2", MUTED, "right")
        pg.text(cols[4], y, lab[4], 8, "F2", MUTED, "right")
        return y + 22

    y = thead(p, y)
    for qty, name, extra, unit, tot in rows:
        lines = wrap(name, 330 - 34, "F2", 9.5)
        xl = wrap(extra, 330 - 34, "F1", 8.5) if extra else []
        need = 13 * len(lines) + 11 * len(xl) + 10
        if y + need > Page.H - 130:
            pages.append(Page())
            p = pages[-1]
            head(p)
            y = thead(p, 110)
        p.text(cols[0], y, str(qty) + "×", 9.5, "F1", INK)
        p.text(cols[3] + 30, y, unit, 9.5, "F1", INK, "right")
        p.text(cols[4], y, tot, 9.5, "F2", INK, "right")
        for i, ln in enumerate(lines):
            p.text(cols[1], y + i * 13, ln, 9.5, "F2", INK)
        yy = y + 13 * len(lines)
        for ln in xl:
            p.text(cols[1], yy - 2, ln, 8.5, "F1", MUTED)
            yy += 11
        p.line(L, yy - 4, R, yy - 4, 0.4)
        y = yy + 12
    # Summen
    if y + 22 * len(totals) + 60 > Page.H - 130:
        pages.append(Page())
        p = pages[-1]
        head(p)
        y = 110
    y += 8
    for label, val, bold in totals:
        if bold == "small":
            p.text(330, y, label, 8, "F1", MUTED)
            p.text(R, y, val, 8, "F1", MUTED, "right")
            y += 11
            continue
        if bold:
            y += 4
            p.line(330, y - 11, R, y - 11, 0.8, INK)
        p.text(330, y, label, 10 if bold else 9, "F2" if bold else "F1", INK if bold else MUTED)
        p.text(R, y, val, 10 if bold else 9, "F2" if bold else "F1", INK, "right")
        y += 17 if bold else 14
    y += 14
    for n in notes:
        for ln in wrap(n, R - L, "F1", 8.8):
            if y > Page.H - 90:
                pages.append(Page())
                p = pages[-1]
                head(p)
                y = 110
            p.text(L, y, ln, 8.8, "F1", INK)
            y += 12
        y += 5
    for i, pg in enumerate(pages, 1):
        foot(pg, i, len(pages))
    return build(pages, kind)
