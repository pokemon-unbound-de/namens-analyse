#!/usr/bin/env python3
"""Unit-Tests fuer limits_inventar.py (synthetische Fixtures,
public-safe: keine Spieltexte, keine echten Namen/Vorlagen).

QA 2026-10-28 (CX-022):
- Zeichenzaehlung = Unicode-Codepunkte (nicht Bytes/PCS/Pixel)
- Duplikate bleiben erhalten und werden erklart (Erstvorkommen =
  Original, spaetere Vorkommen mit Zeilenbezug)
- Vorlagen-Abgleich nur exakt/eindeutig (Kurzform-Identitaet +
  Typ-Kompatibilitaet; dex: systematischer Suffix "-Pokémon"),
  sonst `offen` mit Grund
- Vorlagen-Header-Validierung: fehlende Pflichtspalten, falscher
  oder leerer Header => Exit 1 (kein stilles „keine Vorlagen“);
  korrekter Header ohne Datenzeilen => erlaubte leere Liste
- Ungültiges UTF-8 der Markdown-Quelle => sauberes Exit 1 ohne
  Traceback
- KEINE Byte-/Pixel-/Screen-/ROM-Adressen abgeleitet: die Spalten
  bleiben explizit `unbekannt`
- Titel-/Asset-Version-Abweichung = ungeklärter Inhaltsversionsbezug
- Exit-Codes 0/1/2; deterministisch (zweiter Lauf byte-identisch)
"""

import csv
import os
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import limits_inventar as li  # noqa: E402

SCRIPT = os.path.join(BASE, "limits_inventar.py")

VORLAGEN_HEADER = ("id;typ;en;de_jetzt;de_voll;max_bytes;"
                   "de_kurz_vorschlag;pixel_breite")


def zeile(bereich, kurz, voll, limit=12):
    return "| %s | %s | %s | Limit %d Zeichen |" % (bereich, kurz, voll, limit)


def dokument(*tabelle, titel="# Abkürzungen – Test v9.9", hinweis=True):
    teile = [titel, "", "| Bereich | Kurzform im Spiel | volle Form | Grund |",
             "|---|---|---|---|"]
    teile.extend(tabelle)
    if hinweis:
        teile.extend(["", "Hinweise: Synthetische Test-Zeile."])
    return "\n".join(teile) + "\n"


def vorlagen_csv(rows):
    """rows: (id, typ, de_voll, de_kurz)"""
    lines = [VORLAGEN_HEADER]
    for i, (vid, typ, voll, kurz) in enumerate(rows, 1):
        lines.append("%s;%s;EN%d;%s;%s;10;%s;50" % (vid, typ, i, kurz, voll, kurz))
    return "\n".join(lines) + "\n"


class Runner:
    def __init__(self, tmp):
        self.tmp = tmp

    def run(self, quellen_text, name="quelle.md", vorlagen_text=None,
            extra=None):
        qu = os.path.join(self.tmp, name)
        with open(qu, "w", encoding="utf-8") as fh:
            fh.write(quellen_text)
        vor = None
        if vorlagen_text is not None:
            vor = os.path.join(self.tmp, "vorlagen.csv")
            with open(vor, "w", encoding="utf-8") as fh:
                fh.write(vorlagen_text)
        out = os.path.join(self.tmp, "out")
        args = [sys.executable, SCRIPT, "--quelle", qu, "--out-dir", out]
        if vor:
            args += ["--vorlagen", vor]
        if extra:
            args += extra
        r = subprocess.run(args, capture_output=True, text=True)
        return r, out

    def les_csv(self, out):
        pfad = os.path.join(out, "limits_inventory.csv")
        with open(pfad, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh, delimiter=";"))

    def les_report(self, out):
        with open(os.path.join(out, "limits_inventar_report.md"),
                  encoding="utf-8") as fh:
            return fh.read()


class TestLimitsInventar(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="limits_inv_test_")
        self.r = Runner(self.tmp)

    def test_gueltiges_mini_dokument(self):
        doc = dokument(
            zeile("Items", "Aufz.Schl", "Aufzugsschlüssel", 12),
            zeile("Pokédex-Kategorien", "Ameisb.", "Ameisen-Pokémon", 11),
            zeile("Testbereich", "Testkürz.", "Testvoll", 12))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.r.les_csv(out)
        self.assertEqual(len(rows), 3)
        self.assertEqual([x["bereich"] for x in rows],
                         ["Items", "Pokédex-Kategorien", "Testbereich"])
        self.assertEqual(rows[0]["kurzform"], "Aufz.Schl")
        self.assertEqual(rows[0]["vollform"], "Aufzugsschlüssel")
        self.assertEqual(rows[0]["limit_z"], "12")
        self.assertEqual(rows[0]["zeichen"], "9")
        self.assertEqual(rows[0]["limit_status"], "im_limit")
        self.assertEqual(rows[1]["zeichen"], "7")
        self.assertEqual(rows[1]["limit_status"], "im_limit")
        self.assertEqual(rows[2]["zeichen"], "9")
        self.assertEqual(rows[2]["limit_status"], "im_limit")
        # explizit unbekannte Spalten
        for x in rows:
            self.assertEqual(x["versionsbezug"], "unbekannt")
            self.assertEqual(x["screen_zuordnung"], "unbekannt")
            self.assertEqual(x["rom_adresse"], "unbekannt")
            self.assertEqual(x["byte_limit"], "unbekannt")
        # Zeilenbezug in Datei-Reihenfolge
        self.assertEqual([int(x["zeile"]) for x in rows],
                         sorted(int(x["zeile"]) for x in rows))

    def test_zeichenzahl_unicode_nicht_bytes(self):
        # 12 Unicode-Zeichen, davon 3 Umlaute (14 UTF-8-Bytes):
        # eine Byte-Zaehlung wuerde fälschlich ueberschreiten.
        kurz = "Überflüssig."
        self.assertEqual(len(kurz), 12)
        self.assertGreater(len(kurz.encode("utf-8")), 12)
        doc = dokument(zeile("Items", kurz, "Überflüssige Sache", 12))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["zeichen"], "12")
        self.assertEqual(row["limit_status"], "grenze")

    def test_ueberschreitung_exit2(self):
        kurz = "ZuLangeTestK."  # 13 Zeichen
        doc = dokument(zeile("Items", kurz, "Voll", 12))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 2, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["limit_status"], "ueberschreitung")
        self.assertIn("ueberschreitung=1", r.stdout)

    def test_duplikate_erhalten_und_erklaert(self):
        doc = dokument(
            zeile("Pokédex-Kategorien", "Dupl.", "Duplikat-Pokémon", 11),
            zeile("Pokédex-Kategorien", "Einzig.", "Einziges-Pokémon", 11),
            zeile("Pokédex-Kategorien", "Dupl.", "Duplikat-Pokémon", 11),
            zeile("Pokédex-Kategorien", "Dupl.", "Duplikat-Pokémon", 11))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.r.les_csv(out)
        self.assertEqual(len(rows), 4)  # alle erhalten
        d = [x for x in rows if x["kurzform"] == "Dupl."]
        self.assertEqual([x["duplikat"] for x in d], ["nein", "ja", "ja"])
        self.assertEqual([x["duplikat_vorkommen"] for x in d], ["1", "2", "3"])
        self.assertEqual(d[0]["duplikat_von_zeile"], "")
        self.assertEqual(d[1]["duplikat_von_zeile"], d[0]["zeile"])
        self.assertEqual(d[2]["duplikat_von_zeile"], d[0]["zeile"])
        report = self.r.les_report(out)
        self.assertIn("zusätzliche identische Vorkommen: 2", report)

    def test_duplikat_nur_gleicher_bereich(self):
        doc = dokument(
            zeile("Items", "Gleich.", "Gleiches Ding", 12),
            zeile("Pokédex-Kategorien", "Gleich.", "Gleiches Ding-Pokémon", 11))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.r.les_csv(out)
        self.assertEqual([x["duplikat"] for x in rows], ["nein", "nein"])

    def test_ohne_explizites_limit(self):
        doc = "| Bereich | Kurzform im Spiel | volle Form | Grund |\n|---|---|---|---|\n| Items | KeineLim. | Ohne Limit | sonstiger Grund |\n"
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["limit_z"], "")
        self.assertEqual(row["limit_status"], "kein_explizites_Limit")

    def test_vorlagen_exakt_eindeutig_item(self):
        doc = dokument(zeile("Items", "Rost. Test", "Rostiger Test", 12))
        vor = vorlagen_csv([("0x0000001/10", "item", "Rostiger Test", "Rost. Test")])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "exakt_eindeutig")
        self.assertEqual(row["vorlagen_ids"], "0x0000001/10")
        self.assertEqual(row["vorlagen_grund"], "")

    def test_vorlagen_dex_suffix_mehrmals_ids_eindeutig(self):
        doc = dokument(zeile("Pokédex-Kategorien", "Glüw.", "Glühwürm-Pokémon", 11))
        vor = vorlagen_csv([
            ("0x0000002/10", "dex_kategorie", "Glühwürm", "Glüw."),
            ("0x0000003/10", "dex_kategorie", "Glühwürm", "Glüw."),
        ])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "exakt_eindeutig")
        self.assertEqual(row["vorlagen_ids"], "0x0000002/10,0x0000003/10")

    def test_vorlagen_dex_genau_ohne_suffix(self):
        doc = dokument(zeile("Pokédex-Kategorien", "Glüw.", "Glühwürm", 11))
        vor = vorlagen_csv([("0x0000002/10", "dex_kategorie", "Glühwürm", "Glüw.")])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.r.les_csv(out)[0]["vorlagen_abgleich"],
                         "exakt_eindeutig")

    def test_vorlagen_mehrfach_vollformen_offen(self):
        # Zwei distinkte Vollformen mit gleicher Kurzform: eine passt
        # exakt, die andere nur über den Suffix => mehrfach => offen.
        doc = dokument(zeile("Pokédex-Kategorien", "Amb.", "Ambig-Pokémon", 11))
        vor = vorlagen_csv([
            ("0x0000004/10", "dex_kategorie", "Ambig-Pokémon", "Amb."),
            ("0x0000005/10", "dex_kategorie", "Ambig", "Amb."),
        ])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "offen_mehrfach")
        self.assertEqual(row["vorlagen_grund"], "mehrere_Vollformen")
        self.assertIn("0x0000004/10", row["vorlagen_ids"])
        self.assertIn("0x0000005/10", row["vorlagen_ids"])

    def test_vorlagen_typ_inkompatibel_offen(self):
        # Item-Vorlage, aber dex-Bereich: Kandidaten-Filter leer.
        doc = dokument(zeile("Pokédex-Kategorien", "FremdT.", "Fremdes-Pokémon", 11))
        vor = vorlagen_csv([("0x0000006/10", "item", "Fremdes-Pokémon", "FremdT.")])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "offen_kein_Treffer")
        self.assertEqual(row["vorlagen_grund"], "kein_Treffer")

    def test_vorlagen_kurzform_ohne_vollform(self):
        doc = dokument(zeile("Items", "Weich.", "Weiches Ding", 12))
        vor = vorlagen_csv([("0x0000007/10", "item", "Weiches Ding X", "Weich.")])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "offen_kein_Treffer")
        self.assertEqual(row["vorlagen_grund"], "kurzform_ohne_Vollform_Treffer")

    def test_unbekannter_bereich_ohne_vorlagenbereich(self):
        doc = dokument(zeile("Testbereich", "Irgendw.", "Irgendwas", 12))
        vor = vorlagen_csv([("0x0000008/10", "item", "Irgendwas", "Irgendw.")])
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "ohne_Vorlagenbereich")
        self.assertEqual(row["vorlagen_grund"], "kein_Vorlagenbereich")

    def test_ohne_vorlagen_flag(self):
        doc = dokument(zeile("Items", "OhneVor.", "Ohne Vorlagen", 12))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "ohne_Vorlagen")
        self.assertEqual(row["vorlagen_grund"], "vorlagen_datei_nicht_vorgegeben")

    def test_vorlagen_fehlerhafter_header_exit1(self):
        # Falscher Header + Datenzeilen dürfen nicht stumm als
        # „keine Vorlagen“ durchgehen, sondern abbrechen.
        doc = dokument(zeile("Items", "Irgendw.", "Irgendwas", 12))
        vor = "wrong;headers\na;b\n"
        r, _ = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Pflichtspalte", r.stderr)
        self.assertIn("de_kurz_vorschlag", r.stderr)
        self.assertIn("wrong", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_vorlagen_leere_datei_exit1(self):
        doc = dokument(zeile("Items", "Irgendw.", "Irgendwas", 12))
        r, _ = self.r.run(doc, vorlagen_text="")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("kein Header", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_vorlagen_teilweiser_header_exit1(self):
        # Header vorhanden, aber zwei Pflichtspalten fehlen.
        doc = dokument(zeile("Items", "Irgendw.", "Irgendwas", 12))
        vor = "id;typ\neins;zwei\n"
        r, _ = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("de_kurz_vorschlag", r.stderr)
        self.assertIn("de_voll", r.stderr)

    def test_vorlagen_korrekter_header_ohne_datazeilen_ok(self):
        # Gültiger Header, aber keine Datenzeilen = erlaubte
        # (leere) Vorlagen-Liste, kein Fehler.
        doc = dokument(zeile("Items", "Irgendw.", "Irgendwas", 12))
        vor = VORLAGEN_HEADER + "\n"
        r, out = self.r.run(doc, vorlagen_text=vor)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["vorlagen_abgleich"], "offen_kein_Treffer")
        self.assertEqual(row["vorlagen_grund"], "kein_Treffer")

    def test_quelle_ungueltiges_utf8_exit1(self):
        qu = os.path.join(self.tmp, "quelle_binaer.md")
        with open(qu, "wb") as fh:
            fh.write("# Titel\n\n| x | y | z | w | Limit 4 Zeichen |\n"
                     .encode("utf-8"))
            fh.write(b"\xff\xfe| kaputt |")
        r = subprocess.run([sys.executable, SCRIPT, "--quelle", qu,
                            "--out-dir", os.path.join(self.tmp, "out")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("UTF-8", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_hash_mismatch_exit1(self):
        doc = dokument(zeile("Items", "Hash.", "Hashvoll", 12))
        r, _ = self.r.run(doc, extra=["--expected-sha256", "0" * 64])
        self.assertEqual(r.returncode, 1)
        self.assertIn("SHA-256-Mismatch", r.stderr)

    def test_fehlende_datei_exit1(self):
        r = subprocess.run([sys.executable, SCRIPT, "--quelle",
                            os.path.join(self.tmp, "fehlt.md")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("nicht lesbar", r.stderr)

    def test_strukturfehler_exit2(self):
        doc = ("# Titel\n\n| Bereich | Kurzform im Spiel | volle Form | Grund |\n"
               "|---|---|---|---|\n"
               "| Items | Gut. | Gutes Ding | Limit 12 Zeichen |\n"
               "| Items | Dreispalt | unvollstaendige Zeile\n"
               "| Items | Gut2. | Gutes Ding Zwei | Limit 12 Zeichen |\n")
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 2, r.stderr)
        rows = self.r.les_csv(out)
        self.assertEqual(len(rows), 2)  # defekte Zeile ausgeschlossen
        self.assertIn("Strukturfehler (Zeilen):", self.r.les_report(out))

    def test_leere_datei_exit1(self):
        r, _ = self.r.run("# Nur Titel\n\nKeine Tabelle.\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("keine Tabellenzeilen", r.stderr)

    def test_titel_version_ungeklaert(self):
        doc = dokument(zeile("Items", "Vers.", "Versionsding", 12),
                       titel="# Abkürzungen – Beta v0.1")
        r, out = self.r.run(doc, extra=["--asset-version", "v0.1.7.2"])
        self.assertEqual(r.returncode, 0, r.stderr)
        report = self.r.les_report(out)
        self.assertIn("Inhaltsversionsbezug: UNBEKANNT", report)
        self.assertIn("v0.1.7.2", report)
        row = self.r.les_csv(out)[0]
        self.assertEqual(row["versionsbezug"], "unbekannt")

    def test_titel_version_uebereinstimmend(self):
        doc = dokument(zeile("Items", "Vers.", "Versionsding", 12),
                       titel="# Abkürzungen – Beta v0.1.7.2")
        r, out = self.r.run(doc, extra=["--asset-version", "v0.1.7.2"])
        self.assertEqual(r.returncode, 0, r.stderr)
        report = self.r.les_report(out)
        self.assertIn("stimmen überein", report)

    def test_hinweise_zeile_wird_im_report_gefuhrt(self):
        doc = dokument(zeile("Items", "Hinw.", "Hinweisding", 12))
        r, out = self.r.run(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        report = self.r.les_report(out)
        self.assertIn("Kontext: Hinweise-Zeile(n) des Dokuments", report)
        self.assertIn("Synthetische Test-Zeile.", report)

    def test_determinismus_zweiter_lauf_byteidentisch(self):
        doc = dokument(
            zeile("Items", "Det. Eins", "Deterministisches Ding", 12),
            zeile("Items", "Det. Eins", "Deterministisches Ding", 12),
            zeile("Pokédex-Kategorien", "Det. Zwei", "Determin-Pokémon", 11))
        vor = vorlagen_csv([("0x0000009/10", "item", "Deterministisches Ding", "Det. Eins")])
        r1, out1 = self.r.run(doc, vorlagen_text=vor,
                              extra=["--asset-version", "v0.1.7.2",
                                     "--abruftag", "2026-10-28"])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        out2 = os.path.join(self.tmp, "out2")
        args = [a for a in [sys.executable, SCRIPT, "--quelle",
                            os.path.join(self.tmp, "quelle.md"),
                            "--out-dir", out2, "--vorlagen",
                            os.path.join(self.tmp, "vorlagen.csv"),
                            "--asset-version", "v0.1.7.2",
                            "--abruftag", "2026-10-28"]]
        r2 = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        for name in ("limits_inventory.csv", "limits_inventar_report.md"):
            with open(os.path.join(out1, name), "rb") as fh1, \
                    open(os.path.join(out2, name), "rb") as fh2:
                self.assertEqual(fh1.read(), fh2.read(), name)


if __name__ == "__main__":
    unittest.main()
