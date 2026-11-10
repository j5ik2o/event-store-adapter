import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).with_name('transcript_index.py')
EXAMPLE = CLI.with_name('transcript_index_example.jsonl')


class TranscriptCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.jsonl'
        self.source.write_bytes(EXAMPLE.read_bytes())

    def run_cli(self, *extra, command='index', live=None, success=True):
        identity = ['--mode', 'fixture', '--source', str(self.source)]
        if live:
            identity = ['--mode', 'live', '--state-db', str(live),
                        '--thread-id', 'synthetic', '--workspace', str(CLI.parents[2])]
        result = subprocess.run([sys.executable, str(CLI), command] + identity + [
            '--start', '1', '--end', '5', '--byte-budget', '4096', '--excerpt-budget', '80',
            '--prior-conclusion', 'old review is not an execution',
            '--new-action', 'this synthetic invocation'] + list(extra), capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b'')
            value = json.loads(result.stdout)
            self.assertEqual(value['output_bytes'], len(result.stdout))
            self.assertLessEqual(len(result.stdout), value['byte_budget'])
            return value
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, b'')
        self.assertIn(b'UNKNOWN/blocked', result.stderr)
        return result

    def write_events(self, events):
        self.source.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events), encoding='utf-8')

    def test_fixture_has_prompts_tool_and_result(self):
        before = self.source.read_bytes()
        value = self.run_cli('--reviewed', '1:3')
        self.assertEqual(value['provenance']['mode'], 'synthetic_fixture')
        self.assertEqual(value['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(value['selected_events'], 5)
        self.assertIn('新規', value['entries'][1]['excerpt'])
        self.assertEqual(value['entries'][2]['excerpt'], 'exec_command')
        self.assertIn('3 passed', value['entries'][3]['excerpt'])
        self.assertTrue(value['entries'][2]['already_reviewed'])
        self.assertFalse(value['entries'][3]['already_reviewed'])
        self.assertFalse(value['prior_conclusion_is_execution_evidence'])
        self.assertEqual(value['review_status'], 'MANUAL_SOURCE_ACQUISITION_REQUIRED')
        self.assertEqual(self.source.read_bytes(), before)

    def test_retrieve_original_event_pointer_and_reject_changed_source(self):
        index = self.run_cli()
        entry = index['entries'][3]
        value = self.run_cli('--start', '4', '--end', '4', '--source-sha256',
                             index['source_sha256'], command='event')
        self.assertEqual(value['entries'][0], entry)
        raw = self.source.read_bytes()[entry['offset']:entry['offset'] + entry['source_bytes']]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['event_sha256'])
        self.source.write_bytes(self.source.read_bytes() + b'{}\n')
        self.run_cli('--start', '4', '--end', '4', '--source-sha256', index['source_sha256'],
                     command='event', success=False)

    def test_unicode_and_giant_event(self):
        text = '界\n' * 2300000
        self.write_events([{'payload': {'type': 'function_call_output', 'output': text}}])
        value = self.run_cli('--end', '1', '--excerpt-budget', '7')
        entry = value['entries'][0]
        self.assertEqual(entry['excerpt'], '界\n界')
        self.assertEqual(value['excerpt_bytes'], 7)
        self.assertEqual(entry['excerpt_omitted_bytes'], len(text.encode()) - 7)
        self.assertTrue(entry['line_truncated'])
        self.assertGreater(value['excerpt_omitted_lines'], 2000000)

    def test_omissions_include_whole_event_bytes(self):
        self.write_events([{'payload': {'type': 'user_message', 'message': 'x' * 500}}] * 30)
        value = self.run_cli('--end', '30', '--byte-budget', '2200', '--excerpt-budget', '500')
        kept = len(value['entries'])
        self.assertGreater(value['omitted_events'], 0)
        self.assertEqual(value['omitted_events'], 30 - kept)
        one_line = len(self.source.read_bytes()) // 30
        self.assertEqual(value['omitted_event_bytes'], (30 - kept) * one_line)
        self.assertEqual(value['excerpt_omitted_bytes'], (30 - kept) * 500)

    def test_invalid_json_duplicate_keys_partial_line_empty_and_outside(self):
        for raw in (b'', b'{}', b'{bad}\n', b'{"x":1,"x":2}\n',
                    b'{"payload":{"x":1,"x":2}}\n', b'{"x":NaN}\n', b'[]\n', b'\xff\n'):
            with self.subTest(raw=raw):
                self.source.write_bytes(raw)
                self.run_cli('--end', '1', success=False)
        self.source.write_bytes(b'{}\n')
        self.run_cli(success=False)
        self.run_cli('--start', '0', success=False)
        self.run_cli('--start', '5', '--end', '1', success=False)

    def test_invalid_event_outside_selected_range_still_blocks(self):
        self.source.write_bytes(b'{}\n{"x":1,"x":2}\n')
        self.run_cli('--end', '1', success=False)

    def test_opaque_content_is_not_decoded(self):
        self.write_events([
            {'payload': {'type': 'function_call', 'name': 'tool', 'arguments': 'SECRET'}},
            {'payload': {'type': 'reasoning', 'encrypted_content': 'SECRET'}},
            {'payload': {'type': 'function_call_output', 'output': {'opaque': 'SECRET'}}},
            {'payload': {'type': 'message', 'role': 'assistant', 'content': [{'text': 'SECRET'}]}},
            {'payload': {'type': 'unknown', 'runtime_args': 'SECRET'}}])
        value = self.run_cli()
        self.assertNotIn('SECRET', json.dumps(value))
        self.assertIn('opaque', value['entries'][0]['visibility'])

    def test_tiny_budget_and_event_without_hash_block(self):
        self.run_cli('--byte-budget', '1', success=False)
        self.run_cli('--excerpt-budget', '-1', success=False)
        self.run_cli(command='event', success=False)

    def test_live_db_identity_and_workspace_checks_read_only(self):
        db = self.root / 'state.sqlite'
        with sqlite3.connect(str(db)) as conn:
            conn.execute('create table threads (id text, rollout_path text)')
            conn.execute('insert into threads values (?,?)', ('synthetic', str(self.source)))
        events = [json.loads(line) for line in EXAMPLE.read_text().splitlines()]
        events[0]['payload']['cwd'] = str(CLI.parents[2])
        self.write_events(events)
        before = db.read_bytes()
        value = self.run_cli(live=db)
        self.assertEqual(value['provenance']['mode'], 'live')
        self.assertEqual(db.read_bytes(), before)
        events[0]['payload']['cwd'] = str(self.root)
        self.write_events(events)
        self.run_cli(live=db, success=False)
        events[0]['payload']['cwd'] = str(CLI.parents[2])
        events[0]['payload']['id'] = 'wrong'
        self.write_events(events)
        self.run_cli(live=db, success=False)
        with sqlite3.connect(str(db)) as conn:
            conn.execute('delete from threads')
        self.run_cli(live=db, success=False)


if __name__ == '__main__':
    unittest.main()
