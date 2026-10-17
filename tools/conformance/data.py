"""実行器が共有できる文字列生成と、仕様の値計算。"""

import copy
from datetime import datetime, timezone
import re
import struct


def materialize(case):
    """JSONポインタで指定した空文字列だけを、UTF-8の指定バイト数へ展開する。"""
    result = copy.deepcopy(case)
    targets = set()
    for generator in case.get('generators', []):
        target = generator['target']
        if target in targets:
            raise ValueError(f"生成対象の重複: {target}")
        targets.add(target)
        if not target.startswith(('/fixtures/events/', '/fixtures/snapshots/')):
            raise ValueError(f"生成対象は封筒の属性に限る: {target}")
        character = generator['character']
        width = len(character.encode('utf-8'))
        size = generator['byte_length']
        if size % width:
            raise ValueError(f"生成バイト数が文字幅の倍数でない: {target}")
        parts = [part.replace('~1', '/').replace('~0', '~') for part in target[1:].split('/')]
        node = result
        try:
            for part in parts[:-1]:
                node = node[int(part)] if isinstance(node, list) else node[part]
            key = int(parts[-1]) if isinstance(node, list) else parts[-1]
            if node[key] != '' or not isinstance(node[key], str):
                raise ValueError(f"生成対象が空文字列でない: {target}")
            node[key] = character * (size // width)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError(f"文字列生成の対象が不正: {target}: {error}") from error
    return result


def resolve_pointer(document, pointer):
    """RFC 6901 のポインタが指す位置を (親, キーまたは添字) で返す。存在しない位置は ValueError。"""
    if not pointer.startswith('/'):
        raise ValueError(f"JSON Pointer がペイロードにない位置を指す: {pointer!r}（根のポインタは使えない）")
    tokens = [token.replace('~1', '/').replace('~0', '~') for token in pointer[1:].split('/')]
    container, key = None, None
    node = document
    for token in tokens:
        if isinstance(node, dict) and token in node:
            container, key = node, token
        elif isinstance(node, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(node):
            container, key = node, int(token)
        else:
            raise ValueError(f"JSON Pointer がペイロードにない位置を指す: {pointer!r}")
        node = container[key]
    return container, key


def fnv1a64(value):
    result = 0xcbf29ce484222325
    for byte in value.encode('utf-8'):
        result = ((result ^ byte) * 0x100000001b3) & (2**64 - 1)
    return f'0x{result:016x}'


def epoch_nanoseconds(iso):
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{9})Z", iso)
    if not match:
        raise ValueError(f"UTC・9桁小数秒の ISO 8601 ではない: {iso}")
    seconds = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    delta = seconds - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + int(match[2])


class EnvelopeFormatError(ValueError):
    """Bigtable の封筒として復元できないバイト列（形式の版・長さ・未使用の末尾の違反）。"""


def _pack(fmt, value, what):
    try:
        return struct.pack(fmt, value)
    except struct.error as error:
        raise ValueError(f"封筒の{what}が範囲外: {value}") from error


def _length_prefixed(prefix_format, data, what):
    return _pack(prefix_format, len(data), what + "の長さ") + data


def encode_bigtable_event(aid, seq_nr, occurred_at_ns, manifest, payload):
    """bigtable.md 4章のイベント封筒。すべてビッグエンディアンで、先頭の 0x01 は形式の版。"""
    return (b'\x01' + _length_prefixed('>H', aid.encode('utf-8'), 'aid')
            + _pack('>Q', seq_nr, 'seq_nr') + _pack('>q', occurred_at_ns, 'occurred_at_ns')
            + _length_prefixed('>I', manifest.encode('utf-8'), 'manifest')
            + _length_prefixed('>I', payload, 'payload'))


def encode_bigtable_snapshot(seq_nr, manifest, payload):
    """bigtable.md 4章のスナップショット封筒。"""
    return (b'\x01' + _pack('>Q', seq_nr, 'seq_nr')
            + _length_prefixed('>I', manifest.encode('utf-8'), 'manifest')
            + _length_prefixed('>I', payload, 'payload'))


class _Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        if size > len(self.data) - self.offset:
            raise EnvelopeFormatError("封筒の長さが足りない")
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self, size):
        try:
            return self.take(size).decode('utf-8')
        except UnicodeDecodeError as error:
            raise EnvelopeFormatError("封筒の文字列が UTF-8 でない") from error


def decode_bigtable_envelope(kind, data):
    """封筒を項目へ復元する。形式の版・長さ・未使用の末尾の違反は EnvelopeFormatError。"""
    if kind not in ('event', 'snapshot'):
        raise ValueError(f"封筒の種類が不正: {kind}")
    reader = _Reader(data)
    if reader.unpack('>B') != 1:
        raise EnvelopeFormatError("未知の封筒の形式版")
    result = {}
    if kind == 'event':
        result['aid'] = reader.text(reader.unpack('>H'))
    result['seq_nr'] = reader.unpack('>Q')
    if kind == 'event':
        result['occurred_at_ns'] = reader.unpack('>q')
    result['manifest'] = reader.text(reader.unpack('>I'))
    result['payload'] = reader.take(reader.unpack('>I'))
    if reader.offset != len(data):
        raise EnvelopeFormatError("封筒に未使用の末尾がある")
    return result
