#!/usr/bin/env python3
"""Reproduzierbares Abkürzungs-/Limits-Inventar für ABKUERZUNGEN.md.

Quelle (öffentliches Release-Asset):
    https://github.com/pokemon-unbound-de/pokemon-unbound-de/releases/download/v0.1.7.2/ABKUERZUNGEN.md

Zweck: Pro Tabellenzeile werden Quelle (URL), Datei-Hash, Zeilennummer,
Bereich, Kurz-/Vollform, dokumentiertes Zeichenlimit und die
Zeichenanzahl (Unicode-Codepunkte) erfasst. Duplikate werden erhalten
und erklärt (Erstvorkommen = Original, spätere Vorkommen mit
Zeilenbezug). Der Abgleich gegen vorhandene Vorlagen findet nur
exakt/eindeutig statt — alles andere bleibt `offen`.

Wichtige Abgrenzungen (Projektentscheidungen 2026-10-28):
- Zeichen zählen = Unicode-Codepunkte der Kurzform. KEINE
  PCS-/Byte-/Pixel-/Screen-/ROM-Interpretation: Screen-Zuordnung,
  ROM-Adressen und Byte-Limits werden NICHT aus Zeichenlimits
  abgeleitet, sondern explizit `unbekannt` gelassen.
- Der Inhaltsversionsbezug (Dokumenttitel vs. Release-Asset) wird
  als UNGEKLÄRT dokumentiert; Limitwerte dürfen nicht pauschal aus
  einer anderen Version übernommen werden.
- Das Tool ist kein Gate: es berichtet nur. Exit-Codes:
  0 = ohne Überschreitungen/Strukturfehler;
  1 = Input-Fehler (fehlende Datei, ungültiges UTF-8 der Quelle,
      Hash-Mismatch, keine Zeilen, unlesbare Vorlagen oder
      fehlerhafter/leerer Vorlagen-Header ohne Pflichtspalten);
  2 = Befunde (Überschreitungen oder Strukturfehler > 0).

Eigenschaften: deterministisch (zweiter Lauf byte-identisch, keine
Zeitstempel aus dem System), nur Standardbibliothek, Python >= 3.8,
ohne LLM. Der Code ist public-safe: er enthält keine Spieltexte;
alle Eingabedateien werden per Pfad übergeben.

Aufruf:
    python3 limits_inventar.py \
      --quelle ABKUERZUNGEN.md \
      --quelle-url <url> \
      --asset-version v0.1.7.2 \
      --expected-sha256 <hash> \
      --vorlagen item_kurzformen.csv \
      --abruftag 2026-10-28 \
      --out-dir ergebnisse/limits-inventar/
"""

import argparse
import csv
import hashlib
import os
import re
import sys

STANDARD_QUELLE_URL = (
    "https://github.com/pokemon-unbound-de/pokemon-unbound-de"
    "/releases/download/v0.1.7.2/ABKUERZUNGEN.md"
)

# Bereiche des Dokuments, die Vorlagen-Typen entsprechen. Unbekannte
# Bereiche erhalten den Status `ohne_Vorlagenbereich` (kein Abgleich,
# kein Fehler).
VORLAGEN_BEREICHE = {"Items": "item", "Pokédex-Kategorien": "dex_kategorie"}

# Systematischer Suffix des Pokédex-Kategorien-Bereichs im Dokument:
# alle 86 Zeilen tragen die volle Form als "<Name>-Pokémon". Der
# Abgleich mit Vorlagen (`de_voll` = Basisname) ist exakt mit diesem
# einen dokumentierten Suffix, nicht fuzzy.
DEX_SUFFIX = "-Pokémon"

UNK = "unbekannt"

FELDER = [
    "quelle_url", "datei_sha256", "zeile", "bereich", "kurzform",
    "vollform", "limit_z", "zeichen", "limit_status", "duplikat",
    "duplikat_von_zeile", "duplikat_vorkommen", "vorlagen_abgleich",
    "vorlagen_ids", "vorlagen_grund", "versionsbezug",
    "screen_zuordnung", "rom_adresse", "byte_limit",
]

LIMIT_RE = re.compile(r"Limit\s+(\d+)\s+Zeichen")
VERSION_RE = re.compile(r"v\d+(?:\.\d+)*")
SEPARATOR_RE = re.compile(r":?-{1,}:?")


def parse_dokument(text):
    """Parst das Abkürzungs-Dokument.

    -> (titel, titel_version, zeilen, strukturfehler, hinweise)
    - zeilen: Liste von Dicts (zeile, bereich, kurzform, vollform,
      grund, limit_z) in Datei-Reihenfolge
    - strukturfehler: Zeilennummern strukturell gebrochener
      Tabellenzeilen (falsche Spaltenzahl, leere Pflichtzellen,
      fehlendes abschließendes Pipe)
    - hinweise: Zeilennummern + Text von `Hinweise:`-Zeilen (Kontext)
    """
    titel = ""
    titel_version = ""
    zeilen = []
    strukturfehler = []
    hinweise = []
    for nr, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not titel and line.startswith("# "):
            titel = line[2:].strip()
            m = VERSION_RE.search(titel)
            if m:
                titel_version = m.group(0)
            continue
        if line.startswith("Hinweise:"):
            hinweise.append((nr, line))
            continue
        if not line.startswith("|"):
            continue
        if not line.endswith("|"):
            strukturfehler.append(nr)
            continue
        cells = [c.strip() for c in line[1:-1].split("|")]
        if all(SEPARATOR_RE.fullmatch(c) for c in cells):
            continue  # Separator-Zeile
        if cells and cells[0] == "Bereich":
            continue  # Kopfzeile
        if len(cells) != 4 or not cells[0] or not cells[1] or not cells[2]:
            strukturfehler.append(nr)
            continue
        bereich, kurzform, vollform, grund = cells
        m = LIMIT_RE.search(grund)
        limit_z = int(m.group(1)) if m else None
        zeilen.append({
            "zeile": nr,
            "bereich": bereich,
            "kurzform": kurzform,
            "vollform": vollform,
            "grund": grund,
            "limit_z": limit_z,
        })
    return titel, titel_version, zeilen, strukturfehler, hinweise


# Pflichtspalten der Vorlagen-CSV — die Spalten, die der Abgleich
# tatsächlich nutzt. Fehlende Pflichtspalten im Header bedeuten,
# dass die Datei ungültig ist (Exit 1); sie dürfen nicht stumm als
# „keine Vorlagen“ durchgehen.
VORLAGEN_PFLICHT_SPAALTEN = ("id", "typ", "de_kurz_vorschlag", "de_voll")


def laden_vorlagen(pfad):
    """Lädt die Vorlagen-CSV (id;typ;en;de_jetzt;de_voll;max_bytes;
    de_kurz_vorschlag;pixel_breite). Nur die für den Abgleich
    relevanten Felder werden übernommen.

    Wirft ValueError, wenn der Header leer ist oder Pflichtspalten
    fehlen (ein falscher Header darf nicht stumm in eine leere
    Vorlagen-Liste münden)."""
    vorlagen = []
    with open(pfad, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        felder = reader.fieldnames
        if not felder:
            raise ValueError("leere Vorlagen-CSV (kein Header)")
        fehlt = [k for k in VORLAGEN_PFLICHT_SPAALTEN if k not in felder]
        if fehlt:
            gefunden = ", ".join(f for f in felder if f) or "(keine)"
            raise ValueError(
                "Vorlagen-CSV: fehlende Pflichtspalte(n) %s "
                "(gefunden: %s)" % (", ".join(fehlt), gefunden))
        for r in reader:
            kurz = (r.get("de_kurz_vorschlag") or "").strip()
            if not kurz:
                continue
            vorlagen.append({
                "id": (r.get("id") or "").strip(),
                "typ": (r.get("typ") or "").strip(),
                "de_kurz": kurz,
                "de_voll": (r.get("de_voll") or "").strip(),
            })
    return vorlagen


def vorlagen_abgleich(bereich, kurzform, vollform, vorlagen):
    """Exakter, eindeutiger Abgleich einer Dokumentzeile gegen die
    Vorlagen.

    Regel: Kurzform-Identität + Bereich/Typ-Kompatibilität; volle
    Form: Identität mit `de_voll` oder (im dex-Bereich) Identität
    plus dem systematischen Suffix `-Pokémon`. Genau ein distinktes
    Vollform-Paar => `exakt_eindeutig` (alle Vorkommen-IDs der
    Vorlagen); zwei oder mehrere distinkte Vollformen =>
    `offen_mehrfach`; sonst `offen_kein_Treffer` mit Grund.
    """
    if vorlagen is None:
        return "ohne_Vorlagen", "", "vorlagen_datei_nicht_vorgegeben"
    typ = VORLAGEN_BEREICHE.get(bereich)
    if typ is None:
        return "ohne_Vorlagenbereich", "", "kein_Vorlagenbereich"
    kandidaten = [v for v in vorlagen
                  if v["typ"] == typ and v["de_kurz"] == kurzform]
    exakt = [v for v in kandidaten
             if v["de_voll"] == vollform
             or (typ == "dex_kategorie"
                 and v["de_voll"] + DEX_SUFFIX == vollform)]
    if not exakt:
        grund = "kurzform_ohne_Vollform_Treffer" if kandidaten else "kein_Treffer"
        return "offen_kein_Treffer", "", grund
    volls = sorted({v["de_voll"] for v in exakt})
    ids = ",".join(v["id"] for v in exakt)
    if len(volls) > 1:
        return "offen_mehrfach", ids, "mehrere_Vollformen"
    return "exakt_eindeutig", ids, ""


def limit_status(limit_z, zeichen):
    if limit_z is None:
        return "kein_explizites_Limit"
    if zeichen > limit_z:
        return "ueberschreitung"
    if zeichen == limit_z:
        return "grenze"
    return "im_limit"


def verarbeite(zeilen, vorlagen):
    """Berechnet Duplikate + Vorlagen-Status pro Zeile (Datei-Reihenfolge).

    Duplikat-Identität: (bereich, kurzform, vollform, limit). Das
    erste Vorkommen ist Original (vorkommen 1); spätere Vorkommen
    werden erhalten und auf die Zeile des Originals verwiesen.
    """
    gruppen = {}
    out = []
    for z in zeilen:
        key = (z["bereich"], z["kurzform"], z["vollform"],
               z["limit_z"] if z["limit_z"] is not None else "")
        zeichen = len(z["kurzform"])  # Unicode-Codepunkte, keine Bytes
        if key in gruppen:
            first, count = gruppen[key]
            count += 1
            gruppen[key] = (first, count)
            dup, von, vork = "ja", first, count
        else:
            gruppen[key] = (z["zeile"], 1)
            dup, von, vork = "nein", "", 1
        status, ids, grund = vorlagen_abgleich(
            z["bereich"], z["kurzform"], z["vollform"], vorlagen)
        out.append({
            "zeile": z["zeile"],
            "bereich": z["bereich"],
            "kurzform": z["kurzform"],
            "vollform": z["vollform"],
            "limit_z": z["limit_z"] if z["limit_z"] is not None else "",
            "zeichen": zeichen,
            "limit_status": limit_status(z["limit_z"], zeichen),
            "duplikat": dup,
            "duplikat_von_zeile": von,
            "duplikat_vorkommen": vork,
            "vorlagen_abgleich": status,
            "vorlagen_ids": ids,
            "vorlagen_grund": grund,
        })
    return out


def statistik(out, strukturfehler):
    stat = {
        "total": len(out),
        "per_bereich": [],
        "unique": 0,
        "dup_vorkommen": 0,
        "dup_gruppen": [],
        "limit_status": {},
        "vorlagen_status": {},
        "strukturfehler": strukturfehler,
    }
    bereiche = {}
    for r in out:
        bereiche[r["bereich"]] = bereiche.get(r["bereich"], 0) + 1
        stat["per_bereich"].append(r["bereich"])
        stat["limit_status"][r["limit_status"]] = (
            stat["limit_status"].get(r["limit_status"], 0) + 1)
        stat["vorlagen_status"][r["vorlagen_abgleich"]] = (
            stat["vorlagen_status"].get(r["vorlagen_abgleich"], 0) + 1)
        if r["duplikat"] == "ja":
            stat["dup_vorkommen"] += 1
        else:
            stat["unique"] += 1
    stat["per_bereich"] = [(b, bereiche[b]) for b in bereiche]
    gesenkt = [r for r in out if r["duplikat"] == "ja"]
    if gesenkt:
        gruppen = {}
        for r in out:
            key = (r["bereich"], r["kurzform"], r["vollform"], r["limit_z"])
            gruppen.setdefault(key, []).append(r["zeile"])
        for key, zeilen in gruppen.items():
            if len(zeilen) > 1:
                stat["dup_gruppen"].append({
                    "bereich": key[0], "kurzform": key[1],
                    "vollform": key[2], "anzahl": len(zeilen),
                    "zeilen": ",".join(str(z) for z in zeilen),
                })
    return stat


def report_markdown(konf, titel, titel_version, out, stat, hinweise):
    L = []
    L.append("# Limits-Inventar: Abkürzungs-Dokument (Release-Asset)")
    L.append("")
    L.append("## Quelle und Integrität")
    L.append("")
    L.append("- Quelle: `%s`" % konf["quelle_url"])
    if konf["abruftag"]:
        L.append("- Abruf: %s (als Argument übergeben, reproduzierbar)"
                 % konf["abruftag"])
    L.append("- SHA-256 (Datei): `%s`" % konf["sha256"])
    if konf["expected_sha256"]:
        L.append("- Integritätscheck: erwarteter SHA-256 als Argument "
                 "übergeben — Übereinstimmung bestätigt (bei Abweichung "
                 "würde das Tool Exit 1 verlassen, bevor es schreibt).")
    L.append("- Dokumenttitel: %s" % (titel or "(kein Titel)"))
    L.append("")
    if titel_version and konf["asset_version"]:
        if titel_version != konf["asset_version"]:
            L.append("- **Inhaltsversionsbezug: UNBEKANNT/UNGELÖST** — "
                     "der Titel nennt %s, das Asset gehört zu Release "
                     "%s. Vor Gate-/Limit-Übernahme ist der "
                     "Versionsbezug zu klären; Limitwerte werden nicht "
                     "pauschal aus einer anderen Version übernommen."
                     % (titel_version, konf["asset_version"]))
        else:
            L.append("- Inhaltsversionsbezug: Titel- und "
                     "Asset-Version stimmen überein (%s)."
                     % titel_version)
    else:
        L.append("- **Inhaltsversionsbezug: UNBEKANNT** (Version in "
                 "Titel oder Asset fehlt).")
    L.append("")
    L.append("## Methode")
    L.append("")
    L.append("- Tool: `namens-analyse/limits_inventar.py` (deterministisch, "
             "nur Standardbibliothek, ohne LLM; zweiter Lauf "
             "byte-identisch)")
    L.append("- Zählung: Unicode-Codepunkte der Kurzform (reine "
             "Zeichenzählung). Keine PCS-/Byte-/Pixel-/Screen-/ROM-"
             "Interpretation.")
    L.append("- Duplikat-Identität: (Bereich, Kurzform, volle Form, "
             "Limit); Duplikate bleiben erhalten, Erstvorkommen = "
             "Original, spätere Vorkommen mit Zeilenbezug.")
    L.append("- Vorlagen-Abgleich: nur exakt/eindeutig (Kurzform-"
             "Identität + Bereich/Typ-Kompatibilität; volle Form: "
             "Identität mit `de_voll`, im dex-Bereich zusätzlich der "
             "systematische Suffix `%s`); sonst `offen` mit Grund." % DEX_SUFFIX)
    L.append("- Exit-Codes: 0 = ohne Befunde; 1 = Input-Fehler; 2 = "
             "Überschreitungen oder Strukturfehler > 0. Kein "
             "Pflichtgate.")
    L.append("")
    L.append("## Summen")
    L.append("")
    L.append("- Zeilen mit Tabelleninhalt: %d" % stat["total"])
    L.append("- unterschiedliche Zeilen: %d; zusätzliche identische "
             "Vorkommen: %d (Duplikatgruppen: %d)"
             % (stat["unique"], stat["dup_vorkommen"], len(stat["dup_gruppen"])))
    L.append("- Bereiche:")
    for bereich, n in stat["per_bereich"]:
        L.append("  - %s: %d" % (bereich, n))
    L.append("- Limit-Status: %s" % ", ".join(
        "%s=%d" % (k, stat["limit_status"][k]) for k in sorted(stat["limit_status"])))
    L.append("- Vorlagen-Status: %s" % ", ".join(
        "%s=%d" % (k, stat["vorlagen_status"][k]) for k in sorted(stat["vorlagen_status"])))
    if stat["strukturfehler"]:
        L.append("- Strukturfehler (Zeilen): %s"
                 % ", ".join(str(z) for z in stat["strukturfehler"]))
    else:
        L.append("- Strukturfehler: 0")
    L.append("")
    if stat["dup_gruppen"]:
        L.append("## Duplikatgruppen (erhalten, erklärt)")
        L.append("")
        L.append("| Bereich | Kurzform | volle Form | Vorkommen | Zeilen |")
        L.append("|---|---|---|---:|---|")
        for g in stat["dup_gruppen"]:
            L.append("| %s | %s | %s | %d | %s |"
                     % (g["bereich"], g["kurzform"], g["vollform"],
                        g["anzahl"], g["zeilen"]))
        L.append("")
    L.append("## Vorlagen-Abgleich")
    L.append("")
    exakt = [r for r in out
             if r["vorlagen_abgleich"] == "exakt_eindeutig"]
    if exakt:
        L.append("Exakte, eindeutige Treffer:")
        L.append("")
        L.append("| Zeile | Bereich | Kurzform | volle Form | Vorlagen-IDs |")
        L.append("|---:|---|---|---|---|")
        for r in exakt:
            L.append("| %d | %s | %s | %s | %s |"
                     % (r["zeile"], r["bereich"], r["kurzform"],
                        r["vollform"], r["vorlagen_ids"]))
        L.append("")
    offen = [r for r in out if r["vorlagen_abgleich"].startswith("offen")]
    if offen:
        L.append("Offene Zeilen (kein exakter/eindeutiger Vorlagen-Treffer):")
        L.append("")
        L.append("| Zeile | Bereich | Kurzform | volle Form | Grund |")
        L.append("|---:|---|---|---|---|")
        for r in offen:
            L.append("| %d | %s | %s | %s | %s |"
                     % (r["zeile"], r["bereich"], r["kurzform"],
                        r["vollform"], r["vorlagen_grund"]))
        L.append("")
    L.append("## Unbekannt / offen (explizit gelassen)")
    L.append("")
    L.append("- Screen-Zuordnung, ROM-Adressen, Byte-Limits: **%s** — "
             "werden nicht aus Zeichenlimits abgeleitet (keine "
             "PCS-/Pixel-/ROM-Belege im Dokumentformat; Pixelgrenzen "
             "nur pro Screen und passender Version belegbar)." % UNK)
    L.append("- Inhaltsversionsbezug (Titel vs. Asset): offen, siehe "
             "oben.")
    L.append("- Vorlagen-IDs sind ROM-Referenzen im Kontext der "
             "Vorlagen-CSV; sie sind kein Beleg für die Felder des "
             "dokumentierten Spiels.")
    L.append("")
    if hinweise:
        L.append("## Kontext: Hinweise-Zeile(n) des Dokuments")
        L.append("")
        for nr, text in hinweise:
            L.append("- Zeile %d: %s" % (nr, text))
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Abkürzungs-/Limits-Inventar (deterministisch, "
                    "ohne LLM; kein Pflichtgate)")
    p.add_argument("--quelle", required=True,
                   help="lokale Kopie des Abkürzungs-Dokuments (.md)")
    p.add_argument("--quelle-url", default=STANDARD_QUELLE_URL,
                   help="URL der Quelle (Metadaten, pro Zeile)")
    p.add_argument("--asset-version", default=None,
                   help="Release-Version des Assets (z. B. v0.1.7.2) "
                        "für den Versionsvergleich")
    p.add_argument("--expected-sha256", default=None,
                   help="erwarteter SHA-256 (Integritätscheck; "
                        "Abweichung => Exit 1)")
    p.add_argument("--vorlagen", default=None,
                   help="Vorlagen-CSV (id;typ;en;de_jetzt;de_voll;"
                        "max_bytes;de_kurz_vorschlag;pixel_breite); "
                        "optional")
    p.add_argument("--abruftag", default=None,
                   help="Abrufdatum YYYY-MM-DD (Reproduzierbarkeit; "
                        "kein System-Zeitstempel)")
    p.add_argument("--out-dir", default=".",
                   help="Zielverzeichnis (default: .)")
    args = p.parse_args(argv)

    try:
        with open(args.quelle, "rb") as fh:
            roh = fh.read()
    except OSError as e:
        print("Fehler: Quelle nicht lesbar: %s" % e, file=sys.stderr)
        return 1
    sha = hashlib.sha256(roh).hexdigest()
    if args.expected_sha256 and sha != args.expected_sha256:
        print("Fehler: SHA-256-Mismatch: erwartet %s, gefunden %s"
              % (args.expected_sha256, sha), file=sys.stderr)
        return 1
    try:
        text = roh.decode("utf-8")
    except UnicodeDecodeError as e:
        print("Fehler: Quelle ist kein gültiges UTF-8 (Byte %d, %s) — "
              "Eingabe abgebrochen" % (e.start + 1, e.reason),
              file=sys.stderr)
        return 1

    vorlagen = None
    if args.vorlagen:
        try:
            vorlagen = laden_vorlagen(args.vorlagen)
        except (OSError, csv.Error, UnicodeDecodeError, ValueError) as e:
            print("Fehler: Vorlagen ungültig oder nicht lesbar: %s" % e,
                  file=sys.stderr)
            return 1

    titel, titel_version, zeilen, strukturfehler, hinweise = \
        parse_dokument(text)
    if not zeilen:
        print("Fehler: keine Tabellenzeilen mit Daten gefunden",
              file=sys.stderr)
        return 1

    out = verarbeite(zeilen, vorlagen)
    stat = statistik(out, strukturfehler)

    konf = {
        "quelle_url": args.quelle_url,
        "sha256": sha,
        "expected_sha256": args.expected_sha256,
        "asset_version": args.asset_version,
        "abruftag": args.abruftag,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    csv_pfad = os.path.join(args.out_dir, "limits_inventory.csv")
    with open(csv_pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(FELDER)
        for r in out:
            w.writerow([
                args.quelle_url, sha, r["zeile"], r["bereich"],
                r["kurzform"], r["vollform"], r["limit_z"], r["zeichen"],
                r["limit_status"], r["duplikat"],
                r["duplikat_von_zeile"], r["duplikat_vorkommen"],
                r["vorlagen_abgleich"], r["vorlagen_ids"],
                r["vorlagen_grund"], UNK, UNK, UNK, UNK,
            ])
    report_pfad = os.path.join(args.out_dir, "limits_inventar_report.md")
    with open(report_pfad, "w", encoding="utf-8") as fh:
        fh.write(report_markdown(konf, titel, titel_version, out, stat,
                                 hinweise))

    print("limits_inventar: %d Zeilen (%d unterschiedlich, %d Duplikate), "
          "%d Bereiche; Limit-Status %s; Vorlagen-Status %s; "
          "Strukturfehler: %d"
          % (stat["total"], stat["unique"], stat["dup_vorkommen"],
             len(stat["per_bereich"]),
             " ".join("%s=%d" % kv for kv in sorted(stat["limit_status"].items())),
             " ".join("%s=%d" % kv for kv in sorted(stat["vorlagen_status"].items())),
             len(stat["strukturfehler"])))
    print("-> %s" % csv_pfad)
    print("-> %s" % report_pfad)

    if stat["limit_status"].get("ueberschreitung", 0) > 0 or strukturfehler:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
