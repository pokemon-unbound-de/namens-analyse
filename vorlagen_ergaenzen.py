#!/usr/bin/env python3
"""
Vorlagen-Ergänzung (6er-Aufgabe 5 und 6, Stand nach #39-Korrekturrunde)
=======================================================================
Vollendet die von der Werkstatt bereitgestellten Vorlagen (commit
`4c40b4f` in werkstatt-konsistenz-daten) — deterministisch, offline,
ohne LLM. Der Code ist public-safe (enthält keine Spieltexte; die
Eingabe-Dateien stammen aus dem privaten Repo):

1. item_kurzformen.csv  (Aufgabe 5)
   - leere `de_voll`-Zellen werden ergänzt (offizielle deutsche
     Vollformen der Dex-Kategorien; kuratiert aus den
     Abkürzungs-Präfixen in `de_jetzt`, die die Rekonstruktion
     bestätigen, z. B. "Klingenkr." = 9 Zeichen von "Klingenkrieger"),
   - Spalte `de_kurz_vorschlag`: Passform-Prüfung gegen `max_bytes` in
     **GBA-PCS-Bytes** — 1 Byte pro Zeichen (256er-Zeichensatz;
     Umlaute ä ö ü ß und Ä Ö Ü = 1 Byte wie lateinische Zeichen).
     **Nicht UTF-8** (Issue #39 Korrekturrunde: "Glühwürmch." =
     11 PCS-Bytes <= max 11, passt; im UTF-8-Maßstab wäre es
     13 Byte gewesen und hätte zu einem zu kurzen Vorschlag geführt).
     Passte `de_jetzt` bereits, bleibt es unverändert (die
     Werkstatt-Kurzform ist sonst verbindlich); sonst: längster
     Präfix der Vollform auf Charaktergrenze + Schlusspunkt,
     <= max_bytes.
   - neue Spalte `pixel_breite` (informativer Hinweis — getrennter
     Test, #39): Breite in Pixeln im FireRed-Normalfont (summierte
     Glyph-Vorschübe, Standard 6 px/Zeichen, "." = 5 px). Dient als
     Input für den separaten Pixelweiten-Check; kein Pass/Fail, da die
     Bildschirm-Limits je Screen/Buffer unterschiedlich sind
     (Referenz: 0xFD-Textpuffer = 54 px).

2. dex_offen.csv  (Aufgabe 6)
   - Spalten `edition` und `quelle` bleiben **bewusst leer**
     (#39-Korrekturrunde): "Gen 1" aus der Dex-Nummer ist eine
     Generationsspanne, keine Edition, und ein Artenname im
     Kategorie-Text belegt keinen Pokédex-Wortlaut. Beide Spalten
     werden erst nach exaktem Satz-Abgleich gegen den Pokédex-Text
     befüllt — davor offen gelassen. Die Generationsspannen-Annahme
     (nationale Dex-Nummern: 1–151 Gen 1, 152–251 Gen 2,
     252–386 Gen 3, 387–493 Gen 4, 494–649 Gen 5, 650–721 Gen 6,
     722–809 Gen 7) ist nicht verifiziert und auf Anfrage verfügbar.
   - alle 807 Zeilen bleiben erhalten, sortiert nach `haeufigkeit`
     absteigend (Tie-Break: `nr` aufsteigend).

3. GBA-PCS-Metriken (portiert, MIT)
   Glyph-Breiten-Tabelle und Zeichentabelle portiert aus
   Simopich/unbound-translator (`lib/gen3_font.py`, `lib/pcs_text.py`;
   MIT-Lizenz, https://github.com/Simopich/unbound-translator,
   Stand main @ 2026-10-28). Die Breiten sind
   `sFontNormalLatinGlyphWidths` aus pret/pokefirered `src/text.c`
   (Index = PCS-Byte). Der Port wurde gegen die Quelldateien
   byte-identisch verifiziert (Breiten-Tabelle + Zeichentabelle +
   Pixelbreiten-Crosscheck).

Nutzung:
    python3 vorlagen_ergaenzen.py \\
        --basis-item  item_kurzformen.csv   # Stand 4c40b4f (unverändert)
        --basis-dex   dex_offen.csv         # Stand 4c40b4f (unverändert)
        --out-item    item_kurzformen.final.csv
        --out-dex     dex_offen.final.csv
"""

import argparse
import csv
import sys

# Offizielle deutsche Vollformen der Dex-Kategorien (kuratiert aus den
# Abkürzungs-Präfixen in `de_jetzt`). "Hummelflieger" ist ein Vorschlag:
# das Präfix "Hummelfl." erlaubt auch "Hummelflug"; nach dem
# Kategorie-Pattern (Wesen-Nomen) ist "Hummelflieger" die Wahl.
KATEGORIE_VOLL = {
    "Firefly": "Glühwürmchen",
    "Shield": "Schutzschild",
    "Grass Snake": "Grasschlange",
    "Sword": "Klingenkrieger",
    "Bee Fly": "Hummelflieger",
    "Synthetic": "Modifikation",
    "Scaly": "Schuppentier",
    "Land Spirit": "Schutzpatron",
}

# ---------------------------------------------------------------------------
# GBA-PCS-Metriken (portiert aus Simopich/unbound-translator, MIT —
# siehe Modul-Doku)
# ---------------------------------------------------------------------------
# sFontNormalLatinGlyphWidths: Glyph-Vorschub in Pixeln (inkl. Spacing),
# Index = PCS-Byte, FireRed-Normal-Latin-Font.
NORMAL_GLYPH_WIDTHS = (
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    8, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 8, 6, 6, 6, 6, 6, 6, 9, 8, 8, 6,
    6, 6, 6, 6, 10, 8, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 8, 8, 8, 8, 8, 8, 4, 6, 8, 5, 5, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 12, 12, 12, 12, 6, 6, 6,
    6, 6, 6, 6, 8, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    8, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 6, 5,
    6, 6, 6, 3, 3, 6, 6, 8, 5, 9, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 6, 6, 4, 6, 5,
    5, 6, 5, 6, 6, 6, 5, 5, 5, 6, 6, 6, 6, 6, 6, 8,
    5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
)

# Referenzbreite des 0xFD-Textpuffers in Pixeln (nur Dokumentations-
# Referenz; die Vorlagen prüfen damit bewusst NICHT).
RUNTIME_BUFFER_WIDTH = 54

# PCS-Byte -> Zeichen: Bereiche aus lib/pcs_text.py (Identical-Port).
_PCS_CHAR_RANGES = [
    (0x00, " ÀÁÂÇÈÉÊËÌ"),
    (0x0B, "ÎÏÒÓÔ"),
    (0x10, "ŒÙÚÛÑßàá"),
    (0x19, "çèéêëì"),
    (0x20, "îïòóôœùúûñºª"),
    (0x5A, "Í%()"),
    (0xA1, "0123456789"),
    (0xAB, "!?.-‧"),
    (0xB7, "$,*/"),
    (0xBB, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (0xD5, "abcdefghijklmnopqrstuvwxyz"),
    (0xF0, ":ÄÖÜäöü"),
]

# Einzelzeichen-Overrides aus lib/pcs_text.py (die Mehrzeichen-Steuer-
# Makros wie "\\n"/"\\qo"/"\\pk" sind Platzhalter, keine Klartext-
# Zeichen, und für Breiten-Berechnungen von Klartext irrelevant).
_PCS_CHAR_OVERRIDES = {
    0x2D: "&", 0x35: "=", 0x36: ";", 0x51: "¿", 0x52: "¡",
    0x68: "â", 0x6F: "í", 0xB3: "\u2018", 0xB4: "\u2019",
}

_PCS_TO_CHAR = {}
for _start, _chars in _PCS_CHAR_RANGES:
    for _i, _ch in enumerate(_chars):
        _PCS_TO_CHAR[_start + _i] = _ch
_PCS_TO_CHAR.update(_PCS_CHAR_OVERRIDES)

# Zeichen -> PCS-Byte. Der gerade Apostroph belegt 0xB4 (wie im
# Source-Codec); Steuer-Bytes (0xFA/0xFB/0xFE/0xFC/0xFD/0xFF) sind kein
# Teil des Klartext-Zeichensatzes.
CHAR_TO_PCS = {ch: b for b, ch in _PCS_TO_CHAR.items()}
CHAR_TO_PCS["'"] = 0xB4


def pcs_len(s: str) -> int:
    """Länge in GBA-PCS-Bytes: 1 Byte pro Zeichen (256er-Zeichensatz).

    Umlaute (ä ö ü ß Ä Ö Ü) sind 1 Byte wie lateinische Zeichen —
    im Gegensatz zu UTF-8, wo sie 2 Byte kosten (Issue #39: die
    max_bytes-Limits der Vorlagen sind PCS-Bytes, nicht UTF-8).
    """
    for ch in s:
        if ch not in CHAR_TO_PCS:
            raise ValueError(f"Zeichen {ch!r} nicht im PCS-Zeichensatz: {s!r}")
    return len(s)


def pixel_breite(s: str) -> int:
    """Breite in Pixeln im FireRed-Normalfont (summierte Glyph-Breiten).

    Informativer Wert für den getrennten Pixelweiten-Check (#39:
    Pixelbreite von der Byte-Breite getrennt testen). Kein Pass/Fail:
    die Bildschirm-Limits je Screen/Buffer unterscheiden sich
    (Referenz: 0xFD-Textpuffer = 54 px).
    """
    total = 0
    for ch in s:
        b = CHAR_TO_PCS.get(ch)
        if b is None:
            raise ValueError(f"Zeichen {ch!r} nicht im PCS-Zeichensatz: {s!r}")
        total += NORMAL_GLYPH_WIDTHS[b]
    return total


def kurzform_fuer(base_jetzt, voll, max_bytes):
    """Kurzform-Vorschlag, der in `max_bytes` PCS-Bytes passt.

    Passt `base_jetzt` bereits (1 PCS-Byte pro Zeichen), bleibt es
    unverändert (die Werkstatt-Kurzform ist sonst verbindlich).
    Sonst: längster Präfix der Vollform auf Charaktergrenze +
    Schlusspunkt, <= max_bytes PCS-Bytes. Im Stand 4c40b4f passen
    alle 21 Kurzformen ("Glühwürmch." = 11 PCS-Bytes <= 11)."""
    if pcs_len(base_jetzt) <= max_bytes:
        return base_jetzt
    quelle = voll if voll else base_jetzt.rstrip(".")
    out = ""
    for ch in quelle:
        if pcs_len(out + ch + ".") <= max_bytes:
            out += ch
        else:
            break
    return out + "."


def item_kurzformen_erzaehlen(basis_pfad, out_pfad):
    with open(basis_pfad, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    out = []
    n_voll = 0
    n_geaendert = 0
    for r in rows:
        en = (r.get("en") or "").strip()
        de_voll = (r.get("de_voll") or "").strip()
        if not de_voll:
            de_voll = KATEGORIE_VOLL.get(en, "")
            if de_voll:
                n_voll += 1
        if not de_voll:
            print(f"WARNTUNG: leeres de_voll ohne Eintrag in "
                  f"KATEGORIE_VOLL: {r.get('id', '?')} ({en})",
                  file=sys.stderr)
        de_jetzt = (r.get("de_jetzt") or "").strip()
        try:
            max_bytes = int((r.get("max_bytes") or "13").strip())
        except ValueError:
            max_bytes = 13
        kurz = kurzform_fuer(de_jetzt, de_voll, max_bytes)
        if kurz != de_jetzt:
            n_geaendert += 1
        out.append([r.get("id", ""), r.get("typ", ""), en,
                    de_jetzt, de_voll, str(max_bytes), kurz,
                    pixel_breite(kurz)])
    with open(out_pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["id", "typ", "en", "de_jetzt", "de_voll", "max_bytes",
                    "de_kurz_vorschlag", "pixel_breite"])
        w.writerows(out)
    # Kontrolle: jeder Vorschlag muss in max_bytes (PCS-Bytes) passen
    for row in out:
        assert pcs_len(row[6]) <= int(row[5]), row
    print(f"→ {out_pfad} ({len(out)} Zeilen, {n_voll} de_voll ergänzt, "
          f"{n_geaendert} Kurzform(en) neu vorgeschlagen — alle <= "
          f"max_bytes (PCS-Bytes) geprüft; pixel_breite = FireRed-"
          f"Normalfont, informativer Wert für den getrennten "
          f"Pixelweiten-Check)", file=sys.stderr)


def dex_offen_erzaehlen(basis_pfad, out_pfad):
    """Dex-Vorlage: alle Zeilen + Spalten bleiben erhalten; `edition`
    und `quelle` sind bewusst leer (#39-Korrekturrunde — Begründung
    in der Modul-Doku). Sortierung: haeufigkeit absteigend,
    Tie-Break: nr aufsteigend."""
    with open(basis_pfad, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    out = []
    for r in rows:
        try:
            hae = int((r.get("haeufigkeit") or "0").strip() or "0")
        except ValueError:
            hae = 0
        try:
            nr = int((r.get("nr") or "").strip())
        except ValueError:
            nr = 0
        # Spalten 7/8 = interne Sortierspalten (haeufigkeit, nr),
        # werden nicht in die Ausgabe geschrieben.
        out.append([r.get("nr") or "", r.get("en_kategorie") or "",
                    r.get("en_text") or "", r.get("de_jetzt") or "",
                    r.get("haeufigkeit") or "",
                    "", "", -hae, nr])
    out.sort(key=lambda x: (x[7], x[8]))
    with open(out_pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["nr", "en_kategorie", "en_text", "de_jetzt",
                    "haeufigkeit", "edition", "quelle"])
        for row in out:
            w.writerow(row[:7])
    top = [row[4] for row in out[:10]]
    print(f"→ {out_pfad} ({len(out)} Zeilen; edition + quelle bewusst "
          f"leer, #39-Korrekturrunde; Top-10 haeufigkeit: {top})",
          file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description="Werkstatt-Vorlagen ergänzen (6er-Aufgabe 5+6, "
                    "#39-Korrekturrunde)")
    p.add_argument("--basis-item", required=True,
                   help="item_kurzformen.csv Stand 4c40b4f (unverändert)")
    p.add_argument("--basis-dex", required=True,
                   help="dex_offen.csv Stand 4c40b4f (unverändert)")
    p.add_argument("--out-item", required=True)
    p.add_argument("--out-dex", required=True)
    args = p.parse_args()

    item_kurzformen_erzaehlen(args.basis_item, args.out_item)
    dex_offen_erzaehlen(args.basis_dex, args.out_dex)
    print("(nur Namen/Nummern/Metriken im Code — keine Spieltexte; "
          "Font-Daten: MIT, s. Modul-Doku)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
