#!/usr/bin/env python3
"""
Namens-Analyse
==============
Deterministische Text-Analysen für die Pokémon-Unbound-DE-Übersetzung.

Prüft die DE-Texte eines Korpus-CSV gegen (a) die Kanon-Namensliste
(offizielle EN/DE-Namen) und (b) das Namensverzeichnis (Glossar, u. a.
Ortsnamen) — alles offline, ohne LLM, deterministisch.

Drei Analysen (jede mit eigener Ausgabe, alle privat = enthalten Text):

1. NAMENS-ABGLEICH  (-> namens_abgleich.csv)
   `id; gefunden; richtig; typ; quelle`
   Wo steht in der DE-Fassung ein offizielles EN-Namen (statt des DE-Namens)
   oder eine (selten vorkommende) Fehlreibung eines offiziellen DE-Namens?

2. ENGLISCHE RESTE  (-> en_reste.csv)
   `id; fundstelle; en_wort; vorschlag`
   Englische Reste in DE-Texten: (a) Läufe von 2+ aufeinanderfolgenden
   EN-Wörtern (jedes in der EN-Quelle derselben Zeile, keines in den
   Ausnahmelisten), (b) einzelnes kapitalisiertes EN-Wort mit
   kuratierter deutscher Entsprechung (EN_DE_VORSCHLAG), (c) komplett
   unübersetzte Zeilen (EN == DE) mit einem Wort aus EN_DE_VORSCHLAG
   (z. B. "Autumn" -> "Herbst"). Ausgenommen: Kanon-Namen, gewollte
   Lehnwörter (Item, Team, Route, Pokédex, ...), Marken, DE-Kognate.
   Französisch, Latein, Onomatopöien und Credits werden nicht gemeldet
   (dokumentierte Entscheidung; einzelne kleingeschriebene Wörter
   ebenso — Wort-für-Wort-Reporting wäre Lärm über Lärm).

3. ORTSNAMEN-EINHEITLICHKEIT  (-> ortsnamen.csv)
   `id; erwartet_de; gefunden; typ; quelle`
   Abweichungen bei Ortsnamen: EN-Form statt DE-Form, oder
   seltene Fehlreibung der DE-Form.

WICHTIG: Code ist public-safe (keine Spieltexte im Code). Die Ausgaben
enthalten Textinhalte -> privat ablegen, nie in öffentliche Repos.

Nutzung:
    python3 namens_analyse.py \
        --korpus    texte_v0.1.7.2.csv \
        --kanon     kanon_namen.csv \
        --glossar   NAMENSVERZEICHNIS.md \
        --out-dir   ./auswertung

Optionale Flags:
    --nur-abgleich / --nur-reste / --nur-ortsnamen   (nur eine Analyse)
    --max-tippfehler-haeufig N  (Tippfehler nur, wenn Token <= N mal,
                                Default 3)
    --kalibrier  (Diagnosen für die Schwellen drucken statt CSV-Dateien)
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Normalisierung & Tokenisierung
# --------------------------------------------------------------------------

CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Markierungscodes des Korpus: \n \p \l \qo \qc \au \ad \ar \. usw.
# Das Korpus speichert sie als LITERALE Zeichenketten (Backslash +
# Buchstaben), nicht als Steuerzeichen.
ESC_RE = re.compile(r"\\[A-Za-z.]+")
BRACKET_RE = re.compile(r"\[[^\]]*\]")          # Farbcodes / Puffer-Platzhalter
WS_RE = re.compile(r"\s+")

def norm(s: str) -> str:
    """Normalisierung für Namens-Scans: NFKC, Steuerzeichen -> Leer,
    Markierungscodes raus, Farbcodes/Puffer raus, Leerzeichen stauchen.
    Groß-/Klein BEHALTEN.

    Wichtig: Zeilenumbrüche/Marker sind im Korpus literale Zeichenketten
    ("\\n", "\\p", "\\qo", "\\.", ...) = Backslash + Zeichen. Die werden
    zu Leerzeichen, sonst kleben Tokens zusammen ("\\nSparky" ->
    "nSparky", "\\nExecutive" -> "nexecutive")."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = CTRL_RE.sub(" ", s)
    s = ESC_RE.sub(" ", s)
    s = BRACKET_RE.sub(" ", s)
    return WS_RE.sub(" ", s).strip()

# Namen-artiger Token: beginnt groß, min. 3 Zeichen, Buchstaben (auch
# Umlaute/akzentuierte Zeichen/Bindestrich/Apostroph). Fängt
# Eigennamen/Orte/Namen ein, nicht kleine Wörter.
NAME_TOKEN_RE = re.compile(r"[A-ZÀ-ÖÜ][A-Za-zÀ-ÿ\-']{2,}")
# Allgemeines Wort (für Alignment/Englisch-Erkennung): min. 3 Buchstaben,
# inkl. akzentuierter Zeichen (é, à, ü, ...) — sonst wird "Pokémon" zu
# "Pok" + "mon" getrennt (Tausende False Positives).
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")


def name_tokens(s: str):
    return NAME_TOKEN_RE.findall(s)


def edit1(a: str, b: str) -> bool:
    """Edit-Distanz genau 1 (Insertion/Deletion/Substitution)."""
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = skips = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            skips += 1
            if skips > 1:
                return False
            j += 1
    return True


# --------------------------------------------------------------------------
# Daten laden
# --------------------------------------------------------------------------

def load_kanon(path: str):
    """Kanon-CSV (typ;en;de;quelle). Rückgabe:
    en2de: {en: (de, typ, quelle)}
    de_names: list[(de, typ, quelle, en)]
    en_name_set, de_name_set (casefolded) für Ausschlüsse
    """
    en2de = {}
    de_names = []
    en_set = set()
    de_set = set()
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            t = (r.get("typ") or "").strip()
            en = (r.get("en") or "").strip()
            de = (r.get("de") or "").strip()
            q = (r.get("quelle") or "").strip()
            if not (t and en and de):
                continue
            en2de.setdefault(en, (de, t, q))
            de_names.append((de, t, q, en))
            en_set.add(en.casefold())
            de_set.add(de.casefold())
    return en2de, de_names, en_set, de_set


def load_orte(path: str):
    """Glossar: nur die '## Orte' -Sektion parsen.
    Rückgabe: [(de, en, art)]."""
    orte = []
    in_orte = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("## "):
                in_orte = line.lower().startswith("## orte")
                continue
            if not in_orte or not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            de, en = cells[0], cells[1]
            art = cells[2] if len(cells) > 2 else ""
            if de in ("DE", "---", "") or en in ("EN", "---", ""):
                continue
            if set(de) <= {"-"} or set(en) <= {"-"}:
                continue
            # "*vorläufig*"-Marker aus den Namen streichen
            orte.append((de.strip("*").strip(), en.strip("*").strip(), art))
    return orte


def load_glossar_names(path: str):
    """Glossar: alle DE-Namen aus allen Tabellensektionen (Figuren,
    Orte, Trainerklassen, Projektbegriffe). Rückgabe: list[str]."""
    names = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            de, en = cells[0], cells[1]
            if de in ("DE", "") or set(de) <= {"-"}:
                continue
            if en in ("EN", "") or set(en) <= {"-"}:
                continue
            names.append(de.strip("*").strip())
    return names


def load_corpus(path: str):
    rows = []
    seen = set()
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            rid = (r.get("id") or "").strip()
            en = (r.get("en") or "")
            de = (r.get("de") or "")
            if not rid or not en.strip() or not de.strip() or rid in seen:
                continue
            seen.add(rid)
            rows.append({
                "id": rid, "en": en, "de": de,
                "kategorie": (r.get("kategorie") or "").strip(),
                "ort": (r.get("ort") or "").strip(),
            })
    return rows


# --------------------------------------------------------------------------
# Namens-Matching (Präfix-Präfilter + Wortgrenzen-Regex)
# --------------------------------------------------------------------------

def build_prefix_index(names):
    """names: iterable von (key, payload). Indexiert nach ersten 4 Zeichen
    (casefolded). Rückgabe: {prefix4: [(key, payload, regex)]}."""
    idx = defaultdict(list)
    for key, payload in names:
        kcf = key.casefold()
        rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])")
        idx[kcf[:4]].append((key, payload, rx))
    return idx


def prefixes_present(text_cf: str):
    out = set()
    for n in (2, 3, 4):
        if len(text_cf) >= n:
            out.update(text_cf[i:i + n] for i in range(len(text_cf) - n + 1))
    return out


def match_names(text: str, text_cf: str, prefix_idx):
    """Alle Namen, die in text (Wortgrenzen, case-sensitive) vorkommen.
    Rückgabe: list[(key, payload)]."""
    hits = []
    seen = set()
    prefs = prefixes_present(text_cf)
    for key, bucket in prefix_idx.items():
        if key not in prefs:
            continue
        for name, payload, rx in bucket:
            if name in seen:
                continue
            if rx.search(text):
                seen.add(name)
                hits.append((name, payload))
    return hits


# --------------------------------------------------------------------------
# Analyse 1: NAMENS-ABGLEICH
# --------------------------------------------------------------------------

# Dokumentierte deutsche Kognate: offizielle EN-Namen, die zugleich
# alltägliche deutsche Wörter sind. Sie stehen im DE-Text hundertfach als
# normales Deutsch ("Pass gut auf!", "Mist!", "der Klang"), nicht als
# unübersetzter Name -> nie als "EN-Name im DE-Text" melden. Kuratiert
# aus der Kalibrierung (deckt ~60 von 73 sonst-BeFUNDen ab).
# "leer": deutsches Wort (z. B. UI-Label "No data" -> "Leer") — Issue #39
# Korrekturrunde: der Abgleich-Befund war ein Falschpositiv.
EN_COGNATE = {"mist", "pass", "rest", "klang", "charge", "rage", "flash",
              "leer"}

# Korrekte deutsche Flexionsendungen: ein Token, das aus dem offiziellen
# Namen plus ENDUNGE besteht, ist kein Tippfehler (Giftstachel+n,
# Prunusbeere+en, Fuegro+s im Genitiv, Grandiras+' als Besitzform).
INFL_SUFFIXE = ("n", "s", "e", "es", "en", "'", "s'", "s\u2032")

# Kuratierte deutsche Wörter, die edit-1-nah an offiziellen Namen liegen,
# aber korrektes Deutsch sind (aus der Kontext-Review der Kalibrierung):
# "Strudel" liegt edit-1-nah an "Sprudel", ist aber ein normales Wort
# ("im Strudel gefangen"). Die Regel greift nur für normal
# großgeschriebene Wörter (Titlecase, z. B. "Eher", "Sehe") —
# ALL-CAPS-Ganzzeilen wie "EHER"/"BELEBEN" sind genuine Befunde
# (falsches/fehlendes Namen im Namensfeld) und bleiben gemeldet.
DE_WOERTER_GUARD = {
    "autos", "baue", "beehre", "beiss", "blip", "blitze", "brülle",
    "brüllen", "eher", "eisensand", "eises", "engel", "entfessle", "entlassung",
    "euler", "fliehen", "flut", "formel", "formen", "frank", "gähnen",
    "harte", "heiler", "heulen", "hoop", "härter", "isst", "kante",
    "karriere", "kauz", "knospe", "krater", "kummer", "laub", "liegen",
    "link", "mangel", "minen", "nat", "nats", "niesen", "nix",
    "rasant", "raus", "riss", "ruten", "scharfer", "scher", "schmutz",
    "schutt", "schwebt", "schwere", "schütz", "sehe", "sehen", "sinus",
    "stahls", "starke", "strudel", "sturzflut", "säule", "tank", "techniken",
    "teer", "tinte", "urgh", "verzehren", "walzen", "wieso", "willy",
    "winkel", "wolle", "wollt", "zerschneiden"
}


def _is_de_woert(tok: str) -> bool:
    """Kuratiertes deutsches Wort? Nur Titlecase trifft die Guard-Regel
    ("Eher" -> ja, "EHER" -> nein): ALL-CAPS-Ganzzeilen sind
    genuine Befunde."""
    if not tok or not tok[0].isupper() or not tok[1:].islower():
        return False
    return tok.casefold() in DE_WOERTER_GUARD


def ist_flexion(tok_cf: str, dcf: str) -> bool:
    """Korrektes deutsches Flexions-/Form-Verhältnis (kein Tippfehler):
    Suffix (Giftstachel+n, Grandiras+'), Bindestrich am Zeilenende
    ("Dürre-"), Bindestrich statt Leerzeichen ("Silph-Scope" ~
    "Silph Scope"). Bewusst KEINE Kürzungs-Regel: "Mega-Armreif" ~
    "Mega-Armreife" ist ein echter Befund."""
    if any(tok_cf == dcf + s for s in INFL_SUFFIXE):
        return True
    if tok_cf.endswith("-") and tok_cf[:-1] == dcf:
        return True
    return "-" not in dcf and tok_cf.replace("-", " ") == dcf


def analyse_namens_abgleich(rows, kanon, max_tippfehler_haeufig):
    """Namens-Abgleich: EN-Namen in DE-Text + seltene Fehlreibungen
    offizieller DE-Namen."""
    en2de, de_names, en_set, de_set = kanon

    en_index = build_prefix_index(
        [(en, (de, t, q)) for en, (de, t, q) in en2de.items()])

    # Pass 1: Häufigkeit aller Namen-artigen Tokens in allen DE-Texten
    # (Tippfehler-Filter: seltene Tokens = wahrscheinliche Fehler)
    token_freq = Counter()
    for r in rows:
        for tok in name_tokens(norm(r["de"])):
            token_freq[tok.casefold()] += 1

    # 3-Gramm-Präfilter für Tippfehler: DE-Namen nach 3-Grammen
    # bündeln (edit-1-Varianten teilen sich fast alle 3-Gramme).
    de_grams = {}
    de_gram_idx = defaultdict(set)
    de_payload = {}
    for (de_name, t, q, en_name) in de_names:
        de_payload.setdefault(de_name, (t, q, en_name))
        dcf = de_name.casefold()
        if len(dcf) < 3:
            continue
        grams = frozenset(dcf[i:i + 3] for i in range(len(dcf) - 2))
        de_grams.setdefault(de_name, grams)
        for g in grams:
            de_gram_idx[g].add(de_name)

    findings = []
    for r in rows:
        de = norm(r["de"])
        de_cf = de.casefold()
        # nicht übersetzte Zeile (EN == DE) -> Platzhalter,
        # kein Namensbefund
        if de_cf == norm(r["en"]).casefold():
            continue

        # (a) EN-Namen in DE-Text
        for en_name, (de_name, t, q) in match_names(de, de_cf, en_index):
            if en_name.casefold() == de_name.casefold():
                continue  # identischer Name (z. B. Mew)
            if en_name.casefold() in EN_COGNATE:
                continue  # deutsches Kognat ("Pass gut auf!"), kein Befund
            if en_name.casefold() in de_set:
                continue  # EN-Name ist zugleich offizielles DE-Name
                # (Kollision: EN "Spotlight" ist DE-Name von "Follow
                # Me") -> Vorkommen im DE-Text ist korrekt, kein Befund
            de_rx = re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(de_name)
                + r"(?![A-Za-z0-9])")
            if de_rx.search(de):
                continue  # offizielles DE-Namen ist auch da
            findings.append({
                "id": r["id"], "gefunden": en_name, "richtig": de_name,
                "typ": t, "quelle": q, "_art": "en_name_in_de"})

        # (b) seltene Fehlreibung eines offiziellen DE-Namens
        for tok in name_tokens(de):
            tok_cf = tok.casefold()
            if tok_cf in en_set or tok_cf in de_set:
                continue  # offizieller Name (EN oder DE)
            if token_freq[tok_cf] > max_tippfehler_haeufig:
                continue  # häufiges Wort -> eher echtes DE-Wort
            if _is_de_woert(tok):
                continue  # kuratiertes deutsches Wort (Titlecase)
            grams = {tok_cf[i:i + 3] for i in range(len(tok_cf) - 2)}
            if not grams:
                continue
            min_overlap = max(0, len(tok_cf) - 6)
            cands = set()
            for g in grams:
                cands.update(de_gram_idx.get(g, ()))
            for de_name in sorted(cands):
                dcf = de_name.casefold()
                if dcf == tok_cf or abs(len(dcf) - len(tok_cf)) > 1:
                    continue
                if len(de_grams[de_name] & grams) < min_overlap:
                    continue
                if not edit1(dcf, tok_cf):
                    continue
                if ist_flexion(tok_cf, dcf):
                    continue  # korrekte deutsche Flexion, kein Befund
                t, q, _ = de_payload[de_name]
                findings.append({
                    "id": r["id"], "gefunden": tok,
                    "richtig": de_name, "typ": t, "quelle": q,
                    "_art": "fehlreibung"})
                break
    return findings


# --------------------------------------------------------------------------
# Analyse 2: ENGLISCHE RESTE
# --------------------------------------------------------------------------

# Gewollte Lehnwörter: englische Begriffe, die in der DE-Übersetzung
# bewusst in englischer Form stehen (Item, Team, Route, Pokédex, ...).
# Bewusst ENG gefasst: gewöhnliche englische Wörter (door, city,
# mountain, friend, ...) stehen hier NICHT — die wären in DE-Texten
# Übersetzungsreste und sollen gemeldet werden. Achtung: é-Varianten
# müssen EXPLIZIT stehen (casefold streicht keine Akzente): "pokédex"
# und "pokedex" sind verschiedene casefolded Strings.
LEHNWORTER = {
    "item", "items", "team", "teams", "pokemon", "level", "trainer",
    "battle", "pc", "box", "card", "cards", "chip", "info", "menu",
    "boss", "shop", "party", "stadium", "champion", "score", "stat",
    "stats", "status", "radio", "video", "game", "gameboy", "special",
    "super", "mega", "ultra", "prime", "note", "ok", "okay", "hp",
    "xp", "exp", "tv", "type", "ticket", "minute", "gold", "silver",
    "ring", "rings", "boots", "set", "partner", "partners", "crew",
    "event", "events", "phase", "standard", "system", "systems",
    "plan", "plans", "start", "route", "pokedex", "pokédex",
    "pokecenter", "pokécenter", "pokénav", "pokémon",
    # "city": offizielle deutsche Stadtnamen behalten bewusst "City"
    # (z. B. Antisia = "Antisis City", Seaport = "Seaport City" —
    # NAMENSVERZEICHNIS.md) — Issue #39 Korrekturrunde: kein Rest.
    "city",
}

# Deutsche Wörter, die identisch mit Englischen sind (Kognate) — nie
# als "englischer Rest" melden. Relevant erst, wenn das Wort auch in
# der EN-Quelle derselben Zeile steht (z. B. "tag"/"Tag").
# "winter": identisch deutsch (Saison-Label).
# "bring": deutscher Imperativ ("Bring mir das!") ist identisch mit
# dem englischen "bring" -> nicht als Rest melden.
# "all": umgangssprachliches deutsches "all" (= "alle", #39-
# Korrekturrunde); "look": deutscher Lehnwort-Gebrauch ("neuen Look").
# Nebenwirkung: die Zeile mit dem bekannten Daten-Schaden "ür" wird
# dadurch nicht mehr als Rest gemeldet (der Schaden bleibt in den
# Korpus-Daten sichtbar; siehe Issue #39).
GERMAN_STOP = {"tag", "man", "mal", "was", "war", "gen", "winter",
               "bring", "all", "look"}

# Dokumentierte Marken-/Label-Ausnahmen für komplett unübersetzte
# Zeilen (EN == DE): Marken und Projekt-Labels, die bewusst nicht
# übersetzt werden. Bewusst klein gehalten — kein generischer
# Marken-Stoplist.
MARKEN = {"smogon", "unbound"}

# Englische Begriffe mit deutscher Entsprechung (Vorschlag-Spalte).
# Kuratiert, deterministisch; sonst gilt der Default "übersetzen".
EN_DE_VORSCHLAG = {
    "all": "alle",
    "autumn": "Herbst", "fall": "Herbst", "spring": "Frühling",
    "summer": "Sommer", "winter": "Winter",
    "morning": "Morgen", "afternoon": "Nachmittag", "evening": "Abend",
    "night": "Nacht", "today": "heute", "tomorrow": "morgen",
    "yesterday": "gestern", "now": "jetzt", "soon": "bald",
    "again": "wieder", "always": "immer", "never": "nie",
    "here": "hier", "there": "dort", "please": "bitte",
    "hello": "Hallo", "goodbye": "Auf Wiedersehen", "help": "Hilfe",
    "wait": "warten", "look": "schauen", "listen": "zuhören",
    "say": "sagen", "tell": "erzählen", "ask": "fragen",
    "answer": "antworten", "think": "denken", "know": "wissen",
    "open": "öffnen", "close": "schließen", "buy": "kaufen",
    "sell": "verkaufen", "give": "geben", "take": "nehmen",
    "find": "finden", "lose": "verlieren", "win": "gewinnen",
    "fight": "kämpfen", "defend": "verteidigen",
    "map": "Karte", "key": "Schlüssel", "move": "Attacke",
    "moves": "Attacken", "types": "Typen", "money": "Geld",
    "time": "Zeit", "day": "Tag", "week": "Woche", "month": "Monat",
    "year": "Jahr", "hour": "Stunde", "second": "Sekunde",
    "door": "Tür", "window": "Fenster", "road": "Straße",
    "city": "Stadt", "town": "Städtchen", "island": "Insel",
    "mountain": "Berg", "forest": "Wald", "cave": "Höhle",
    "lake": "See", "river": "Fluss", "sea": "Meer",
    "friend": "Freund", "friends": "Freunde", "enemy": "Feind",
    "enemies": "Feinde", "power": "Kraft", "energy": "Energie",
    "speed": "Tempo", "damage": "Schaden", "critical": "kritisch",
    "defense": "Verteidigung",
}


def analyse_en_reste(rows, kanon, glossar_de_names):
    """Englische Reste in DE-Texten (drei enge Regeln, kein
    Wort-für-Wort-Reporting — das wäre Lärm über Lärm):

    (a) Läufe von 2+ AUFENEINANDERFOLGENDEN EN-Wörtern in
        (teilweise) übersetzten Zeilen: jedes Token auch in der
        EN-Quelle derselben Zeile (Alignment), keines in den
        Ausnahmelisten, UND mindestens ein Wort mit kuratierter
        deutscher Entsprechung (EN_DE_VORSCHLAG). Ohne die Map-Regel
        wären Eigenname-Comounds ("Kanto-Region"), Produktbe-
        zeichnungen und Onomatopöien reiner Lärm. Fängt echte Reste
        wie "GIVE ME AWESOME" oder "Win-win".
    (b) Einzelnes KAPITALISIERTES EN-Wort, aber nur mit kuratierter
        deutscher Entsprechung (EN_DE_VORSCHLAG). Kleingeschriebene
        Einzelfälle bleiben unerfasst (dokumentiert: ohne Wörterbuch
        nicht von deutschem Deutsch zu unterscheiden).
    (c) Komplett unübersetzte Zeilen (EN == DE) nur, wenn mind. ein
        Wort in EN_DE_VORSCHLAG (und kein DE-Kognat) steht und kein
        Wort eine dokumentierte Marke ist. Fängt exakt "Autumn"
        (-> "Herbst"); Credits, Namen, Onomatopöien, Labels bleiben
        sauber aussortiert.
    """
    en2de, de_names, en_set, de_set = kanon
    gl_cf = {n.casefold() for n in glossar_de_names}
    stop = (en_set | de_set | gl_cf
            | {w.casefold() for w in LEHNWORTER} | GERMAN_STOP)
    marken = {w.casefold() for w in MARKEN}

    findings = []

    # (a) + (b): teilweise übersetzte Zeilen
    for r in rows:
        de = norm(r["de"])
        en = norm(r["en"])
        if not de or de.casefold() == en.casefold():
            continue  # unübersetzte Zeilen: Regel (c) unten
        en_words = {w.casefold() for w in WORD_RE.findall(en)}
        toks = list(WORD_RE.finditer(de))

        # (a) Läufe von 2+ aufeinanderfolgenden EN-Wörtern
        i = 0
        in_run = set()
        while i < len(toks):
            t = toks[i]
            wcf = t.group(0).casefold()
            if wcf not in en_words or wcf in stop:
                i += 1
                continue
            j = i
            while j + 1 < len(toks):
                ncf = toks[j + 1].group(0).casefold()
                if ncf in en_words and ncf not in stop:
                    j += 1
                else:
                    break
            if j > i:  # Lauf von 2+
                run_words = [toks[k].group(0).casefold()
                             for k in range(i, j + 1)]
                # Mindestens ein kuratiertes Wort muss im Lauf stehen:
                # Läufe ohne solches Wort sind Eigenname-Comounds
                # ("Kanto-Region", "Safari-Zone"), Produktbezeichnungen
                # ("GBA Wireless Adapter") oder Onomatopöien — keine
                # meldepflichtigen Reste.
                if not any(w in EN_DE_VORSCHLAG for w in run_words):
                    i = j + 1
                    continue
                run_end = toks[j].end()
                in_run.update(k.start for k in toks[i:j + 1])
                findings.append({
                    "id": r["id"],
                    "fundstelle": de[max(0, t.start() - 40): run_end + 40],
                    "en_wort": de[t.start():run_end].strip(),
                    "vorschlag": "übersetzen",
                })
            i = j + 1

        # (b) einzelnes kapitalisiertes Wort aus EN_DE_VORSCHLAG
        for t in toks:
            if t.start in in_run:
                continue  # Teil des Laufs, bereits gemeldet
            w = t.group(0)
            wcf = w.casefold()
            if wcf not in en_words or wcf in stop:
                continue
            if wcf not in EN_DE_VORSCHLAG:
                continue
            if not w[0].isupper():
                continue  # nur Kapitalisierung (Eigenname-Charakter)
            findings.append({
                "id": r["id"],
                "fundstelle": de[max(0, t.start() - 40): t.end() + 40],
                "en_wort": w,
                "vorschlag": EN_DE_VORSCHLAG[wcf],
            })

    # (c) komplett unübersetzte Zeilen (EN == DE)
    for r in rows:
        de = norm(r["de"])
        en = norm(r["en"])
        if not de or de.casefold() != en.casefold():
            continue
        words = WORD_RE.findall(en)
        wcf_list = [w.casefold() for w in words]
        if any(w in marken for w in wcf_list):
            continue  # Marken-/Label-Zeile, bewusst unübersetzt
        map_words = [w for w in wcf_list
                     if w in EN_DE_VORSCHLAG and w not in GERMAN_STOP]
        if not map_words:
            continue
        findings.append({
            "id": r["id"],
            "fundstelle": "ganze Zeile (unübersetzt)",
            "en_wort": en[:80],
            "vorschlag": "; ".join(EN_DE_VORSCHLAG[w] for w in map_words[:3]),
        })
    return findings


# --------------------------------------------------------------------------
# Analyse 3: ORTSNAMEN-EINHEITLICHKEIT
# --------------------------------------------------------------------------

def analyse_ortsnamen(rows, orte, max_tippfehler_haeufig):
    """Abweichungen bei Ortsnamen aus dem Namensverzeichnis.

    (1) en_form: die EN-Form eines Orts steht im DE-Text, die
        DE-Form nicht.
    (2) fehlreibung: seltene Fehlreibung (edit-1) der DE-Form.
    """
    findings = []
    if not orte:
        return findings

    # Token-Häufigkeit für Tippfehler-Filter
    token_freq = Counter()
    for r in rows:
        for tok in name_tokens(norm(r["de"])):
            token_freq[tok.casefold()] += 1

    # Regexes einmal vordefinieren (108 Orte x 2)
    en_re = {}
    de_re = {}
    for o_de, o_en, art in orte:
        if o_en:
            en_re[o_en] = (o_de, re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(o_en) + r"(?![A-Za-z0-9])"))
        de_re[o_de] = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(o_de) + r"(?![A-Za-z0-9])")
    de_cf_list = [(o_de, o_de.casefold()) for (o_de, o_en, art) in orte]

    for r in rows:
        de = norm(r["de"])
        if de.casefold() == norm(r["en"]).casefold():
            continue  # unübersetzte Zeile -> kein Ortsbefund
        # (1) EN-Form statt DE-Form
        for o_en, (o_de, rx) in en_re.items():
            if not rx.search(de):
                continue
            if de_re[o_de].search(de):
                continue  # DE-Form ist auch da -> kein Befund
            findings.append({
                "id": r["id"], "erwartet_de": o_de,
                "gefunden": o_en, "typ": "en_form",
                "quelle": "NAMENSVERZEICHNIS (Orte)"})
        # (2) seltene Fehlreibung der DE-Form (nur 108 Namen ->
        # Brute-Force mit edit-1)
        for tok in name_tokens(de):
            tok_cf = tok.casefold()
            if token_freq[tok_cf] > max_tippfehler_haeufig:
                continue
            if _is_de_woert(tok):
                continue  # kuratiertes deutsches Wort (Titlecase)
            for o_de, o_de_cf in de_cf_list:
                if o_de_cf == tok_cf:
                    continue
                if abs(len(o_de_cf) - len(tok_cf)) > 1:
                    continue
                if not edit1(o_de_cf, tok_cf):
                    continue
                if ist_flexion(tok_cf, o_de_cf):
                    continue  # korrekte deutsche Flexion, kein Befund
                findings.append({
                    "id": r["id"], "erwartet_de": o_de,
                    "gefunden": tok, "typ": "fehlreibung",
                    "quelle": "NAMENSVERZEICHNIS (Orte)"})
    return findings


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------

def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def kalibrier(rows, kanon, glossar_de, max_tippfehler_haeufig, orte=None):
    """Diagnosen für die Schwellen-Anpassung (stdout, keine Dateien):
    druckt die Befunde aller drei Analysen zur manuellen Prüfung."""
    print("=== (1) NAMENS-ABGLEICH ===")
    f = analyse_namens_abgleich(rows, kanon, max_tippfehler_haeufig)
    c = Counter((x["gefunden"], x["richtig"], x["typ"]) for x in f)
    n_en = sum(1 for x in f if x["_art"] == "en_name_in_de")
    print(f"{len(f)} Befunde ({n_en} EN-Namen, {len(f) - n_en} "
          f"Tippfehler):")
    for x in sorted(f, key=lambda x: (x["_art"], x["gefunden"])):
        print(f'  [{x["id"]}] {x["gefunden"]!r} -> {x["richtig"]!r} '
              f'({x["typ"]}) [{x["_art"]}]')

    print("\n=== (2) ENGLISCHE RESTE ===")
    f2 = analyse_en_reste(rows, kanon, glossar_de)
    print(f"{len(f2)} Befunde:")
    for x in f2:
        print(f'  [{x["id"]}] {x["en_wort"]!r} -> {x["vorschlag"]!r} '
              f'| {x["fundstelle"][:70]!r}')

    if orte:
        print("\n=== (3) ORTSNAMEN ===")
        f3 = analyse_ortsnamen(rows, orte, max_tippfehler_haeufig)
        print(f"{len(f3)} Abweichungen:")
        for x in f3:
            print(f'  [{x["id"]}] {x["gefunden"]!r} -> {x["erwartet_de"]!r} '
                  f'({x["typ"]})')


def main():
    p = argparse.ArgumentParser(description="Namens-Analyse (DE-Texte)")
    p.add_argument("--korpus", required=True,
                   help="Korpus-CSV (;-getrennt: id;en;de;kategorie;ort)")
    p.add_argument("--kanon", default=None,
                   help="Kanon-Namensliste-CSV (typ;en;de;quelle)")
    p.add_argument("--glossar", default=None,
                   help="Namensverzeichnis-Markdown (Sektionen "
                        "Figuren/Orte/Trainerklassen/Projektbegriffe)")
    p.add_argument("--out-dir", default="auswertung")
    p.add_argument("--max-tippfehler-haeufig", type=int, default=3,
                   help="Tippfehler nur melden, wenn Token <= N-mal "
                        "vorkommt (Default 3)")
    p.add_argument("--nur-abgleich", action="store_true")
    p.add_argument("--nur-reste", action="store_true")
    p.add_argument("--nur-ortsnamen", action="store_true")
    p.add_argument("--kalibrier", action="store_true",
                   help="Diagnosen für die Schwellen drucken statt CSVs")
    args = p.parse_args()

    only = sum([args.nur_abgleich, args.nur_reste, args.nur_ortsnamen])
    do_abgleich = only == 0 or args.nur_abgleich
    do_reste = only == 0 or args.nur_reste
    do_ort = only == 0 or args.nur_ortsnamen

    rows = load_corpus(args.korpus)
    print(f"→ {len(rows)} Zeilen geladen", file=sys.stderr)

    kanon = None
    if do_abgleich or do_reste:
        if not args.kanon:
            print("⚠ --kanon fehlt; Abgleich/Reste übersprungen",
                  file=sys.stderr)
            do_abgleich = do_reste = False
        else:
            kanon = load_kanon(args.kanon)
            print(f"→ {len(kanon[1])} Kanon-Namen geladen", file=sys.stderr)

    orte = []
    glossar_de = []
    if args.glossar and (do_ort or do_reste):
        orte = load_orte(args.glossar)
        glossar_de = load_glossar_names(args.glossar)
        print(f"→ {len(orte)} Ortsnamen / {len(glossar_de)} "
              "Glossar-DE-Namen geladen", file=sys.stderr)
    elif do_ort:
        print("⚠ --glossar fehlt; Ortsnamen übersprungen", file=sys.stderr)
        do_ort = False

    if args.kalibrier:
        if kanon:
            kalibrier(rows, kanon, glossar_de,
                      args.max_tippfehler_haeufig, orte)
        return 0

    os.makedirs(args.out_dir, exist_ok=True)

    n_abgleich = n_reste = n_ort = 0
    if do_abgleich and kanon:
        f = analyse_namens_abgleich(rows, kanon, args.max_tippfehler_haeufig)
        out = os.path.join(args.out_dir, "namens_abgleich.csv")
        write_csv(out, ["id", "gefunden", "richtig", "typ", "quelle"],
                  [[x["id"], x["gefunden"], x["richtig"], x["typ"],
                    x["quelle"]] for x in f])
        n_en = sum(1 for x in f if x["_art"] == "en_name_in_de")
        print(f"→ {out} ({len(f)} Befunde: {n_en} EN-Namen, "
              f"{len(f) - n_en} Tippfehler)", file=sys.stderr)
        n_abgleich = len(f)

    if do_reste and kanon:
        f = analyse_en_reste(rows, kanon, glossar_de)
        out = os.path.join(args.out_dir, "en_reste.csv")
        write_csv(out, ["id", "fundstelle", "en_wort", "vorschlag"],
                  [[x["id"], x["fundstelle"], x["en_wort"], x["vorschlag"]]
                   for x in f])
        n_row = sum(1 for x in f
                    if x["fundstelle"].startswith("ganze Zeile"))
        print(f"→ {out} ({len(f)} Befunde: {len(f) - n_row} Wörter, "
              f"{n_row} ganze Zeilen)", file=sys.stderr)
        n_reste = len(f)

    if do_ort and orte:
        f = analyse_ortsnamen(rows, orte, args.max_tippfehler_haeufig)
        out = os.path.join(args.out_dir, "ortsnamen.csv")
        write_csv(out, ["id", "erwartet_de", "gefunden", "typ", "quelle"],
                  [[x["id"], x["erwartet_de"], x["gefunden"], x["typ"],
                    x["quelle"]] for x in f])
        n_en = sum(1 for x in f if x["typ"] == "en_form")
        print(f"→ {out} ({len(f)} Abweichungen: {n_en} EN-Form, "
              f"{len(f) - n_en} Tippfehler)", file=sys.stderr)
        n_ort = len(f)

    print("\n=== ZUSAMMENFASSUNG ===", file=sys.stderr)
    print(f"Zeilen: {len(rows)} | Abgleich: {n_abgleich} | Reste: {n_reste} "
          f"| Ortsnamen: {n_ort}", file=sys.stderr)
    print("(Outputs enthalten Spieltext — privat halten)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
