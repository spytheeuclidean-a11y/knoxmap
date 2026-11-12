"""Write lang/english.txt: every line of the window, ready to be translated.

    python tools/make_lang_template.py            # add what is new, keep the rest
    python tools/make_lang_template.py --check    # exit 1 if the file is behind
    python tools/make_lang_template.py --prune    # drop lines the code no longer says

Anyone can put KnoxMap in their language without touching the code: copy
lang/english.txt to lang/<their language>.txt, translate the right-hand side
of each line, and pick the language at the top of the window. The name of the
file is the name in the menu, so russian.txt appears as "Russian".

The English side is what the window actually says, so this is generated rather
than typed: the text of every element in templates/index.html, its
placeholders and titles, the messages in static/js (quoted and in template
literals, whose `${...}` becomes `{name}`), and the ones web/presets.py and
the runtime add. A line whose translation is left as the English is simply
not translated, which is what an untouched template does.

Regenerating is additive on purpose. A translation is found by its English
side, so deleting a line silently deletes every translation of it - and an
extractor that reads source text by pattern will never see everything a
hand-edited file has. Lines the code no longer mentions are kept and listed;
--prune is the one explicit way to let them go.
"""
from __future__ import annotations

import html as html_mod
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "templates" / "index.html"
SCRIPTS = tuple(
    ROOT / "static" / "js" / name
    for name in ("app.js", "draw.js", "fx.js", "iso_view.js", "shell.js")
)
OUT = ROOT / "lang" / "english.txt"

HEADER = """\
# KnoxMap in your language
#
# Copy this file, name it after the language - russian.txt, deutsch.txt,
# turkce.txt - and translate the right of each "=" only. Leave the left alone:
# that is what KnoxMap says in English, and how it finds your translation.
# Whatever is still in English is shown in English, so a half-finished file
# works. Lines starting with # are notes and are ignored.
#
# Then start KnoxMap and pick the language at the top of the window.
#
# Written by tools/make_lang_template.py from the window itself - run it again
# after a KnoxMap update to pick up anything new. It only ever adds lines: a
# line it cannot find in the code is kept, because deleting it would delete
# every translation of it too.
"""

# Text that is not worth translating: names, symbols and numbers.
SKIP = {"KnoxMap", "discord", "OpenStreetMap", "Leaflet", "×", "→", "?"}
# These preset validation errors come from web/presets.py rather than a page script.
# They are shown in the Saved areas panel just like client-side messages.
PRESET_ERRORS = (
    "This is not a KnoxMap preset version 1.",
    "The preset needs a valid area and scale.",
    "The preset area or scale is outside the map's limits.",
    "The preset outline is not a polygon.",
    "The preset outline falls outside its area.",
    "The preset outline could not be read.",
    "The preset needs map settings.",
)

# Runtime messages use named placeholders; the translator keeps their names.
EXTRA_MESSAGES = (
    'Rotate area',
    'Rotate area (drag to rotate, Shift to snap, or click to turn 45°)',
    'Shape area',
    'Map area',
    'Cells',
    'Tiles',
    'Bitmap',
    'MB',
    'km²',
    'OSM query',
    'OSM queries',
    'OpenStreetMap data source',
    'Online queries',
    'Extract / Live',
    'Regional dump',
    'Overpass server addresses',
    'Fast',
    'Default',
    'Offline',
    'Auto',
    '⚡ Overpass API — Online queries',
    'Downloads the selected area from the servers below. Busy servers get a limited number of retries; downloaded parts are kept. If the servers are unreachable, choose Auto or Geofabrik.',
    '⚙ Auto mode',
    'Reads regional Geofabrik data when pyosmium is installed. The file is downloaded once and cached. Reading reports its current stage and object count. Falls back to Overpass if the extract is unavailable.',
    '📦 Geofabrik — Local data',
    'Downloads and caches a Geofabrik region, then selects objects for your area. Works without Overpass after the download. The first read of a large region takes time; the current stage is shown in the window.',
    'Map data source set to {source}',
    'Only the drawn shape is built:',
    '{area} km²',
    '(bounding box: {area} km², {columns}×{rows} cells). Outside it the land turns back to countryside, with the main roads and rivers running on.',
    'reading the relations',
    'reading the map data',
    'reading the map data: {count} tagged nodes and ways checked',
    'reading the rest of the larger areas',
    'finding the OpenStreetMap extract that covers this place',
    'reading the {region} extract',
    'downloading the {region} extract from Geofabrik, {downloaded} of {total} MB',
    'downloading the {region} extract from Geofabrik, {downloaded} MB',
    'no extract ({reason}) - asking the Overpass servers instead',
    'the Overpass servers are busy — waiting {seconds}s, then trying again ({attempt} of {attempts})',
    'the Overpass servers did not answer — {count} of {total} tiles come from an earlier download and may be out of date',
    'server is resting',
    'expected Overpass JSON, received {details}',
    'invalid Overpass JSON: missing elements list',
    'partial answer — {details}',
    'every Overpass endpoint failed — {details}',
    'the Overpass servers are resting after refusing or failing to answer',
    'the Overpass servers are resting after refusing or failing to answer - asking again in about {seconds}s',
    '"{url}" is not an http(s) server address.',
    'The OpenStreetMap extract could not be used: {reason}',
    'All Overpass endpoints failed: {details}',
    'Lookup failed: {details}',
    'no answer within {seconds}s',
    'The free OpenStreetMap servers are busy or not answering right now. KnoxMap already retried. Wait a few minutes and press Generate again; anything that did download is kept, so the next try is faster. A smaller area also helps.',
    'That area has more map data than the public servers will send in one go. Pick a smaller area and try again.',
    'KnoxMap could not reach the OpenStreetMap servers. Check your internet connection, then try again.',
    '{message} Details: {details}',
    'OSM query failed: {details}',
    'The map would not download. The public Overpass servers are shared and go busy; waiting a few minutes and generating again usually works. {details}',
    '{count} of {total} map tiles would not download. The public Overpass servers are shared and go busy; waiting a few minutes and generating again usually works, and a smaller area always does. {details}',
)

# Anything that is code rather than words: a selector, a path, HTML, a template.
# Braces are deliberately absent: `{area}` is part of the message, and the
# placeholders the runtime fills in are the whole point of these lines.
CODE = re.compile(r"^[#./]|[\[\]<>$`|]|\bhttps?:|^\w+-\w+$")

# One quoted piece of script: '...', "..." or `...`. The brace-free class for
# the first two is what keeps a scan from running across statements; template
# literals may run over lines, which is how the page builds its HTML.
QUOTED = re.compile(
    r"'(?P<single>(?:[^'\\\n]|\\.){6,1000})'"
    r'|"(?P<double>(?:[^"\\\n]|\\.){6,1000})"'
    r"|`(?P<template>(?:[^`\\]|\\.){6,2000})`",
    re.S,
)

# `${takes}` in a template literal is a value: it becomes the {takes} the
# language files match on. An expression with braces of its own is left as it
# is rather than guessed at.
VALUE = re.compile(r"\$\{([^{}]*)\}")
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
# Members that name the operation rather than the value it carries.
METHODS = {"Math", "Number", "String", "Boolean", "Array", "Object", "round",
           "floor", "ceil", "abs", "min", "max", "toFixed", "toString",
           "toLocaleString", "toLowerCase", "toUpperCase",
           "join", "map", "filter", "reduce", "length"}

PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)\}")


def placeholder_name(expression: str) -> str:
    """`takes` for ${takes}, `area` for ${area.toFixed(1)}, `widthM` for ${Math.round(widthM)}."""
    # A literal argument (`toLocaleString("de")`) names no value.
    expression = re.sub(r"'[^']*'|\"[^\"]*\"", "", expression)
    names = [name for name in IDENTIFIER.findall(expression) if name not in METHODS]
    return names[-1] if names else "value"


def as_placeholder(text: str) -> str:
    """A template literal's ${...} written the way the language files say it."""
    return VALUE.sub(lambda hit: "{" + placeholder_name(hit.group(1)) + "}", text)


def is_words(text: str) -> bool:
    """Whether this looks like something a person reads, not code."""
    if len(text) < 3 or CODE.search(text):
        return False
    if not re.search(r"[A-Za-z]{2}", text):
        return False
    # A lone lower-case word or two is a key or a class name, not a message.
    words = text.split()
    return len(words) >= 3 or text[0].isupper() or text[0].isdigit()


def page_strings(path: str) -> list[str]:
    text = open(path, encoding="utf-8").read()
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", text, flags=re.S)
    found = []
    for piece in re.split(r"<[^>]+>", body):
        piece = " ".join(html_mod.unescape(piece).split())
        if "{{" not in piece and is_words(piece):
            found.append(piece)
    # placeholder, title, aria-label and label: the last is how a <option>
    # shows a scale or a cell name without any text of its own.
    for attr in re.findall(r'(?:placeholder|title|aria-label|label)="([^"]+)"', text):
        attr = html_mod.unescape(attr)
        if "{{" not in attr and is_words(attr):
            found.append(attr)
    return found


def script_strings(paths) -> list[str]:
    """Sentences the scripts put on the page.

    Only plain quoted text of a few words: enough to catch the notes, the
    buttons and the settings, without dragging in every css class and key.
    Template literals are read too, with their `${...}` turned into `{name}`,
    because that is how the messages carrying live numbers are written.
    """
    found = []
    for path in paths:
        text = open(path, encoding="utf-8").read()
        for match in QUOTED.finditer(text):
            template = match.group("template")
            piece = template if template is not None else (
                match.group("single") if match.group("single") is not None
                else match.group("double"))
            if piece is None:
                continue
            piece = piece.replace("\\'", "'").replace('\\"', '"')
            if template is not None:
                piece = as_placeholder(piece)
            piece = " ".join(piece.split())
            if is_words(piece) and re.search(r"[A-Za-z]{2,}\s+[A-Za-z]", piece):
                found.append(piece)
    return found


def read_keys(path: Path | None = None) -> list[str]:
    """The English side of every line, as the window reads the file."""
    path = OUT if path is None else path
    if not path.exists():
        return []
    keys = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        english = line.partition("=")[0].strip()
        if english:
            keys.append(english)
    return keys


def skeleton(text: str) -> str:
    """The words around the placeholders, with the names taken out."""
    return PLACEHOLDER.sub("{}", text)


def messages() -> list[str]:
    """Every line the code says, with the wording already in english.txt kept.

    A template literal names its own placeholders (`${Math.round(widthM)}`
    becomes {widthM}); where english.txt already holds the same sentence as
    {w}, the committed key wins, so a rename in the code cannot orphan the
    translation keyed by it.
    """
    found = (page_strings(str(PAGE)) + script_strings(SCRIPTS)
             + list(PRESET_ERRORS) + list(EXTRA_MESSAGES))
    known: dict[str, str] = {}
    for key in read_keys():
        known.setdefault(skeleton(key), key)
    seen: set[str] = set()
    lines: list[str] = []
    for text in found:
        if text in SKIP or "=" in text:
            continue                   # "=" is the separator; skip those
        text = known.get(skeleton(text), text)
        if text not in seen:
            seen.add(text)
            lines.append(text)
    return lines


def template_lines(previous: list[str] | None = None, *, prune: bool = False
                   ) -> tuple[list[str], list[str]]:
    """The lines to write, and the committed ones the code no longer says.

    Without `prune` the second list is kept as well: a generator that reads
    source by pattern must not be able to subtract a translation.
    """
    previous = read_keys() if previous is None else previous
    found = messages()
    said = set(found)
    dropped = [key for key in previous if key not in said]
    lines = found if prune else found + dropped
    return sorted(dict.fromkeys(lines), key=str.lower), dropped


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    prune, check = "--prune" in args, "--check" in args
    previous = read_keys()
    lines, dropped = template_lines(previous, prune=prune)

    if check:
        missing = [line for line in messages() if line not in set(previous)]
        if missing:
            print(f"{len(missing)} line(s) the code says are missing from {OUT}:")
            for line in sorted(missing, key=str.lower)[:20]:
                print(f"  + {line}")
            return 1
        print(f"{OUT} has every line the code says ({len(previous)} lines)")
        return 0

    added = sum(1 for line in lines if line not in set(previous))
    # Keep the file's line endings: it is edited on Windows and on Linux.
    newline = "\r\n" if OUT.exists() and b"\r\n" in OUT.read_bytes() else "\n"
    os.makedirs(OUT.parent, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write(HEADER.replace("\n", newline) + newline)
        fh.write(newline.join(f"{line} = {line}" for line in lines) + newline)

    print(f"wrote {OUT} with {len(lines)} lines ({added} new)")
    if dropped:
        if prune:
            print(f"dropped {len(dropped)} line(s) the code no longer says:")
            for line in dropped:
                print(f"  - {line}")
        else:
            print(f"kept {len(dropped)} line(s) the code no longer says "
                  f"({len(previous)} in the file, {len(lines) - len(previous)} added); "
                  f"--prune drops them:")
            for line in dropped[:10]:
                print(f"  - {line}")
            if len(dropped) > 10:
                print(f"  ... and {len(dropped) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
