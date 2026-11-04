"""Exercise the real backup CLIs against isolated SQLite/document fixtures."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

from django.conf import settings
from django.test import SimpleTestCase


class BackupRestoreTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cfb-backup-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'source'
        self.pdf = self.data / 'private/documents/fixture.pdf'
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b'%PDF-fixture-persistent')
        with sqlite3.connect(self.data / 'cfb.sqlite3') as connection:
            connection.executescript(
                "CREATE TABLE core_document(file TEXT); "
                "INSERT INTO core_document VALUES('documents/fixture.pdf'); "
                "CREATE TABLE example(value TEXT); "
                "INSERT INTO example VALUES('persistente');"
            )
        self.archive = self.root / 'backup.zip'
        self.target = self.root / 'restored'

    def run_cli(self, script, *args, success=True):
        result = subprocess.run(
            [sys.executable, str(settings.BASE_DIR / 'scripts' / script), *map(str, args)],
            capture_output=True, text=True, timeout=30,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def backup(self, **kwargs):
        return self.run_cli(
            'backup.py', '--data-dir', self.data, '--output', self.archive,
            '--maintenance-confirmed', **kwargs,
        )

    def restore(self, archive=None, **kwargs):
        return self.run_cli('restore.py', archive or self.archive, '--data-dir', self.target, **kwargs)

    def test_requires_stopped_writers_confirmation(self):
        result = self.run_cli('backup.py', '--data-dir', self.data, '--output', self.archive, success=False)
        self.assertIn('maintenance-confirmed', result.stderr)
        self.assertFalse(self.archive.exists())

    def test_backup_contains_manifest_and_private_files_but_no_secrets(self):
        (self.data / '.development-key').write_text('test-only-excluded-key')
        self.backup()
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertEqual(set(bundle.namelist()), {'manifest.json', 'cfb.sqlite3', 'private/documents/fixture.pdf'})
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(manifest['version'], 1)
            for name, metadata in manifest['files'].items():
                content = bundle.read(name)
                self.assertEqual(metadata['size'], len(content))
                self.assertEqual(metadata['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)

    def test_existing_backup_is_preserved(self):
        self.backup()
        previous = self.archive.read_bytes()
        self.backup(success=False)
        self.assertEqual(self.archive.read_bytes(), previous)

    def test_roundtrip_preserves_database_and_document(self):
        self.backup()
        self.restore()
        self.assertEqual((self.target / 'private/documents/fixture.pdf').read_bytes(), self.pdf.read_bytes())
        with sqlite3.connect(self.target / 'cfb.sqlite3') as connection:
            self.assertEqual(connection.execute('SELECT value FROM example').fetchone(), ('persistente',))
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertEqual((self.target / 'cfb.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_existing_restore_directory_is_preserved(self):
        self.backup()
        self.target.mkdir()
        marker = self.target / 'user-file'
        marker.write_text('preservar')
        self.restore(success=False)
        self.assertEqual(marker.read_text(), 'preservar')
        self.assertEqual(list(self.target.iterdir()), [marker])

    def test_uncompressed_size_limit(self):
        self.backup()
        self.run_cli('restore.py', self.archive, '--data-dir', self.target, '--max-bytes', '10', success=False)
        self.assertFalse(self.target.exists())

    def test_corrupted_document_checksum_is_rejected(self):
        self.backup()
        corrupt = self.root / 'corrupt.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(corrupt, 'w') as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename == 'private/documents/fixture.pdf':
                    # Same size: ensure hash verification, not just length, rejects it.
                    content = bytes([content[0] ^ 1]) + content[1:]
                target.writestr(info, content)
        result = self.restore(corrupt, success=False)
        self.assertIn('SHA-256', result.stderr)
        self.assertFalse(self.target.exists())

    def test_path_traversal_is_rejected_even_with_matching_manifest(self):
        self.backup()
        malicious = self.root / 'traversal.zip'
        name = 'private/../../escape'
        content = b'escape-attempt'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(malicious, 'w') as target:
            manifest = json.loads(source.read('manifest.json'))
            for info in source.infolist():
                if info.filename != 'manifest.json':
                    target.writestr(info, source.read(info.filename))
            manifest['files'][name] = {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
            target.writestr(name, content)
            target.writestr('manifest.json', json.dumps(manifest))
        self.restore(malicious, success=False)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_backup_rejects_missing_referenced_document(self):
        self.pdf.unlink()
        self.backup(success=False)
        self.assertFalse(self.archive.exists())
