# namens-analyse

Deterministische Text-Analysen für die
[Pokémon-Unbound-DE-Übersetzung](https://github.com/pokemon-unbound-de).
Alles läuft **offline, ohne LLM und deterministisch** (zweiter Lauf
byte-identisch). Der Code ist public-safe: er enthält keine
Spieltexte; Eingabe-Dateien (Korpus, Kanon, Glossar, Vorlagen) werden
per Pfad übergeben.

## Werkzeuge

| Script | Zweck |
|---|---|
| `namens_analyse.py` | Drei Analysen: Namens-Abgleich, englische Reste, Ortsnamen-Einheitlichkeit |
| `unuebersetzte_texts.py` | Report aller nicht-übersetzten Korpus-Zeilen (EN == DE nach Normalisierung) — „Was fehlt noch?"-Liste für Pre-Stable |
| `vorlagen_ergaenzen.py` | Vollendet die Vorlagen aus `werkstatt-konsistenz-daten` (6er-Aufgabe 5+6: Item-Kurzformen, Pokédex) |
| `vorlagen_erstellen.py` | Alternative Vorlagen-Erzeugung komplett aus Kanon + Korpus (ohne Basis-Vorlagen) |
| `limits_inventar.py` | Reproduzierbares Abkürzungs-/Limits-Inventar mit Quellenbezug: pro Zeile URL/Hash/Zeilennummer/Bereich/Kurz-/Vollform/Limit/Zeichen; Duplikat-Erhalt, exakter/eindeutiger Vorlagen-Abgleich (sonst `offen`), explizite Unbekanntes (Screen/ROM/Byte), Versionsbezug |

Nur Standardbibliothek, Python ≥ 3.8. Laufzeit: < 5 s (Analyse),
< 30 s (Vorlagen erstellen).

---

## 1. `namens_analyse.py`

```
python3 namens_analyse.py \
  --korpus  texte_v0.1.7.2.csv \
  --kanon   kanon_namen.csv \
  --glossar NAMENSVERZEICHNIS.md \
  --out-dir ergebnisse/            # default: ./
```

Optionen: `--max-tippfehler-haeufig N` (default 3), `--kalibrier`
(druckt alle Befunde der drei Analysen nach stdout statt CSVs).

### Ausgaben

| Datei | Schema | Inhalt |
|---|---|---|
| `namens_abgleich.csv` | `id;gefunden;richtig;typ;quelle` | Offizielle EN-Namen, die im DE-Text stehen, statt des DE-Namens; plus seltene Fehlreibungen offizieller DE-Namen |
| `en_reste.csv` | `id;fundstelle;en_wort;vorschlag` | Englische Reste in DE-Texten (drei enge Regeln, siehe unten) |
| `ortsnamen.csv` | `id;erwartet_de;gefunden;typ;quelle` | Abweichungen bei Ortsnamen gegen das Namensverzeichnis (EN-Form statt DE-Form, oder seltene Fehlreibung) |

### Normalisierung

- NFKC, Steuerzeichen → Leer, Farbcodes/Puffer-Platzhalter `[…x…]`
  raus, `ESC_RE = \\[A-Za-z.]+` → Leer.
- **Wichtig**: Das Korpus speichert Zeilenumbrüche/Marker als
  *literale* Zeichenketten (`\n`, `\p`, `\l`, `\qo`, `\qc`, `\.`, …).
  Werden sie nicht normalisiert, kleben Tokens zusammen
  (`\nSparky` → `nSparky`).
- `WORD_RE = [A-Za-zÀ-ÿ]{3,}` (inkl. Akzente — sonst zerfällt
  „Pokémon“ in `Pok`+`mon`), `NAME_TOKEN_RE =
  [A-ZÀ-ÖÜ][A-Za-zÀ-ÿ\-']{2,}`.

### Analyse 1: Namens-Abgleich

Zwei Prüfungen pro Zeile:

1. **EN-Name im DE-Text** — der offizielle englische Name eines
   Kanon-Eintrags steht (Wortgrenzen, case-insensitiv) im
   DE-Text, obwohl es einen deutschen Namen gibt. Skips:
   - identischer Name (z. B. Mew),
   - **Kognat-Regel**: `EN_COGNATE = {mist, pass, rest, klang,
     charge, rage, flash, leer}` — EN-Namen, die zugleich alltägliche
     deutsche Wörter sind, hundertfach im Korpus als normales
     Deutsch; `leer` kalibriert in der #39-Korrekturrunde
     (UI-Label „No data“ → „Leer“: Falschpositiv, kein Fehlnamen);
   - **Kollisions-Regel**: EN-Name, der zugleich ein offizielles
     DE-Name ist (EN „Spotlight“ = DE-Name von „Follow Me“) →
     Vorkommen im DE-Text ist korrekt.
2. **Seltene Fehlreibung eines DE-Namens** — Token im DE-Text, das
   edit-distanz-1 zu einem offiziellen DE-Namen liegt, selten ist
   (`token_freq ≤ --max-tippfehler-haeufig`) und keine korrekte
   deutsche Form ist. Skips:
   - offizielle Namen (EN oder DE),
   - **Flexions-Regeln** (`ist_flexion`): Suffixe
     `n/s/e/es/en/'/s'/s′` (Giftstachel+n, Grandiras+'),
     Bindestrich am Zeilenende (`Dürre-`), Bindestrich statt
     Leerzeichen (`Silph-Scope` ~ `Silph Scope`). Bewusst **keine**
     Kürzungs-Regel — `Mega-Armreif` ~ `Mega-Armreife` bleibt ein
     Befund.
   - **Wörter-Guard** (`DE_WOERTER_GUARD`, 74 kuratierte deutsche
     Wörter, die edit-1-nah an offiziellen Namen liegen): greift
     **nur für Titlecase** („Eher“ → geschützt). ALL-CAPS-Ganzzeilen
     („EHER“, „BELEBEN“) sind genuine Befunde (fehlender/falscher
     Name im Namensfeld) und bleiben gemeldet.

### Analyse 2: Englische Reste

Bewusst **kein** Wort-für-Wort-Reporting (wäre Lärm über Lärm);
drei enge Regeln:

1. **Läufe ≥ 2 aufeinanderfolgender EN-Wörter** in (teilweise)
   übersetzten Zeilen: jedes Token auch in der EN-Quelle derselben
   Zeile (Alignment), keines in den Ausnahmelisten, **und mindestens
   ein Wort mit kuratierter deutscher Entsprechung**
   (`EN_DE_VORSCHLAG`). Ohne die Map-Regel wären
   Eigenname-Comounds („Kanto-Region“, „Safari-Zone“),
   Produktbezeichnungen und Onomatopöien reiner Lärm.
2. **Einzelnes kapitalisiertes EN-Wort** — nur mit kuratierter
   deutscher Entsprechung (`EN_DE_VORSCHLAG`).
   Kleingeschriebene Einzelfälle bleiben unerfasst: ohne
   Wörterbuch nicht von deutschem Deutsch zu unterscheiden
   (dokumentierte Entscheidung).
3. **Komplett unübersetzte Zeilen (EN == DE)** — nur mit ≥ 1
   Map-Wort und ohne Marken-Wörter. Fängt exakt Fälle wie
   `Autumn` → `Herbst`; Credits, Namen, Onomatopöien, Labels
   bleiben sauber aussortiert.

Ausnahmelisten (kuratiert, im Code dokumentiert):

| Liste | Zweck | Beispiel |
|---|---|---|
| `LEHNWORTER` | gewollt englische Begriffe in DE (Item, Team, …); **bewusst eng** — gewöhnliche EN-Wörter (door, mountain, …) stehen nicht drin, **außer** `city` (#39-Korrekturrunde: offizielle deutsche Stadtnamen behalten bewusst „City“, z. B. „Antisis City“ — kein Rest). Achtung: `casefold()` streicht keine Akzente, daher `pokedex` **und** `pokédex` explizit | `item, team, route, city, pokédex, pokécenter, pokénav` |
| `GERMAN_STOP` | Wörter, die identisch deutsch sind; `winter` (Saison-Label), `bring` (deutscher Imperativ „Bring mir …“), `all` (umgangssprachliches deutsches „all“ = „alle“), `look` (deutscher Lehnwort-Gebrauch „neuen Look“) — die beiden letzteren #39-Korrekturrunde | `tag, man, mal, winter, bring, all, look` |
| `MARKEN` | Marken-/Label-Zeilen, bewusst unübersetzt | `smogon, unbound` |
| `EN_DE_VORSCHLAG` | kuratierte EN→DE-Entsprechungen für die Regeln 2+3 und den Läufer; `autumn→Herbst`, … (die früheren Beispiele `city→Stadt`, `all→alle`, `look→schauen` werden seit #39 von LEHNWORTER/GERMAN_STOP vorab erwischt — in der Map redundant, aber harmlos) | `autumn→Herbst` |

### Analyse 3: Ortsnamen-Einheitlichkeit

Gegen die 108 Ortsnamen aus `NAMENSVERZEICHNIS.md`:

1. EN-Form (bzw. seltene EN-Variante) im DE-Text, wo die DE-Form
   stehen sollte,
2. seltene Fehlreibung der DE-Form (edit-1, mit den gleichen
   Flexions-Regeln + Wörter-Guard wie Analyse 1).

### Stand 2026-10-28 (Reproduzierbarkeit)

- **Korpus**: `werkstatt-konsistenz-daten` → `texte_v0.1.7.2.csv`
  (17.188 Zeilen; EN == DE: 438)
- **Kanon**: `kanon-namensliste` @ `9b2ee2e` (3.273 Zeilen: 1.025
  pokémon, 1.005 item, Attacken/Fähigkeiten; z. B. EN „Darkest
  Lariat“ = DE `Dark Lariat` ist offizieller DE-Name → kein Befund)
- **Glossar**: `pokemon-unbound-de/docs/NAMENSVERZEICHNIS.md`
  (108 Orte, 258 Glossar-DE-Namen)
- **Ergebnis** (nach #39-Korrekturrunde): Abgleich **8**
  (1 EN-Name `Upgrade`; 7 Tippfehler), Reste **4**
  (`Speed`, `Power`, `Win-win`, `Autumn` — als **Hinweise** ohne
  Auto-Fix), Ortsnamen **4** (`Tarmigan` → `Tarmigau` ×3,
  `Antisia-Kanal` → `Antisis-Kanal`)
- #39-Kalibrierung: `Leer` → `EN_COGNATE` (Abgleich 9 → 8),
  `city` → `LEHNWORTER`, `all` + `look` → `GERMAN_STOP`
  (Reste 16 → 4). **Nebenwirkung**: die Zeile mit dem bekannten
  Daten-Schaden „ür“ wird dadurch nicht mehr als Rest gemeldet
  (das `all` in derselben Zeile ist jetzt Stop-Wort); der Schaden
  bleibt in den Korpus-Daten sichtbar.
- Die Outputs enthalten Spieltext → **private** Repo
  (`werkstatt-konsistenz-daten/ergebnisse/`); hier nur Code.

Alle Kuratierungs-Entscheidungen (welches Wort in welche Liste,
warum) sind im Code kommentiert und wurden gegen den Kontext der
betroffenen Zeilen geprüft (Kalibrierungs-Protokoll liegt privat
unter `research/konsistenz-kalibrierung.md`).

---

## 2. `unuebersetzte_texts.py`

```
python3 unuebersetzte_texts.py --korpus texte_v0.1.7.2.csv \
    --out unuebersetzte.csv
```

Meldet alle Zeilen, deren DE-Text nach `norm()` identisch mit dem
EN-Text ist (= nicht übersetzt). Output:
`id;kategorie;ort;en;de;raw_gleich;typ`.

- `raw_gleich` = `nein` → nur Steuercodes/Farbcodes weichen ab
  (Text unangetastet),
- `typ` nach Wortzahl: `satz` (≥ 4 Wörter = echte Lücke),
  `kurz_text` (2–3), `ein_wort` (1; meist gewollte Namen/
  Onomatopöien).

Stand 2026-10-28: 444 von 17.188 Zeilen (48 `satz`, 72 `kurz_text`,
324 `ein_wort`). Output enthält Spieltext → privat.

## 3. `vorlagen_ergaenzen.py` (6er-Aufgabe 5+6)

Vollendet die Vorlagen aus `werkstatt-konsistenz-daten`
(Stand `4c40b4f`) — deterministisch:

```
python3 vorlagen_ergaenzen.py \
  --basis-item item_kurzformen.basis.csv \
  --basis-dex  dex_offen.basis.csv \
  --out-item   item_kurzformen.csv \
  --out-dex    dex_offen.csv
```

- **`item_kurzformen.csv`** (21 Zeilen: 2 Items + 19
  `dex_kategorie`): leere `de_voll`-Zellen mit den offiziellen
  deutschen Vollformen gefüllt (Kuratiert-Map `KATEGORIE_VOLL`,
  aus den Abkürzungs-Präfixen rekonstruiert: `Klingenkr.` = 9
  Zeichen von `Klingenkrieger`, …; `Hummelflieger` ist ein
  dokumentierter Vorschlag). Spalte `de_kurz_vorschlag`:
  passt `de_jetzt` in `max_bytes`, bleibt es unverändert;
  sonst längster Präfix der Vollform + Punkt. Kontrolle: alle
  Vorschläge ≤ `max_bytes` (assertiert).
  - **Maßstab (nach #39-Korrekturrunde): GBA-PCS-Bytes — 1 Byte
    pro Zeichen** (256er-Zeichensatz; Umlaute ä ö ü ß und
    Ä Ö Ü = 1 Byte wie lateinische Zeichen, **nicht** UTF-8, wo
    sie 2 Byte kosten). Im Stand `4c40b4f` passen damit **alle
    21 Zeilen**; `Glühwürmch.` = 11 PCS-Bytes ≤ `max_bytes` 11
    und bleibt unverändert (im alten UTF-8-Maßstab wären es
    13 Byte gewesen → zu kurzes „Glühwürm.“).
  - Neue Spalte **`pixel_breite`** (informativ, #39: Pixelbreite
    getrennt von der Byte-Breite testen): Breite in Pixeln im
    FireRed-Normalfont (summierte Glyph-Vorschübe). Kein
    Pass/Fail — Bildschirm-Limits je Screen/Buffer
    unterschiedlich (Referenz: 0xFD-Textpuffer = 54 px).
  - **Metriken-Quelle** (MIT): Glyph-Breiten-Tabelle
    (`sFontNormalLatinGlyphWidths` aus pret/pokefirered
    `src/text.c`) + Zeichentabelle portiert aus
    [Simopich/unbound-translator](https://github.com/Simopich/unbound-translator)
    (`lib/gen3_font.py`, `lib/pcs_text.py`), Stand `main` @
    2026-10-28; Port gegen die Quelldateien byte-identisch
    verifiziert (Tabellen + Pixelbreiten-Crosscheck).
- **`dex_offen.csv`** (807 Zeilen, `nr` 1..807):
  - `edition` **bewusst leer** (#39-Korrekturrunde): „Gen 1“ aus
    der Dex-Nummer ist eine Generationsspanne, keine Edition —
    erst nach exaktem Satz-Abgleich gegen den Pokédex-Text
    befüllen. Generationsspannen-Annahme (nationale Dex-Nummern:
    1–151 Gen 1, 152–251 Gen 2, 252–386 Gen 3, 387–493 Gen 4,
    494–649 Gen 5, 650–721 Gen 6, 722–809 Gen 7) nicht
    verifiziert, auf Anfrage verfügbar;
  - `quelle` **bewusst leer** (#39): ein Artenname im
    Kategorie-Text belegt keinen Pokédex-Wortlaut — auch erst
    nach exaktem Satz-Abgleich;
  - sortiert nach `haeufigkeit` absteigend (Tie-Break `nr`) — die
    100 häufigsten stehen oben.

## 4. `vorlagen_erstellen.py`

Erstellt beide Vorlagen komplett neu aus Kanon + Korpus (ohne
Basis-Vorlagen), falls keine bereitstehen: alle 1.005 Kanon-Items
mit Kurzform-Vorschlag (≤ 13 Byte) + die 100 häufigsten
Kanon-Pokémon nach Korpus-Vorkommen.

```
python3 vorlagen_erstellen.py \
  --kanon kanon_namen.csv --korpus texte_v0.1.7.2.csv --out-dir vorlagen/
```

---

## 5. `limits_inventar.py`

Reproduzierbares Abkürzungs-/Limits-Inventar für Abkürzungs-Dokumente
(öffentliches Release-Asset, z. B. `ABKUERZUNGEN.md` zu v0.1.7.2;
Ziel: `werkstatt-konsistenz-daten/ergebnisse/limits-inventar/`, privat):

```
python3 limits_inventar.py \
  --quelle ABKUERZUNGEN.md \
  --quelle-url <url> \
  --asset-version v0.1.7.2 \
  --expected-sha256 <hash> \
  --vorlagen item_kurzformen.csv \
  --abruftag 2026-10-28 \
  --out-dir ergebnisse/limits-inventar/
```

- **Pro Tabellenzeile**: Quelle (URL), Datei-SHA-256, Zeilennummer,
  Bereich, Kurzform, volle Form, dokumentiertes Zeichenlimit
  (`Limit N Zeichen`), Zeichenanzahl (Unicode-Codepunkte der
  Kurzform — reine Zeichenzählung)
- **Duplikate** werden erhalten und erklärt: Identität
  (Bereich, Kurzform, volle Form, Limit); Erstvorkommen = Original,
  spätere Vorkommen mit Zeilenbezug (`duplikat_von_zeile`,
  `duplikat_vorkommen`)
- **Vorlagen-Abgleich nur exakt/eindeutig** (sonst `offen` mit
  Grund): Kurzform-Identität + Bereich/Typ-Kompatibilität
  (Items↔`item`, Pokédex-Kategorien↔`dex_kategorie`, sonstige
  Bereiche → `ohne_Vorlagenbereich`); volle Form: Identität mit
  `de_voll`, im dex-Bereich zusätzlich der systematische Suffix
  `-Pokémon`. Genau ein distinktes Vollform-Paar →
  `exakt_eindeutig` (mit allen Vorkommen-IDs); mehrere distinkte
  Vollformen → `offen_mehrfach`; kein Treffer → `offen_kein_Treffer`
- **Vorlagen-Validierung**: der Header wird auf die Pflichtspalten
  `id`, `typ`, `de_kurz_vorschlag`, `de_voll` geprüft; leere
  Dateien oder fehlende/fehlerhafte Header → verständlicher
  Input-Fehler mit Exit 1 (kein stilles „keine Vorlagen“)
- **Keine abgeleiteten Belege**: Screen-Zuordnung, ROM-Adressen und
  Byte-Limits bleiben explizit `unbekannt` — sie werden **nicht** aus
  Zeichenlimits abgeleitet (keine PCS-/Pixel-/ROM-Interpretation);
  Pixelgrenzen sind nur pro Screen und passender Version belegbar
- **Inhaltsversionsbezug**: Abweichung zwischen der Titel-Version des
  Dokuments und `--asset-version` wird als offen dokumentiert —
  Limitwerte werden nicht pauschal über Versionen übernommen
- **Exit-Codes**: 0 = ohne Befunde; 1 = Input-Fehler (fehlende
  Datei, ungültiges UTF-8 der Quelle, SHA-256-Mismatch, keine
  Datenzeilen, unlesbare Vorlagen oder fehlerhafter/leerer
  Vorlagen-Header); 2 = Überschreitungen oder Strukturfehler > 0.
  **Kein Pflichtgate** — das Tool berichtet nur
- **Ausgaben**: `limits_inventory.csv` (Semikolon, pro Zeile, Datei-
  Reihenfolge) + `limits_inventar_report.md` (Methode, Summen,
  Duplikatgruppen, Vorlagen-Abgleich, explizite Unbekanntes,
  Dokument-Hinweise)
- Deterministisch: keine System-Zeitstempel (`--abruftag` als
  Argument); zweiter Lauf byte-identisch
- Tests: `test_limits_inventar.py` (synthetische Fixtures,
  public-safe; Negativfälle: Unicode-vs-Byte-Zählung, Überschreitung,
  Duplikat-Erhalt, Vorlagen-Mehrfach/Typ-Inkompatibilität,
  SHA-Mismatch, Strukturfehler, leere Datei, Versions-Abweichung,
  fehlerhafter/leerer/teilweiser Vorlagen-Header, ungültiges
  UTF-8 der Quelle, Determinismus)

---

## Datenschutz

Die Scripts selbst enthalten keine Spieltexte. Korpus-Dateien mit
Spieltexten gehören ins private Repo; öffentliche Outputs dürfen
nur Namen/Zahlen/Methoden enthalten.
