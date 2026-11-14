---
name: ui-strings
description: Use when adding or changing any user-visible text in the KnoxMap web UI (labels, descriptions, hints, button text, title/aria-label/placeholder attributes, messages built in JavaScript) - covers wording and the translation files.
---

# UI text and translations

## Wording

- Plain, generic words about **real-world places**: "a place", "the area", "this
  map". Avoid "your home" or "your street and house number".
- Name places in the UI by where they really are: "in Properties, on the Gameplay
  tab", "under Tools, Zones", "under Edit, Steam libraries".
- Keep the KnoxMap voice: short sentences, say what happens, no jargon such as tag
  names (`highway=residential`) when a word exists ("Street").

## Translations

Text nodes and the `title`, `aria-label` and `placeholder` attributes are translated
at runtime by `static/js/i18n.js` from `lang/*.txt`. Each line reads:

```
English text = Translated text
About {setting} = Acerca de {setting}
```

For every new or changed English string:

1. Add it to `lang/english.txt` (`X = X`). `english.txt` must hold every key. A
   translation file with a key missing from English fails `test_lang_files`.
2. Add a translation to `lang/espanol.txt`, `lang/portugues_brasil.txt` and
   `lang/russian.txt`.
3. When you **rename** an existing string, rename its key in **every** `lang/*.txt`
   that has it, including `lang/turkce.txt`.
4. `tools/make_lang_template.py --check` finds strings in the HTML and plain JS, but
   it **skips text inside JS template literals** (HTML built with backticks). Add
   those by hand.
5. Dynamic parts use `{placeholders}`, matching an existing pattern where one exists
   (`About {setting}`).

## Check

```bash
.venv/bin/python -m unittest tests.test_lang_files tests.test_i18n
node tests/test_i18n_templates.js
.venv/bin/python tools/make_lang_template.py --check
```

Run only these related tests, not the whole suite.
