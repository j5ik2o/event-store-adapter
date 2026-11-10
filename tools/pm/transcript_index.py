"""Manual, byte-bounded pointers into one explicitly selected Codex rollout."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


class Blocked(ValueError):
    pass


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Blocked('duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    def invalid(_):
        raise Blocked('nonfinite JSON number')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise Blocked('event must be an object')
    return value


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def common_dir(path):
    return Path(subprocess.check_output(
        ['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        stderr=subprocess.DEVNULL).decode().strip()).resolve()


def resolve(args):
    if args.mode == 'fixture':
        if not args.source or args.state_db or args.thread_id or args.workspace:
            raise Blocked('fixture requires only --source identity')
        return Path(args.source).resolve(), {'mode': 'synthetic_fixture', 'authenticity': 'not_live'}
    if args.source or not all((args.state_db, args.thread_id, args.workspace)):
        raise Blocked('live requires explicit --state-db --thread-id --workspace')
    db = Path(args.state_db).resolve()
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as connection:
        rows = connection.execute('SELECT rollout_path FROM threads WHERE id=?',
                                  (args.thread_id,)).fetchall()
    if len(rows) != 1:
        raise Blocked('UNKNOWN rollout identity')
    source = Path(rows[0][0]).resolve()
    with source.open('rb') as stream:
        first = stream.readline()
        meta = parse(first)
    payload = meta.get('payload', {})
    if (meta.get('type') != 'session_meta' or not isinstance(payload, dict)
            or payload.get('id') != args.thread_id):
        raise Blocked('UNKNOWN session identity')
    cwd = Path(payload['cwd']).resolve()
    workspace = Path(args.workspace).resolve()
    # Matching common directories admits this repository's real worktrees only.
    top = Path(subprocess.check_output(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                                       stderr=subprocess.DEVNULL).decode().strip()).resolve()
    if cwd != top or common_dir(cwd) != common_dir(workspace):
        raise Blocked('UNKNOWN workspace membership')
    return source, {'mode': 'live', 'thread_id': args.thread_id,
                    'state_db': str(db), 'session_cwd': str(cwd),
                    'session_meta_sha256': hashlib.sha256(first).hexdigest()}


def excerpt(event):
    payload = event.get('payload', {})
    if not isinstance(payload, dict):
        return 'unknown', '', 'opaque'
    kind = payload.get('type', event.get('type', 'unknown'))
    if kind == 'message' and payload.get('role') == 'user':
        content = payload.get('content', [])
        if isinstance(content, list):
            text = '\n'.join(item['text'] for item in content
                             if isinstance(item, dict) and item.get('type') in ('input_text', 'text')
                             and isinstance(item.get('text'), str))
            return 'user_prompt', text, 'known_text_fields_only'
    if kind == 'user_message' and isinstance(payload.get('message'), str):
        return 'user_prompt', payload['message'], 'known_text_fields_only'
    if kind in ('function_call', 'custom_tool_call'):
        name = payload.get('name')
        return 'tool_call', name if isinstance(name, str) else '', 'arguments_opaque_not_decoded'
    if kind in ('function_call_output', 'custom_tool_call_output'):
        output = payload.get('output')
        return 'tool_result', output if isinstance(output, str) else '', 'known_text_fields_only' if isinstance(output, str) else 'opaque'
    return str(kind), '', 'opaque_not_decoded'


def reviewed_range(value):
    try:
        start, end = map(int, value.split(':'))
        if start < 1 or end < start:
            raise ValueError()
        return [start, end]
    except ValueError:
        raise argparse.ArgumentTypeError('expected inclusive START:END')


def build(args):
    if args.start < 1 or args.end < args.start or args.byte_budget < 1 or args.excerpt_budget < 0:
        raise Blocked('invalid range or budget')
    source, provenance = resolve(args)
    before = digest(source)
    if args.command == 'event' and before != args.source_sha256:
        raise Blocked('source hash changed')
    manifest = {'schema': 1, 'provenance': provenance, 'source_path': str(source),
                'source_sha256': before, 'range': [args.start, args.end],
                'byte_budget': args.byte_budget, 'excerpt_budget': args.excerpt_budget,
                'review_status': 'MANUAL_SOURCE_ACQUISITION_REQUIRED',
                'reviewed_ranges': args.reviewed, 'prior_conclusion': args.prior_conclusion,
                'prior_conclusion_is_execution_evidence': False,
                'new_action': args.new_action, 'entries': [], 'source_events': 0,
                'selected_events': 0, 'selected_source_bytes': 0,
                'omitted_events': 0, 'omitted_event_bytes': 0,
                'excerpt_bytes': 0, 'source_bytes_not_reproduced': 0,
                'truncated_entries': 0, 'excerpt_omitted_bytes': 0,
                'excerpt_omitted_lines': 0, 'output_bytes': 0,
                'reacquire': {'command': 'event', 'required': ['same identity options',
                              '--start N --end N', '--source-sha256', before,
                              '--byte-budget B --excerpt-budget E',
                              '--prior-conclusion TEXT --new-action TEXT']}}
    offset = 0
    entries = []
    with source.open('rb') as stream:
        for number, raw in enumerate(stream, 1):
            if not raw.endswith(b'\n'):
                raise Blocked('partial final JSONL line at event %d' % number)
            event = parse(raw)
            if number == 1 and args.mode == 'live' and hashlib.sha256(raw).hexdigest() != provenance['session_meta_sha256']:
                raise Blocked('session metadata changed')
            manifest['source_events'] = number
            if args.start <= number <= args.end:
                kind, text, visibility = excerpt(event)
                full = text.encode('utf-8')
                bounded = full[:args.excerpt_budget].decode('utf-8', errors='ignore')
                entries.append({'event': number, 'offset': offset, 'source_bytes': len(raw),
                                'event_sha256': hashlib.sha256(raw).hexdigest(),
                                'kind': kind, 'visibility': visibility, 'excerpt': bounded,
                                'excerpt_original_bytes': len(full),
                                'excerpt_original_lines': len(text.splitlines()),
                                'excerpt_omitted_bytes': len(full) - len(bounded.encode('utf-8')),
                                'line_truncated': len(full) > len(bounded.encode('utf-8')),
                                'already_reviewed': any(a <= number <= b for a, b in args.reviewed)})
                manifest['selected_source_bytes'] += len(raw)
            offset += len(raw)
    if manifest['source_events'] == 0:
        raise Blocked('empty source, zero events')
    if args.end > manifest['source_events']:
        raise Blocked('range outside source')
    if digest(source) != before:
        raise Blocked('source changed during acquisition')
    if args.mode == 'live' and resolve(args) != (source, provenance):
        raise Blocked('live identity changed during acquisition')
    manifest['selected_events'] = len(entries)
    manifest['entries'] = entries

    def recount():
        kept = manifest['entries']
        manifest['omitted_events'] = len(entries) - len(kept)
        manifest['omitted_event_bytes'] = sum(e['source_bytes'] for e in entries[len(kept):])
        manifest['excerpt_bytes'] = sum(len(e['excerpt'].encode('utf-8')) for e in kept)
        manifest['source_bytes_not_reproduced'] = manifest['selected_source_bytes'] - manifest['excerpt_bytes']
        manifest['excerpt_omitted_bytes'] = sum(e['excerpt_original_bytes'] for e in entries) - manifest['excerpt_bytes']
        manifest['excerpt_omitted_lines'] = sum(e['excerpt_original_lines'] for e in entries) - sum(len(e['excerpt'].splitlines()) for e in kept)
        manifest['truncated_entries'] = sum(e['line_truncated'] for e in kept)
        for _ in range(5):
            manifest['output_bytes'] = len(encode(manifest))
        return encode(manifest)

    result = recount()
    if len(result) > args.byte_budget:
        low, high = 0, len(entries)
        while low < high:
            middle = (low + high + 1) // 2
            manifest['entries'] = entries[:middle]
            if len(recount()) <= args.byte_budget:
                low = middle
            else:
                high = middle - 1
        manifest['entries'] = entries[:low]
        result = recount()
    if len(result) > args.byte_budget:
        raise Blocked('byte budget cannot hold manifest')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['index', 'event'])
    parser.add_argument('--mode', choices=['live', 'fixture'], required=True)
    parser.add_argument('--source')
    parser.add_argument('--state-db')
    parser.add_argument('--thread-id')
    parser.add_argument('--workspace')
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--end', type=int, required=True)
    parser.add_argument('--byte-budget', type=int, required=True)
    parser.add_argument('--excerpt-budget', type=int, required=True)
    parser.add_argument('--reviewed', type=reviewed_range, action='append', default=[])
    parser.add_argument('--prior-conclusion', required=True)
    parser.add_argument('--new-action', required=True)
    parser.add_argument('--source-sha256')
    args = parser.parse_args()
    try:
        if args.command == 'event' and (args.start != args.end or not args.source_sha256):
            raise Blocked('event requires one event and --source-sha256')
        sys.stdout.buffer.write(build(args))
    except (Blocked, OSError, ValueError, KeyError, TypeError, sqlite3.Error,
            subprocess.CalledProcessError, RecursionError) as error:
        # Source text and database exception messages can contain sensitive data.
        reason = str(error) if isinstance(error, Blocked) else type(error).__name__
        sys.stderr.write('UNKNOWN/blocked: ' + reason + '\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
