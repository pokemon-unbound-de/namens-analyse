#!/usr/bin/env python3
"""
Vorlagen-Ersteller
==================
Erstellt die beiden Vorlagen-CSVs für die 6er-Aufgabe (Aufgabe 5 und 6),
aus den offiziellen Namensdaten — OHNE Spieltexte (public-safe):

1. item_kurzformen.csv  (Aufgabe 5)
   Alle Items aus der Kanon-Namensliste mit Vollform und einem
   deterministischen Kurzform-Vorschlag (<= 13 Byte UTF-8; Umlaute
   zaehlen 2 Byte).

2. dex_offen.csv  (Aufgabe 6)
   Die 100 haeufigsten Pokemon nach Namens-Vorkommen im Korpus
   (DE- und EN-Form, ganzes Wort, case-insensitive), mit DE/EN-Namen,
   Vorkommen und Kanon-Quelle. Die Spalte `edition` bleibt bewusst
   leer: aus den verfuegbaren Daten (Korpus, Kanon, Glossar) sind
   keine Dex-Nummern ableitbar — von der Mannschaft einfuellen.

Nutzung:
    python3 vorlagen_erstellen.py \
        --kanon    kanon_namen.csv \
        --korpus   texte_v0.1.7.2.csv \
        --out-dir  ./vorlagen
"""

import argparse
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from namens_analyse import norm  # noqa: E402

MAX_KURZFORM_BYTES = 13
TOP_DEX = 100


def load_kanon_rows(path):
    """Alle Kanon-Zeilen als list[dict] (typ, en, de, quelle)."""
    rows = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            t = (r.get("typ") or "").strip()
            en = (r.get("en") or "").strip()
            de = (r.get("de") or "").strip()
            q = (r.get("quelle") or "").strip()
            if not (t and en and de):
                continue
            rows.append({"typ": t, "en": en, "de": de, "quelle": q})
    return rows


def load_corpus_text(path):
    """Gesamtext des Korpus (DE + EN, normalisiert) zum Zaehlen."""
    parts = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            en = r.get("en") or ""
            de = r.get("de") or ""
            if en.strip() or de.strip():
                parts.append(norm(en) + " " + norm(de))
    return "\n".join(parts)


def byte_len(s):
    return len(s.encode("utf-8"))


def kurzform_vorschlag(name):
    """Deterministischer Kurzform-Vorschlag (<= 13 Byte UTF-8).

    Regeln (deterministisch — es ist ein Vorschlag, die Mannschaft
    kann jede Zeile anpassen):
    1. Passt die Vollform in <= 13 Byte: unveraendert.
    2. Sonst: Bindestrich-Segmente zusammennehmen, solange <= 13 Byte
       (und >= 4 Byte) — "A-Raichunium Z" -> "A-Raichunium",
       "Ash-Pikachium Z" -> "Ash-Pikachium", "Band-Autogramm" -> "Band".
    3. Sonst: laengster Praefix auf Charaktergrenze mit <= 13 Byte.
    """
    if byte_len(name) <= MAX_KURZFORM_BYTES:
        return name, "passt"
    if "-" in name:
        segs = name.split("-")
        acc = segs[0]
        for seg in segs[1:]:
            cand = acc + "-" + seg
            if byte_len(cand) <= MAX_KURZFORM_BYTES:
                acc = cand
            else:
                break
        if 4 <= byte_len(acc) <= MAX_KURZFORM_BYTES:
            return acc, "gekürzt"
    out = ""
    for ch in name:
        if byte_len(out + ch) <= MAX_KURZFORM_BYTES:
            out += ch
        else:
            break
    return out.strip(), "gekürzt"


def make_item_kurzformen(kanon_rows, out_path):
    items = [r for r in kanon_rows if r["typ"] == "item"]
    rows_out = []
    n_kuerzt = 0
    for r in sorted(items, key=lambda x: x["de"].casefold()):
        kurz, status = kurzform_vorschlag(r["de"])
        if status == "gekürzt":
            n_kuerzt += 1
        rows_out.append([r["de"], byte_len(r["de"]), kurz,
                         byte_len(kurz), status, r["quelle"]])
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["name_voll", "byte_voll", "name_kurz", "byte_kurz",
                    "status", "quelle"])
        w.writerows(rows_out)
    print(f"→ {out_path} ({len(rows_out)} Items, {n_kuerzt} "
          "gekürzt-Vorschläge)", file=sys.stderr)


def count_name(name, text, text_cf):
    """Vorkommen eines Namens im Gesamtext (Wortgrenzen, case-insensitive)."""
    name_cf = name.casefold()
    if not name_cf:
        return 0
    if name_cf in text_cf:
        rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) +
                        r"(?![A-Za-z0-9])", re.IGNORECASE)
        return len(rx.findall(text))
    return 0


def make_dex_offen(kanon_rows, corpus_text, out_path, top=TOP_DEX):
    pok = [r for r in kanon_rows if r["typ"] == "pokémon"]
    text_cf = corpus_text.casefold()
    entries = []
    for r in pok:
        c = count_name(r["de"], corpus_text, text_cf)
        c += count_name(r["en"], corpus_text, text_cf)
        if c > 0:
            entries.append((c, r))
    # haeufigste zuerst; deterministischer Tie-Break: DE-Name
    entries.sort(key=lambda x: (-x[0], x[1]["de"].casefold()))
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["name_de", "name_en", "vorkommen", "edition",
                    "quelle"])
        for c, r in entries[:top]:
            w.writerow([r["de"], r["en"], c, "", r["quelle"]])
    print(f"→ {out_path} ({len(entries[:top])} von {len(entries)} "
          "Kanon-Pokémon mit Vorkommen; `edition` bewusst leer)",
          file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description="Vorlagen-CSVs (Items + Pokédex) erstellen")
    p.add_argument("--kanon", required=True,
                   help="Kanon-Namensliste-CSV (typ;en;de;quelle)")
    p.add_argument("--korpus", required=True,
                   help="Korpus-CSV (;-getrennt: id;en;de;...)")
    p.add_argument("--out-dir", default="vorlagen")
    p.add_argument("--top-dex", type=int, default=TOP_DEX,
                   help="Anzahl Eintraege in dex_offen.csv (Default 100)")
    args = p.parse_args()

    kanon_rows = load_kanon_rows(args.kanon)
    print(f"→ {len(kanon_rows)} Kanon-Zeilen geladen", file=sys.stderr)
    corpus_text = load_corpus_text(args.korpus)
    print(f"→ Korpus-Gesamtext: {len(corpus_text)} Zeichen",
          file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    make_item_kurzformen(
        kanon_rows, os.path.join(args.out_dir, "item_kurzformen.csv"))
    make_dex_offen(
        kanon_rows, corpus_text,
        os.path.join(args.out_dir, "dex_offen.csv"), args.top_dex)
    print("(Outputs enthalten nur offizielle Namen — keine Spieltexte)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
