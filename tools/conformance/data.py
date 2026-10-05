"""実行器が共有できる文字列生成と、仕様の値計算。"""

import copy
from datetime import datetime, timezone
import re


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
