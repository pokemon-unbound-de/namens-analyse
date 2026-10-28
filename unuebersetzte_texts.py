#!/usr/bin/env python3
"""
Übersetzungs-Report: nicht-übersetzte Texte
===========================================
Listet alle Korpus-Zeilen, deren DE-Text nach Normalisierung
identisch mit dem EN-Text ist (= nicht übersetzt) — die konkrete
"Was fehlt noch?"-Liste für Pre-Stable.

Output (privat, enthält Spieltext):
    id;kategorie;ort;en;de;raw_gleich;typ

- `raw_gleich` = `nein` markiert Zeilen, bei denen nur die
  Steuercodes/Farbcodes abweichen (Text selbst unübersetzt) —
  oft Zeichen, dass die Zeile gar nicht angefasst wurde.
- `typ` (deterministisch, nach Wortzahl im normalisierten Text):
  `satz` (>= 4 Wörter), `kurz_text` (2–3), `ein_wort` (1).
  `ein_wort`-Zeilen sind häufig Namen/Labels (offiziell
  unübersetzt) — die Mannschaft sortiert sie aus; `satz`-Zeilen
  sind die echten Lücken.

Nutzung:
    python3 unuebersetzte_texts.py --korpus texte_v0.1.7.2.csv \
        --out unuebersetzte.csv
"""

import argparse
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from namens_analyse import norm, WORD_RE  # noqa: E402

FELDER = ["id", "kategorie", "ort", "en", "de", "raw_gleich", "typ"]


def typ_von(text):
    n = len(WORD_RE.findall(text))
    if n >= 4:
        return "satz"
    if n == 1:
        return "ein_wort"
    return "kurz_text"


def main():
    p = argparse.ArgumentParser(
        description="Nicht-übersetzte Korpus-Zeilen melden (EN == DE)")
    p.add_argument("--korpus", required=True,
                   help="Korpus-CSV (;-getrennt: id;en;de;...)")
    p.add_argument("--out", default="unuebersetzte.csv")
    args = p.parse_args()

    rows = []
    n_zeilen = 0
    with open(args.korpus, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            en = r.get("en") or ""
            de = r.get("de") or ""
            if not en.strip() or not de.strip():
                continue
            n_zeilen += 1
            if norm(en).casefold() != norm(de).casefold():
                continue
            rows.append({
                "id": (r.get("id") or "").strip(),
                "kategorie": (r.get("kategorie") or "").strip(),
                "ort": (r.get("ort") or "").strip(),
                "en": en,
                "de": de,
                "raw_gleich": "ja" if en == de else "nein",
                "typ": typ_von(norm(en)),
            })

    rows.sort(key=lambda r: (r["kategorie"] or "-", r["id"]))

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FELDER, delimiter=";",
                           quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)

    c_typ = Counter(r["typ"] for r in rows)
    c_kat = Counter(r["kategorie"] or "-" for r in rows)
    c_raw = Counter(r["raw_gleich"] for r in rows)
    print(f"→ {args.out} ({len(rows)} nicht-übersetzte von {n_zeilen} "
          f"Zeilen)", file=sys.stderr)
    print(f"  nach typ: {dict(c_typ)}", file=sys.stderr)
    print(f"  raw_gleich: {dict(c_raw)} "
          f"(nein = nur Codes abweichen, Text unangetastet)",
          file=sys.stderr)
    print("  Top-Kategorien:",
          ", ".join(f"{k}={v}" for k, v in c_kat.most_common(8)),
          file=sys.stderr)
    print("(Output enthält Spieltext — privat halten)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
