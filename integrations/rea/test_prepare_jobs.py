import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_jobs', Path(__file__).with_name('prepare_jobs.py'))
prepare_jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_jobs)


class PrepareJobsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'integrations/jobs/rea-fixtures').mkdir(parents=True)
        (self.root/'integrations/jobs/rea-fixtures/native.c').write_text('int main(void){return 0;}\n')
        (self.root/'integrations/pod').mkdir()
        for name in prepare_jobs.PROJECT_FILES:
            (self.root/'integrations/pod'/name).write_text('export const owned = true;\n')

    def test_project_is_exact_current_source_and_repeatable(self):
        first = prepare_jobs.prepare('rea-project.job.json', self.root)
        self.assertEqual(len(first), 2)
        for path in first:
            self.assertEqual(path.read_bytes(), (self.root/'integrations/pod'/path.name).read_bytes())
        self.assertEqual(prepare_jobs.prepare('rea-project.job.json', self.root), first)
        (first[0].parent/'unexpected.js').write_text('stale')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            prepare_jobs.prepare('rea-project.job.json', self.root)

    @unittest.skipUnless(shutil.which('gcc'), 'gcc unavailable')
    def test_real_compiler_produces_repeatable_native_binary(self):
        path, = prepare_jobs.prepare('rea-native.job.json', self.root)
        data = path.read_bytes()
        self.assertEqual(data[:4], b'\x7fELF')
        prepare_jobs.prepare('rea-native.job.json', self.root)
        self.assertEqual(path.read_bytes(), data)

    def test_symlink_destination_never_overwritten(self):
        outside = self.root/'outside'; outside.write_text('keep')
        (self.root/'integrations/jobs/rea-fixtures/native.bin').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            prepare_jobs.prepare('rea-native.job.json', self.root)
        self.assertEqual(outside.read_text(), 'keep')

    def test_other_jobs_do_not_generate_or_execute(self):
        self.assertEqual(prepare_jobs.prepare('amex-vs-chase-audit.job.json', self.root), [])
        self.assertFalse((self.root/'integrations/jobs/rea-project').exists())


if __name__ == '__main__': unittest.main()
