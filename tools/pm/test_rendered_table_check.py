"""Exercise the offline CLI using observable exit codes and JSON results."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CLI = HERE / 'rendered_table_check.py'
DATA = json.loads((HERE / 'rendered_table_examples.json').read_text(encoding='utf-8'))


class RenderedTableCheckTest(unittest.TestCase):
    def invoke(self, html, expected, data=None, language='en'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'input.html').write_text(html, encoding='utf-8')
            (root / 'contract.json').write_text(json.dumps(data or DATA), encoding='utf-8')
            result = subprocess.run([sys.executable, str(CLI), '--language', language,
                                     '--contract', str(root / 'contract.json'),
                                     '--html', str(root / 'input.html')], capture_output=True, text=True)
        self.assertEqual(result.returncode, {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 2}[expected], result.stderr + result.stdout)
        self.assertEqual(result.stderr, '')
        output = json.loads(result.stdout)
        self.assertEqual(output['result'], expected)
        if expected != 'PASS':
            self.assertTrue(output['details'])
        return output

    def positive(self):
        return DATA['examples']['en']['positive']

    def test_both_languages_and_examples(self):
        for language in ('en', 'ja'):
            for example, expected in [('positive', 'PASS'), ('negative', 'FAIL')]:
                with self.subTest(language=language, example=example):
                    self.invoke(DATA['examples'][language][example], expected, language=language)
                    result = subprocess.run([sys.executable, str(CLI), '--language', language,
                                             '--example', example], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0 if expected == 'PASS' else 1)
                    self.assertEqual(json.loads(result.stdout)['result'], expected)

    def test_entities_and_inline_markup_preserve_semantic_text(self):
        self.invoke(self.positive().replace('||', '&#124;&#124;').replace('^9.0.0', '<span>^9.0.0</span>'), 'PASS')

    def test_truncated_or_changed_or_extended_expression(self):
        for text in ('^8.7.1', '^8.7.1 || ^9.1.0', '^8.7.1 || ^9.0.0 || ^10.0.0', ''):
            with self.subTest(text=text):
                self.invoke(self.positive().replace('^8.7.1 || ^9.0.0', text), 'FAIL')

    def test_raw_markdown_is_not_rendered_evidence(self):
        self.invoke('| JS | `^8.7.1 || ^9.0.0` |', 'FAIL')

    def test_expression_elsewhere_does_not_satisfy_cell(self):
        code = '<code>^8.7.1 || ^9.0.0</code>'
        html = self.positive().replace(code, 'missing')
        self.invoke(html + code, 'FAIL')
        self.invoke(html.replace('SDK 6.127.0', code), 'FAIL')
        self.invoke(html.replace('</a>', '</a>' + code), 'FAIL')

    def test_cell_and_row_count_mutations(self):
        for html in (self.positive().replace('</tr>', '<td>extra</td></tr>', 1),
                     self.positive().replace('<td>SDK 6.127.0</td>', '', 1),
                     self.positive().replace('</tbody>', '<tr><td>x</td><td>y</td></tr></tbody>'),
                     self.positive().replace('<tr><td>Java main</td><td>SDK 6.127.0</td></tr>', '')):
            with self.subTest(html=html):
                self.invoke(html, 'FAIL')

    def test_duplicate_table_label_or_expression(self):
        self.invoke(self.positive() * 2, 'FAIL')
        label = DATA['contracts']['en']['label']
        self.invoke(self.positive().replace('Java main', label), 'FAIL')
        self.invoke(self.positive().replace('</code>', '</code><code>^8.7.1 || ^9.0.0</code>'), 'FAIL')

    def test_moved_row_or_missing_table(self):
        self.invoke(self.positive().replace('Java main', 'TEMP').replace(DATA['contracts']['en']['label'], 'Java main').replace('TEMP', DATA['contracts']['en']['label']), 'FAIL')
        self.invoke('', 'FAIL')
        self.invoke(self.positive().replace('Snapshot', 'Other'), 'FAIL')

    def test_unrelated_table_does_not_expand_scope(self):
        self.invoke('<table><tr><td>unrelated</td></tr></table>' + self.positive(), 'PASS')

    def test_unsupported_or_unbalanced_table_is_unknown(self):
        for html in (self.positive().replace('<td>', '<td colspan="2">', 1),
                     self.positive().replace('<code>', '<code hidden>'),
                     self.positive().replace('<code>', '<code style="display:none">'),
                     self.positive().replace('</table>', ''),
                     self.positive().replace('</td>', '</th>', 1),
                     self.positive().replace('<code>', '<table><code>')):
            with self.subTest(html=html):
                self.invoke(html, 'UNKNOWN')

    def test_invalid_contract_never_passes(self):
        for key, value in [('row', 4), ('column', 2), ('row', True),
                           ('expression', ''), ('headers', []), ('rows', -1)]:
            data = copy.deepcopy(DATA)
            data['contracts']['en'][key] = value
            with self.subTest(key=key, value=value):
                self.invoke(self.positive(), 'UNKNOWN', data=data)

    def test_missing_file_is_unknown(self):
        result = subprocess.run([sys.executable, str(CLI), '--language', 'en', '--html',
                                 '/nonexistent/rendered-table-input.html'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['result'], 'UNKNOWN')

    def test_marked_declaration_respects_runtime_parser_boundary(self):
        declaration = '<![foo]>'
        try:
            HTMLParser().feed(declaration)
        except (NotImplementedError, AssertionError):
            expected = ('UNKNOWN', 'UNKNOWN')
        else:
            expected = ('FAIL', 'PASS')
        self.invoke(declaration, expected[0])
        self.invoke(declaration + self.positive(), expected[1])

    def test_parser_failures_return_unknown_json(self):
        for error in ('NotImplementedError', 'AssertionError'):
            program = ('import html.parser, runpy, sys\n'
                       'def unavailable(*args): raise ' + error + '("parser unavailable")\n'
                       'html.parser.HTMLParser.feed = unavailable\n'
                       'sys.argv = [sys.argv[1], "--language", "en", "--example", "positive"]\n'
                       'runpy.run_path(sys.argv[0], run_name="__main__")\n')
            run = subprocess.run([sys.executable, '-c', program, str(CLI)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertEqual(run.stderr, '')
            self.assertEqual(json.loads(run.stdout)['result'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
