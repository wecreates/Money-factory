"""Verify source identity checks independently from upstream execution."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import verify


class SourceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.entries = []
        for order, name in enumerate(verify.REQUESTED_IDS, 1):
            path = self.root / 'integrations/vendor' / name
            path.mkdir(parents=True)
            (path/'.git').write_text('gitdir: fixture')
            self.entries.append(dict(id=name, order=order, path=str(path.relative_to(self.root)),
                revision='a'*40, repository='https://github.com/owner/'+name, runtime_status='unverified'))
        self.registry = self.root/'integrations/repositories.json'
        self.save()

    def save(self):
        self.registry.write_text(json.dumps({'repositories':self.entries, 'media_tools':getattr(self, 'media', [])}))

    def command(self, args, **kwargs):
        name = Path(args[2]).name
        if 'rev-parse' in args: return 'a'*40+'\n'
        if 'remote' in args: return 'https://github.com/owner/'+name+'.git\n'
        if 'status' in args: return ''
        raise AssertionError(args)

    def check(self, command=None):
        with patch.object(verify.subprocess, 'check_output', side_effect=command or self.command), contextlib.redirect_stdout(io.StringIO()):
            verify.verify(self.root)

    def test_clean_pinned_original_order_passes(self):
        self.check()

    def test_reordered_identity_with_unchanged_numbers_rejected(self):
        self.entries[0]['id'], self.entries[1]['id'] = self.entries[1]['id'], self.entries[0]['id']
        self.save()
        with self.assertRaisesRegex(ValueError, 'requested order'): self.check()

    def test_modified_tracked_source_rejected(self):
        def dirty(args, **kwargs):
            return ' M main.py\n' if 'status' in args else self.command(args, **kwargs)
        with self.assertRaisesRegex(ValueError, 'Tracked source modifications'): self.check(dirty)

    def test_additional_media_source_is_verified_without_changing_requested_order(self):
        path = self.root/'integrations/vendor/voicestudio'
        path.mkdir(); (path/'.git').write_text('gitdir: fixture')
        self.media = [dict(id='voicestudio', path=str(path.relative_to(self.root)),
            revision='a'*40, repository='https://github.com/owner/voicestudio', runtime_status='unverified')]
        self.save(); self.check()
        def dirty_media(args, **kwargs):
            if Path(args[2]).name == 'voicestudio' and 'status' in args: return ' M server.py'
            return self.command(args, **kwargs)
        with self.assertRaisesRegex(ValueError, 'voicestudio'): self.check(dirty_media)

    def test_wrong_origin_or_revision_rejected(self):
        for command_name in ('rev-parse', 'remote'):
            def altered(args, **kwargs):
                return 'wrong\n' if command_name in args else self.command(args, **kwargs)
            with self.subTest(command=command_name), self.assertRaisesRegex(ValueError, 'mismatch'): self.check(altered)


if __name__ == '__main__': unittest.main()
