import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/db_tools.py'


class BackupValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'backup/restore tool is missing')
        spec = importlib.util.spec_from_file_location('db_tools', SCRIPT)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.manifest = {'format': 1, 'services': {}}
        for service in ('mysql', 'mongodb', 'postgresql', 'redis'):
            self.archive(service)
        self.save()

    def archive(self, service, member='data', kind=tarfile.REGTYPE):
        p = self.folder / (service + '.tar.gz')
        with tarfile.open(p, 'w:gz') as tf:
            info = tarfile.TarInfo(member)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = 2
                tf.addfile(info, io.BytesIO(b'ok'))
            else:
                info.linkname = '/outside'
                tf.addfile(info)
        self.manifest['services'][service] = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'image_id': 'sha256:test'}

    def save(self):
        (self.folder / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_backup(self):
        self.assertEqual(self.tool.validate_backup(self.folder)['format'], 1)

    def test_corruption_is_rejected(self):
        with (self.folder / 'mysql.tar.gz').open('ab') as f:
            f.write(b'corruption')
        with self.assertRaises(ValueError):
            self.tool.validate_backup(self.folder)

    def test_incomplete_backup_is_rejected(self):
        (self.folder / 'redis.tar.gz').unlink()
        with self.assertRaises(ValueError):
            self.tool.validate_backup(self.folder)

    def test_traversal_is_rejected_even_with_valid_checksum(self):
        for member in ('../outside', '/absolute', 'data/../../outside'):
            with self.subTest(member=member):
                self.archive('redis', member)
                self.save()
                with self.assertRaises(ValueError):
                    self.tool.validate_backup(self.folder)

    def test_links_and_devices_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                self.archive('redis', kind=kind)
                self.save()
                with self.assertRaises(ValueError):
                    self.tool.validate_backup(self.folder)

    def test_missing_service_is_rejected(self):
        del self.manifest['services']['redis']
        self.save()
        with self.assertRaises(ValueError):
            self.tool.validate_backup(self.folder)

    def test_restore_requires_explicit_confirmation_before_docker_access(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'restore', str(self.folder)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--confirm', result.stderr)


if __name__ == '__main__':
    unittest.main()
