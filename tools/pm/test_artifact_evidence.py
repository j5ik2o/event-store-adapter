"""Behavior tests using isolated files and the public CLI."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).with_name('artifact_evidence.py')


class EvidenceCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = self.root / 'task.json'
        self.manifest = self.root / 'manifest.json'
        self.spec = {'task_id': 'fixture-127', 'artifact_root': '.',
                     'first_artifact': 'first.md', 'deadline': '2000-01-01T00:00:00Z',
                     'required_files': [{'path': role + '.txt', 'role': role}
                                        for role in ('script', 'raw', 'log', 'report')]}
        for row in self.spec['required_files']:
            (self.root / row['path']).write_text(row['role'])
        self.save()

    def save(self):
        self.contract.write_text(json.dumps(self.spec))

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertLess(len(result.stdout), 5000)
        return json.loads(result.stdout)

    def generate(self):
        self.cli('generate', self.contract, '--output', self.manifest)

    def test_overdue_then_present_does_not_prove_timeliness(self):
        result = self.cli('progress', self.contract, code=1)
        self.assertEqual(result['observation']['first_state'], 'overdue_missing')
        (self.root / 'first.md').write_text('first')
        result = self.cli('progress', self.contract)
        self.assertEqual(result['observation']['completed_by_deadline'], 'unknown')
        self.generate()
        result = self.cli('verify', self.manifest, '--contract', self.contract)
        self.assertEqual(result['evidence'], 'satisfied_now')
        self.assertEqual(result['historical_completion'], 'unknown')

    def test_pending_and_required_metadata(self):
        self.spec['deadline'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.save()
        self.assertEqual(self.cli('progress', self.contract, code=1)['observation']['first_state'], 'pending_missing')
        for field in ('task_id', 'artifact_root', 'first_artifact', 'deadline', 'required_files'):
            broken = dict(self.spec)
            del broken[field]
            self.contract.write_text(json.dumps(broken))
            self.cli('progress', self.contract, code=2)
        for value in ('', 'tomorrow', '2026-01-01', '2026-01-01T00:00:00'):
            self.spec['deadline'] = value
            self.save()
            self.cli('progress', self.contract, code=2)

    def test_three_wrappers_mixed_paths_and_integrity_only(self):
        self.generate()
        entries = json.loads(self.manifest.read_text())['files']
        entries[0]['path'] = Path(entries[0]['path']).name
        for wrapper in (entries, {'files': entries}, {'artifacts': entries}):
            self.manifest.write_text(json.dumps(wrapper))
            result = self.cli('verify', self.manifest)
            self.assertEqual(result['integrity'], 'matched_now')
            self.assertEqual(result['evidence'], 'not_assessed')

    def test_omitted_evidence_and_absent_first_are_not_satisfied(self):
        self.generate()
        self.assertEqual(self.cli('verify', self.manifest, '--contract', self.contract, code=1)['evidence'], 'incomplete')
        (self.root / 'first.md').write_text('present')
        data = json.loads(self.manifest.read_text())
        data['files'].pop()
        self.manifest.write_text(json.dumps(data))
        self.assertEqual(self.cli('verify', self.manifest, '--contract', self.contract, code=1)['checklist'], 'mismatch')

    def test_changed_missing_directory_and_no_overwrite(self):
        self.generate()
        self.cli('generate', self.contract, '--output', self.manifest, code=2)
        target = self.root / 'script.txt'
        target.write_text('altered')
        self.cli('verify', self.manifest, code=2)
        target.unlink()
        self.cli('verify', self.manifest, code=2)
        target.mkdir()
        self.cli('verify', self.manifest, code=2)

    def test_empty_ambiguous_truncated_invalid_and_duplicate(self):
        row = {'path': 'log.txt', 'bytes': 3, 'sha256': hashlib.sha256(b'log').hexdigest()}
        invalid = [[], {}, {'other': []}, {'files': [], 'artifacts': []},
                   {'files': [row], 'complete': False}, {'files': [row], 'truncated': True},
                   [row, row], [dict(row, bytes=True)], [dict(row, sha256='bad')],
                   [dict(row, path='*.txt')], [dict(row, path='.')], [None]]
        for value in invalid:
            with self.subTest(value=value):
                self.manifest.write_text(json.dumps(value))
                self.cli('verify', self.manifest, code=2)
        self.manifest.write_text('{"files": [], "files": []}')
        self.cli('verify', self.manifest, code=2)

    def test_reconstructed_7259_entry_failure_is_bounded(self):
        row = {'path': 'log.txt', 'bytes': 3, 'sha256': '0' * 64}
        self.manifest.write_text(json.dumps([row] * 7259))
        result = self.cli('verify', self.manifest, code=2)
        self.assertFalse(result['inspection_complete'])
        self.assertIn('limit', result['error'])
        self.manifest.write_text(json.dumps([row] * 257))
        self.assertIn('count limit', self.cli('verify', self.manifest, code=2)['error'])

    def test_generation_rejects_serialized_manifest_over_reader_limit(self):
        if not hasattr(os, 'pathconf') or os.pathconf(self.root, 'PC_PATH_MAX') < 3500:
            self.skipTest('requires filesystem support for long Unicode paths')
        directory = self.root
        for _ in range(10):
            directory /= 'あ' * 75
            directory.mkdir()
        self.contract = directory / 'task.json'
        self.manifest = directory / 'manifest.json'
        self.spec['required_files'] = [
            {'path': f'f{i}.txt', 'role': ('script', 'raw', 'log', 'report')[i % 4]}
            for i in range(256)]
        for row in self.spec['required_files']:
            (directory / row['path']).write_text('x')
        self.save()
        self.assertLess(self.contract.stat().st_size, 1024 * 1024)
        result = self.cli('generate', self.contract, '--output', self.manifest, code=2)
        self.assertFalse(result['inspection_complete'])
        self.assertIn('JSON byte limit', result['error'])
        self.assertFalse(self.manifest.exists())

    def test_generation_rejects_expanded_paths_over_reader_limit(self):
        if not hasattr(os, 'pathconf') or os.pathconf(self.root, 'PC_PATH_MAX') < 3500:
            self.skipTest('requires filesystem support for long Unicode paths')
        directory = self.root
        for _ in range(14):
            directory /= 'あ' * 75
            directory.mkdir()
        self.contract = directory / 'task.json'
        self.manifest = directory / 'manifest.json'
        for row in self.spec['required_files']:
            (directory / row['path']).write_text('x')
        self.save()
        result = self.cli('generate', self.contract, '--output', self.manifest, code=2)
        self.assertFalse(result['inspection_complete'])
        self.assertIn('bounded string', result['error'])
        self.assertFalse(self.manifest.exists())

    def test_file_and_total_byte_limits(self):
        self.generate()
        data = json.loads(self.manifest.read_text())
        data['files'][0]['bytes'] = 16 * 1024 * 1024 + 1
        self.manifest.write_text(json.dumps(data))
        self.cli('verify', self.manifest, code=2)
        self.manifest.write_text(json.dumps([{'path': str(i), 'bytes': 16 * 1024 * 1024,
                                             'sha256': '0' * 64} for i in range(5)]))
        self.cli('verify', self.manifest, code=2)
        with (self.root / 'script.txt').open('wb') as output:
            output.truncate(16 * 1024 * 1024 + 1)
        self.cli('generate', self.contract, '--output', self.root / 'oversize.json', code=2)

    def test_json_limit_and_input_commands_are_not_executed(self):
        self.manifest.write_text(' ' * (1024 * 1024 + 1))
        self.assertIn('JSON byte limit', self.cli('verify', self.manifest, code=2)['error'])
        marker = self.root / 'executed'
        self.spec['command'] = 'touch ' + str(marker)
        self.spec['updatedAt'] = '2099-01-01T00:00:00Z'
        self.spec['git_clean'] = True
        self.save()
        result = self.cli('progress', self.contract, code=1)
        self.assertEqual(result['observation']['first_state'], 'overdue_missing')
        self.assertFalse(marker.exists())

    def test_roles_escape_duplicate_and_self_reference(self):
        for change in ('roles', 'escape', 'duplicate', 'self'):
            spec = json.loads(json.dumps(self.spec))
            if change == 'roles':
                spec['required_files'].pop()
            elif change == 'escape':
                spec['first_artifact'] = '../outside'
            elif change == 'duplicate':
                spec['required_files'].append(spec['required_files'][0])
            else:
                spec['first_artifact'] = 'manifest.json'
            self.contract.write_text(json.dumps(spec))
            self.cli('generate', self.contract, '--output', self.manifest, code=2)


if __name__ == '__main__':
    unittest.main()
