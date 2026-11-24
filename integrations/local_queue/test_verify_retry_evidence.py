import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from integrations.local_queue.verify_retry_evidence import canonical, verify


PACKET = Path(__file__).with_name('evidence') / 'c12-real-admission-retry-20261124-v2'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RetryEvidenceVerifierTests(unittest.TestCase):
    def copy(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'packet'; shutil.copytree(PACKET, root)
        return root

    def rewrite_manifest_hash(self, root, relative):
        manifest = json.loads((root / 'evidence.json').read_text())
        manifest['artifacts'][relative] = digest(root / relative)
        (root / 'evidence.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')

    def test_closed_real_packet_passes_without_changing_sqlite(self):
        database = PACKET / 'runtime/queue.sqlite3'
        before = digest(database)
        result = verify(PACKET)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['worker_process_exits'], [2, 2])
        self.assertEqual(before, digest(database))
        self.assertFalse((database.parent / 'queue.sqlite3-wal').exists())
        self.assertFalse((database.parent / 'queue.sqlite3-shm').exists())

    def test_extra_or_changed_artifact_is_rejected(self):
        root = self.copy(); (root / 'extra').write_text('unbound')
        with self.assertRaisesRegex(ValueError, 'artifact set'):
            verify(root)
        (root / 'extra').unlink(); (root / 'job.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            verify(root)

    def test_hash_valid_but_false_process_exit_is_rejected(self):
        root = self.copy(); relative = 'process/worker-1.json'
        worker = json.loads((root / relative).read_text()); worker['exit_code'] = 0
        (root / relative).write_text(json.dumps(worker, indent=2, sort_keys=True) + '\n')
        self.rewrite_manifest_hash(root, relative)
        with self.assertRaisesRegex(ValueError, 'Worker command, exit'):
            verify(root)

    def test_hash_valid_but_changed_job_digest_is_rejected(self):
        root = self.copy(); relative = 'job.json'
        job = json.loads((root / relative).read_text()); job['max_attempts'] = 3
        (root / relative).write_text(json.dumps(job, indent=2, sort_keys=True) + '\n')
        self.rewrite_manifest_hash(root, relative)
        manifest = json.loads((root / 'evidence.json').read_text())
        manifest['job_digest'] = hashlib.sha256(canonical(job).encode()).hexdigest()
        (root / 'evidence.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        with self.assertRaisesRegex(ValueError, 'Job limits'):
            verify(root)


if __name__ == '__main__':
    unittest.main()
