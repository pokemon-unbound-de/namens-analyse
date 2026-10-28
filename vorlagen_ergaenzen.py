#!/usr/bin/env python3
"""
Vorlagen-Ergänzung (6er-Aufgabe 5 und 6)
========================================
Vollendet die von der Werkstatt bereitgestellten Vorlagen (commit
`4c40b4f` in werkstatt-konsistenz-daten) — deterministisch, offline,
ohne LLM. Der Code ist public-safe (enthält keine Spieltexte; die
Eingabe-Dateien stammen aus dem privaten Repo):

1. item_kurzformen.csv  (Aufgabe 5)
   - leere `de_voll`-Zellen werden ergänzt (offizielle deutsche
     Vollformen der Dex-Kategorien; kuratiert aus den
     Abkürzungs-Präfixen in `de_jetzt`, die die Rekonstruktion
     bestätigen, z. B. "Klingenkr." = 9 Zeichen von "Klingenkrieger"),
   - neue Spalte `de_kurz_vorschlag`: passte `de_jetzt` bereits in
     `max_bytes` (UTF-8-Byte, Umlaute = 2), bleibt es unverändert;
     sonst längster Präfix der Vollform auf Charaktergrenze + Punkt.
     Einziger Fall im Stand 4c40b4f: "Glühwürmch." (13 Byte > max 11)
     -> "Glühwürm." (11 Byte).

2. dex_offen.csv  (Aufgabe 6)
   - neue Spalte `edition`: Generation aus der Dex-Nummer `nr`
     (nationale Nummerierung: 1-151 Gen 1, 152-251 Gen 2,
     252-386 Gen 3, 387-493 Gen 4, 494-649 Gen 5, 650-721 Gen 6,
     722-809 Gen 7; außerhalb -> leer),
   - neue Spalte `quelle`: Kanon-Quelle des Pokémon, wenn der
     offizielle Name (DE- oder EN-Form) großgeschrieben mit
     Wortgrenzen in `de_jetzt`/`en_text` steht (längster Treffer
     gewinnt); sonst leer,
   - alle 807 Zeilen bleiben erhalten, sortiert nach `haeufigkeit`
     absteigend (die 100 häufigsten stehen oben; Tie-Break: `nr`
     aufsteigend).

Nutzung:
    python3 vorlagen_ergaenzen.py \\
        --basis-item  item_kurzformen.csv   # Stand 4c40b4f (unverändert)
        --basis-dex   dex_offen.csv         # Stand 4c40b4f (unverändert)
        --kanon       kanon_namen.csv
        --out-item    item_kurzformen.final.csv
        --out-dex     dex_offen.final.csv
"""

import argparse
import csv
import os
import re
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

GEN_RENGEN = (
    (1, 151, "Gen 1"),
    (152, 251, "Gen 2"),
    (252, 386, "Gen 3"),
    (387, 493, "Gen 4"),
    (494, 649, "Gen 5"),
    (650, 721, "Gen 6"),
    (722, 809, "Gen 7"),
)


def byte_len(s):
    return len(s.encode("utf-8"))


def edition_von_nr(nr):
    for lo, hi, label in GEN_RENGEN:
        if lo <= nr <= hi:
            return label
    return ""


def kurzform_fuer(base_jetzt, voll, max_bytes):
    """Kurzform-Vorschlag, der in `max_bytes` UTF-8-Byte passt.

    Passt `base_jetzt` bereits: unverändert beibehalten (die Werkstatt-
    Kurzform ist sonst verbindlich). Sonst: längster Präfix der
    Vollform auf Charaktergrenze + Schlusspunkt, <= max_bytes
    ("Glühwürmch." -> aus "Glühwürmchen" -> "Glühwürm.")."""
    if byte_len(base_jetzt) <= max_bytes:
        return base_jetzt
    quelle = voll if voll else base_jetzt.rstrip(".")
    out = ""
    for ch in quelle:
        if byte_len(out + ch + ".") <= max_bytes:
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
        else:
            # Basis-Zeile mit bereits gefüllter Vollform prüfen:
            # passt die kurze Basis-Form (de_jetzt) zur Vollform?
            pass
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
                    de_jetzt, de_voll, str(max_bytes), kurz])
    with open(out_pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["id", "typ", "en", "de_jetzt", "de_voll", "max_bytes",
                    "de_kurz_vorschlag"])
        w.writerows(out)
    # Kontrolle: jeder Vorschlag muss in max_bytes passen
    for row in out:
        assert byte_len(row[6]) <= int(row[5]), row
    print(f"→ {out_pfad} ({len(out)} Zeilen, {n_voll} de_voll ergänzt, "
          f"{n_geaendert} Kurzform(en) neu vorgeschlagen — "
          f"alle <= max_bytes geprüft)", file=sys.stderr)


def load_kanon_pokemon(path):
    """[(name_de, name_en, quelle)] aus der Kanon-Namensliste."""
    names = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            if (r.get("typ") or "").strip() != "pokémon":
                continue
            de = (r.get("de") or "").strip()
            en = (r.get("en") or "").strip()
            q = (r.get("quelle") or "").strip()
            if de or en:
                names.append((de, en, q))
    return names


def quelle_fuer(text, text_cf, kanon_names):
    """Kanon-Quelle des Pokémon, dessen offizieller Name (DE oder EN)
    großgeschrieben mit Wortgrenzen in `text` steht; längster Treffer
    gewinnt. Kein Treffer -> leer string.

    Sucht case-insensitiv, akzeptiert aber nur Treffer, die im Text
    mit einem Großbuchstaben beginnen (der Name am Satzanfang/als
    Eigenname — nicht z. B. "spark" in "Sparkling")."""
    best_len = 0
    best_q = ""
    for de, en, q, rx_de, rx_en in kanon_names:
        for name, name_cf, rx in ((de, de.casefold(), rx_de),
                                  (en, en.casefold(), rx_en)):
            if not name or rx is None or name_cf not in text_cf:
                continue
            for m in rx.finditer(text):
                if m.group(0)[0].isupper() and len(name) > best_len:
                    best_len = len(name)
                    best_q = q
    return best_q


def dex_offen_erzaehlen(basis_pfad, kanon_pfad, out_pfad):
    with open(basis_pfad, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))

    # Kanon-Namen einmal kompilieren (Wortgrenzen, case-insensitiv)
    kanon_names = []
    for de, en, q in load_kanon_pokemon(kanon_pfad):
        rx = []
        for name in (de, en):
            if name:
                rx.append(re.compile(
                    r"(?<![A-Za-z0-9])" + re.escape(name)
                    + r"(?![A-Za-z0-9])", re.IGNORECASE))
            else:
                rx.append(None)
        kanon_names.append((de, en, q, rx[0], rx[1]))

    out = []
    n_quelle = 0
    for r in rows:
        try:
            nr = int((r.get("nr") or "").strip())
        except ValueError:
            nr = 0
        try:
            hae = int((r.get("haeufigkeit") or "0").strip() or "0")
        except ValueError:
            hae = 0
        de_jetzt = r.get("de_jetzt") or ""
        en_text = r.get("en_text") or ""
        text = de_jetzt + " " + en_text
        quelle = quelle_fuer(text, text.casefold(), kanon_names)
        if quelle:
            n_quelle += 1
        # Spalte 8 = interne Sortierspalte (haeufigkeit), wird nicht
        # in die Ausgabe geschrieben.
        out.append([r.get("nr", ""), r.get("en_kategorie", ""),
                    en_text, de_jetzt, r.get("haeufigkeit", ""),
                    edition_von_nr(nr), quelle, -hae, nr])

    # 100 häufigste zuerst (absteigend); Tie-Break: nr aufsteigend
    out.sort(key=lambda x: (x[7], x[8]))

    with open(out_pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["nr", "en_kategorie", "en_text", "de_jetzt",
                    "haeufigkeit", "edition", "quelle"])
        for row in out:
            w.writerow(row[:7])
    top = [row[4] for row in out[:10]]
    print(f"→ {out_pfad} ({len(out)} Zeilen, {n_quelle} mit quelle; "
          f"Top-10 haeufigkeit: {top})", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description="Werkstatt-Vorlagen ergänzen (6er-Aufgabe 5+6)")
    p.add_argument("--basis-item", required=True,
                   help="item_kurzformen.csv Stand 4c40b4f (unverändert)")
    p.add_argument("--basis-dex", required=True,
                   help="dex_offen.csv Stand 4c40b4f (unverändert)")
    p.add_argument("--kanon", required=True,
                   help="Kanon-Namensliste-CSV (typ;en;de;quelle)")
    p.add_argument("--out-item", required=True)
    p.add_argument("--out-dex", required=True)
    args = p.parse_args()

    item_kurzformen_erzaehlen(args.basis_item, args.out_item)
    dex_offen_erzaehlen(args.basis_dex, args.kanon, args.out_dex)
    print("(nur Namen/Nummern im Code — keine Spieltexte)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
