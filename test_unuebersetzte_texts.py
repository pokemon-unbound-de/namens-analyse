#!/usr/bin/env python3
"""Unit-Tests fuer unuebersetzte_texts.py (synthetische Fixtures,
public-safe: keine Spieltexte).

QA 2026-10-28:
- Credit-/Namenslisten werden VOR der Satz-Klassifikation erkannt
  (beginnende Leerzeile + >= 2 Namenszeilen ohne Satz-/Komma-
  Zeichensetzung) — Credits sind gewollt unübersetzt, KEINE Lücken.
- `satz` ist ein Prüf-Kandidat, keine belegte Lücke.

Korpus-Format-Vertrag: Zeilenumbrüche sind im CSV literal `\\n`
(Backslash + n), keine echten Newlines.
"""

import csv
import os
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import unuebersetzte_texts as ut  # noqa: E402

SCRIPT = os.path.join(BASE, "unuebersetzte_texts.py")


class TestIstCreditsList(unittest.TestCase):
    def test_klassische_credits_liste(self):
        self.assertTrue(ut.ist_credits_list(
            "\\nAlice Example\\nBob Example\\n\\n"))

    def test_mehrere_leerzeilen_vorne(self):
        # wie im Korpus: doppelte beginnende Leerzeile
        self.assertTrue(ut.ist_credits_list(
            "\\n\\nCarol Example\\nDave Example\\n\\n\\n"))

    def test_einzeilige_zeile_ist_keine_credits(self):
        self.assertFalse(ut.ist_credits_list("\\nOnly One Name\\n"))

    def test_ohne_beginnende_leerzeile(self):
        self.assertFalse(ut.ist_credits_list(
            "Start\\nAlice Example\\nBob Example"))

    def test_satz_ohne_leitenden_umbruch(self):
        self.assertFalse(ut.ist_credits_list("Hello there, friend!"))

    def test_komma_in_zeile(self):
        self.assertFalse(ut.ist_credits_list(
            "\\nFirst, with comma\\nSecond Line\\n"))

    def test_satzzeichen_in_zeile(self):
        for z in ("\\nOne line.\\nTwo lines\\n",
                  "\\nReally?\\nSecond line\\n",
                  "\\nWow!\\nSecond line\\n",
                  "\\nEnds …\\nSecond line\\n"):
            self.assertFalse(ut.ist_credits_list(z), msg=z)

    def test_leer(self):
        self.assertFalse(ut.ist_credits_list(""))
        self.assertFalse(ut.ist_credits_list("\\n\\n"))


class TestTypVon(unittest.TestCase):
    def test_ein_wort(self):
        self.assertEqual(ut.typ_von("Sparky"), "ein_wort")

    def test_kurz_text(self):
        self.assertEqual(ut.typ_von("abc def"), "kurz_text")
        self.assertEqual(ut.typ_von("abc def ghi"), "kurz_text")

    def test_satz(self):
        self.assertEqual(ut.typ_von("abc def ghi jkl"), "satz")


class TestCli(unittest.TestCase):
    def run_cli(self, korpus, out):
        return subprocess.run(
            [sys.executable, SCRIPT, "--korpus", korpus, "--out", out],
            capture_output=True, text=True)

    def test_credits_vor_satz_klassifikation(self):
        # Credit-Liste mit >= 4 "Wörtern" wäre ohne Credits-Regel
        # `satz`; jetzt korrekt `credits`.
        with tempfile.TemporaryDirectory() as td:
            korpus = os.path.join(td, "korpus.csv")
            out = os.path.join(td, "out.csv")
            with open(korpus, "w", encoding="utf-8", newline="") as fh:
                fh.write("id;en;de;kategorie;ort\n")
                fh.write("K-001;\\nAlice Example\\nBob Example\\n\\n;"
                         "\\nAlice Example\\nBob Example\\n\\n;"
                         "gap_misc;ort1\n")
                fh.write("K-002;Hello there now friend;"
                         "Hello there now friend;scripts;ort2\n")
                fh.write("K-003;Sparky;Sparky;ui;ort3\n")
                fh.write("K-004;Translated text;Another text;scripts;ort4\n")
                fh.write("K-005;;scripts;ort5\n")

            p = self.run_cli(korpus, out)
            self.assertEqual(p.returncode, 0, p.stderr)

            with open(out, encoding="utf-8", newline="") as fh:
                rows = {r["id"]: r for r in
                        csv.DictReader(fh, delimiter=";")}
            # übersetzte + leere Zeile fallen raus
            self.assertEqual(set(rows), {"K-001", "K-002", "K-003"})
            self.assertEqual(rows["K-001"]["typ"], "credits")
            self.assertEqual(rows["K-002"]["typ"], "satz")
            self.assertEqual(rows["K-003"]["typ"], "ein_wort")
            self.assertEqual(rows["K-001"]["raw_gleich"], "ja")
            # Aggregat-Hinweis im stderr
            self.assertIn("credits =", p.stderr)

    def test_case_unempfindlicher_abgleich(self):
        # nur Groß-/Kleinschreibung anders => unübersetzt
        with tempfile.TemporaryDirectory() as td:
            korpus = os.path.join(td, "korpus.csv")
            out = os.path.join(td, "out.csv")
            with open(korpus, "w", encoding="utf-8", newline="") as fh:
                fh.write("id;en;de;kategorie;ort\n")
                fh.write("K-006;Hello There Now Friend;"
                         "hello there now friend;scripts;ort1\n")
            p = self.run_cli(korpus, out)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(out, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh, delimiter=";"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["typ"], "satz")
            self.assertEqual(rows[0]["raw_gleich"], "nein")


if __name__ == "__main__":
    unittest.main()
