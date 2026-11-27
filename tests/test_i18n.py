"""Translation placeholders must survive in dictionaries and in the real JS matcher."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tools import make_lang_template
from web.system import _language_strings

ROOT = Path(__file__).resolve().parents[1]


class TranslationTemplates(unittest.TestCase):
    def test_russian_covers_the_template_except_literal_names_and_code(self):
        # Names, shortcuts, example paths and extractor artefacts stay literal.
        literal = {
            '13px system-ui, sans-serif', ';                // the picked room (',
            r'C:\Users\you\Zomboid', r'E: or E:\Games\Steam',
            'File → BMP To TMX → All Cells…', 'File → Generate Lots 8x8 → All Cells…',
            'leaflet-bar leaflet-control lasso-control', 'toast bad problem',
            'Setup.bat', '1:1', 'Discord', 'USGS 3DEP', 'Geofabrik',
            'Ctrl+Shift+Z', 'Overpass API', 'HIFLD', 'Ctrl+Z', 'ESA WorldCover',
        }
        english = {line.partition(' = ')[0].strip()
                   for line in (ROOT / 'lang/english.txt').read_text(encoding='utf-8').splitlines()
                   if '=' in line and not line.startswith('#')}
        russian = _language_strings(ROOT / 'lang/russian.txt')
        self.assertEqual(english - russian.keys(), literal)

    def test_russian_templates_preserve_all_named_values(self):
        translations = _language_strings(ROOT / 'lang/russian.txt')
        self.assertTrue(translations)
        for english, russian in translations.items():
            with self.subTest(english=english):
                self.assertEqual(set(re.findall(r'\{([A-Za-z_]\w*)\}', english)),
                                 set(re.findall(r'\{([A-Za-z_]\w*)\}', russian)))

    def test_editor_room_labels_are_translated_without_changing_room_ids(self):
        from knoxbuild.designer import room_kinds

        translations = _language_strings(ROOT / 'lang/russian.txt')
        for room in room_kinds():
            with self.subTest(room=room['id']):
                self.assertIn(room['label'], translations)
        prison = next(room for room in room_kinds() if room['id'] == 'prisoncells')
        self.assertEqual(translations[prison['label']], 'Тюремные камеры')
        self.assertEqual(translations['Cells'], 'Ячейки')

    def test_regenerating_english_keeps_the_new_messages(self):
        english = {line.partition(' = ')[0].strip()
                   for line in (ROOT / 'lang/english.txt').read_text(encoding='utf-8').splitlines()
                   if '=' in line and not line.startswith('#')}
        russian = _language_strings(ROOT / 'lang/russian.txt')
        for key in make_lang_template.EXTRA_MESSAGES:
            with self.subTest(key=key):
                self.assertIn(key, english)
                self.assertIn(key, russian)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_browser_translation_matcher(self):
        result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/test_i18n_templates.js')],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
