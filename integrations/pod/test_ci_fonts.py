import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ci_fonts', ROOT / 'ci_fonts.py')
fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fonts)


class Face:
    def __init__(self, family): self.family = family
    def getname(self): return self.family, 'fixture'
    def getmask(self, text): return self
    def getbbox(self): return (0, 0, 64, 16)


class FontGateTests(unittest.TestCase):
    def test_every_exact_face_is_opened_and_rendered(self):
        expected = {str(fonts.ROOT / n): f for f, names in fonts.FACES.items() for n in names}
        seen = []
        def load(name, size):
            self.assertEqual(size, 16)
            seen.append(name)
            return Face(expected[name])
        self.assertTrue(fonts.fonts_ready(load))
        self.assertEqual(set(seen), set(expected))
        self.assertEqual(len(seen), 12)

    def test_missing_or_unreadable_face_blocks(self):
        def missing(*args): raise OSError('fixture')
        self.assertFalse(fonts.fonts_ready(missing))

    def test_wrong_family_blocks_fallback(self):
        self.assertFalse(fonts.fonts_ready(lambda *args: Face('Other')))

    def test_non_rendering_font_blocks(self):
        class Empty(Face):
            def getbbox(self): return (0, 0, 0, 0)
        self.assertFalse(fonts.fonts_ready(lambda *args: Empty('DejaVu Sans')))

    def run_shell(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, count = root / 'calls', root / 'count'
            timeout = shutil.which('timeout')
            self.assertIsNotNone(timeout)
            scripts = {
                'python': '#!/bin/bash\necho font >> "$LOG"\n'
                          'if [[ "$MODE" == existing ]]; then exit 0; fi\n'
                          'if [[ -f "$COUNT" && "$MODE" != corrupt ]]; then exit 0; fi\n'
                          'touch "$COUNT"\nexit 1\n',
                'sudo': '#!/bin/bash\nexec "$@"\n',
                'apt-get': '#!/bin/bash\necho "$*" >> "$LOG"\n'
                           'if [[ "$MODE" == fail ]]; then exit 100; fi\n'
                           'if [[ "$MODE" == stall ]]; then sleep 10; fi\n',
                'timeout': '#!/bin/bash\n'
                           'test "$1" = --signal=TERM && test "$2" = --kill-after=5s && test "$3" = 120s || exit 97\n'
                           'shift 3\nexec ' + timeout + ' --signal=TERM --kill-after=1s 0.5s "$@"\n',
            }
            for name, content in scripts.items():
                (root / name).write_text(content)
                (root / name).chmod(0o700)
            result = subprocess.run(['bash', str(ROOT / 'ci_fonts.sh')],
                env={**os.environ, 'PATH': str(root) + ':' + os.defpath,
                     'LOG': str(log), 'COUNT': str(count), 'MODE': mode},
                capture_output=True, text=True, timeout=3)
            return result.returncode, log.read_text().splitlines()

    def test_verified_existing_fonts_do_not_use_package_manager(self):
        self.assertEqual(self.run_shell('existing'), (0, ['font']))

    def test_missing_fonts_install_then_reverify(self):
        self.assertEqual(self.run_shell('missing'),
                         (0, ['font', 'update', 'install -y fonts-dejavu-core', 'font']))

    def test_package_failure_is_not_ignored(self):
        self.assertEqual(self.run_shell('fail'), (100, ['font', 'update']))

    def test_stalled_package_update_expires(self):
        self.assertEqual(self.run_shell('stall'), (124, ['font', 'update']))

    def test_failed_post_install_validation_blocks(self):
        self.assertEqual(self.run_shell('corrupt'),
                         (1, ['font', 'update', 'install -y fonts-dejavu-core', 'font']))


if __name__ == '__main__': unittest.main()
