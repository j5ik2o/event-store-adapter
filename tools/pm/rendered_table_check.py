#!/usr/bin/env python3
"""Check ADR0009's declared peer cell in saved HTML; never fetch or render input."""
import argparse
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path


@dataclass
class Cell:
    text: str = ''
    codes: list = field(default_factory=list)


@dataclass(frozen=True)
class Contract:
    headers: list
    rows: int
    columns: int
    row: int
    column: int
    label: str
    expression: str


def contract_from_json(data):
    if not isinstance(data, dict) or set(data) != set(Contract.__annotations__):
        raise ValueError('invalid contract fields')
    for key in ('rows', 'columns', 'row', 'column'):
        if type(data[key]) is not int or data[key] < 0:
            raise ValueError('contract coordinates must be nonnegative integers')
    if (data['rows'] < 2 or data['columns'] < 2
            or not 0 < data['row'] < data['rows']
            or not 0 < data['column'] < data['columns']):
        raise ValueError('contract coordinate outside declared shape')
    if (not isinstance(data['headers'], list)
            or len(data['headers']) != data['columns']
            or any(not isinstance(s, str) or not s.strip() for s in data['headers'])):
        raise ValueError('contract needs a complete header')
    for key in ('label', 'expression'):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError('empty contract text')
    return Contract(**data)


class Tables(HTMLParser):
    """Read explicit table rows/cells and code text from a GFM HTML fragment."""
    void = {'br', 'hr', 'img', 'wbr', 'input', 'source', 'area', 'base',
            'col', 'embed', 'link', 'meta', 'param', 'track'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []
        self.table = None
        self.row = None
        self.cell = None
        self.code = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.table is not None:
                raise ValueError('nested table unsupported')
            self.table = []
        if self.table is None:
            if tag in {'tr', 'td', 'th'}:
                raise ValueError('table content outside table')
            return
        if any(k in {'hidden', 'style', 'aria-hidden', 'rowspan', 'colspan'} for k, _ in attrs):
            raise ValueError('hidden, styled, or spanning table content unsupported')
        if tag in {'script', 'style', 'template'}:
            raise ValueError('non-text table content unsupported')
        parent = self.stack[-1] if self.stack else None
        if tag in {'thead', 'tbody', 'tfoot'} and parent != 'table':
            raise ValueError('invalid table section')
        if tag == 'tr':
            if parent not in {'table', 'thead', 'tbody', 'tfoot'} or self.row is not None:
                raise ValueError('invalid row')
            self.row = []
        if tag in {'td', 'th'}:
            if parent != 'tr' or self.cell is not None:
                raise ValueError('invalid cell')
            self.cell = Cell()
        if tag == 'code' and self.cell is not None:
            if self.code is not None:
                raise ValueError('nested code unsupported')
            self.code = ''
        if tag == 'br' and self.cell is not None:
            self.cell.text += ' '
            if self.code is not None:
                self.code += ' '
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.table is None:
            return
        if not self.stack or self.stack[-1] != tag:
            raise ValueError('unbalanced table markup')
        self.stack.pop()
        if tag == 'code' and self.code is not None:
            self.cell.codes.append(self.code)
            self.code = None
        if tag in {'td', 'th'}:
            self.row.append(self.cell)
            self.cell = None
        if tag == 'tr':
            self.table.append(self.row)
            self.row = None
        if tag == 'table':
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.text += data
            if self.code is not None:
                self.code += data
        elif self.table is not None and data.strip():
            raise ValueError('text outside table cell')

    def finish(self, html):
        self.feed(html)
        self.close()
        if self.table is not None or self.stack:
            raise ValueError('unclosed table')
        return self.tables


def normalized(text):
    return ' '.join(text.split())


def check(html, contract):
    tables = Tables().finish(html)
    candidates = [t for t in tables if t and
                  [normalized(c.text) for c in t[0]] == contract.headers]
    if len(candidates) != 1:
        return ['expected one declared table, found %d' % len(candidates)]
    table = candidates[0]
    errors = []
    if len(table) != contract.rows:
        errors.append('expected %d rows, found %d' % (contract.rows, len(table)))
    for index, row in enumerate(table):
        if len(row) != contract.columns:
            errors.append('row %d: expected %d cells, found %d' %
                          (index, contract.columns, len(row)))
    labels = [i for i, row in enumerate(table)
              if row and normalized(row[0].text) == contract.label]
    if labels != [contract.row]:
        errors.append('expected unique row label at row %d, found %s' % (contract.row, labels))
    if contract.row >= len(table) or contract.column >= len(table[contract.row]):
        errors.append('declared cell missing')
    else:
        codes = table[contract.row][contract.column].codes
        if codes.count(contract.expression) != 1:
            errors.append('declared cell needs exactly one complete code expression: ' + contract.expression)
    return errors


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, default=Path(__file__).with_name('rendered_table_examples.json'))
    parser.add_argument('--language', required=True, choices=('en', 'ja'))
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--html', type=Path)
    inputs.add_argument('--example', choices=('positive', 'negative'))
    args = parser.parse_args()
    try:
        data = json.loads(args.contract.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        contract = contract_from_json(data['contracts'][args.language])
        html = (args.html.read_text(encoding='utf-8') if args.html else
                data['examples'][args.language][args.example])
        errors = check(html, contract)
        result, code = ('FAIL', 1) if errors else ('PASS', 0)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        result, code, errors = 'UNKNOWN', 2, [str(exc)]
    print(json.dumps(dict(result=result, language=args.language, details=errors,
                          scope='declared table shape and peer code cell only'), ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
