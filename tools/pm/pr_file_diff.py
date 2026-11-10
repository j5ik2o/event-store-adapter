#!/usr/bin/env python3
"""Read selected PR patches through gh. See pr_file_diff.md for guarantees."""
import argparse
import json
import re
import subprocess
import tempfile


class Unavailable(Exception):
    pass


def api(endpoint):
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                 '-H', 'Accept: application/vnd.github+json',
                 '-H', 'X-GitHub-Api-Version: 2026-03-10', endpoint],
                stdout=output, stderr=subprocess.DEVNULL, timeout=45, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Unavailable('api_execution_failed') from None
        if result.returncode:
            raise Unavailable('api_request_failed')
        output.seek(0)
        data = output.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise Unavailable('api_response_limit')
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise Unavailable('invalid_api_json') from None


def metadata(value):
    try:
        revision = {side: value[side]['sha'] for side in ('head', 'base')}
        if not all(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40,64}', sha)
                   for sha in revision.values()):
            raise ValueError()
        for key in ('changed_files', 'additions', 'deletions'):
            if type(value[key]) is not int or value[key] < 0:
                raise ValueError()
        return dict(revision, **{key: value[key] for key in ('changed_files', 'additions', 'deletions')})
    except (KeyError, TypeError, ValueError):
        raise Unavailable('invalid_pr_metadata') from None


def patch_reasons(patch, additions, deletions):
    if not isinstance(patch, str) or not patch:
        return ['patch_missing_binary_or_omitted']
    counts = [0, 0]
    remaining = None
    previous_end = [0, 0]
    previous_line = None
    terminated_sides = [False, False]
    for line in patch.split('\n'):
        match = re.fullmatch(r'@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@.*', line)
        if match:
            values = [match[1], match[2] or '1', match[3], match[4] or '1']
            if any(len(value) > 10 or int(value) > 2147483647 for value in values):
                return ['hunk_number_out_of_range']
            if any(terminated_sides):
                return ['newline_marker_invalid']
            if remaining and any(remaining):
                return ['hunk_incomplete']
            start = [int(values[0]), int(values[2])]
            if any(start[i] < previous_end[i] for i in (0, 1)):
                return ['hunk_order_invalid']
            remaining = [int(values[1]), int(values[3])]
            previous_end = [start[i] + remaining[i] for i in (0, 1)]
            previous_line = None
        elif line == '\\ No newline at end of file':
            if previous_line is None:
                return ['newline_marker_invalid']
            sides = (0, 1) if previous_line == ' ' else ((0,) if previous_line == '-' else (1,))
            if any(remaining[i] or terminated_sides[i] for i in sides):
                return ['newline_marker_invalid']
            for i in sides:
                terminated_sides[i] = True
            previous_line = None
        elif line[:1] in (' ', '+', '-') and remaining is not None:
            sides = (0, 1) if line[0] == ' ' else ((0,) if line[0] == '-' else (1,))
            if any(terminated_sides[i] for i in sides):
                return ['newline_marker_invalid']
            if line[0] != '+':
                remaining[0] -= 1
            if line[0] != '-':
                remaining[1] -= 1
            if line[0] == '+':
                counts[0] += 1
            if line[0] == '-':
                counts[1] += 1
            if min(remaining) < 0:
                return ['hunk_length_mismatch']
            previous_line = line[0]
        else:
            return ['patch_syntax_invalid']
    if remaining is None:
        return ['hunk_missing']
    if any(remaining):
        return ['hunk_incomplete']
    if counts != [additions, deletions]:
        return ['patch_change_count_mismatch']
    return []


def collect(endpoint, selection, report):
    before = metadata(api(endpoint))
    report['revision']['before'] = before
    records = {}
    reasons = report['reasons']
    for page in range(1, 31):
        batch = api(f'{endpoint}/files?per_page=100&page={page}')
        if not isinstance(batch, list) or len(batch) > 100:
            raise Unavailable('invalid_files_page')
        for item in batch:
            if not isinstance(item, dict) or not isinstance(item.get('filename'), str):
                raise Unavailable('invalid_file_metadata')
            name = item['filename']
            if name in records:
                reasons.append('duplicate_filename')
            for key in ('additions', 'deletions', 'changes'):
                if type(item.get(key)) is not int or item[key] < 0:
                    raise Unavailable('invalid_file_counts')
            records[name] = item
        if len(batch) < 100:
            break
    after = metadata(api(endpoint))
    report['revision']['after'] = after
    if before != after:
        reasons.append('revision_or_metadata_changed')
    report['files_received'] = len(records)
    if before['changed_files'] >= 3000 or len(records) >= 3000:
        reasons.append('github_files_limit')
    if len(records) != before['changed_files']:
        reasons.append('file_count_mismatch')
    for key in ('additions', 'deletions'):
        if sum(item[key] for item in records.values()) != before[key]:
            reasons.append(f'{key}_total_mismatch')
    report['unselected'] = {'count': len(set(records) - set(selection)), 'reason': 'not_selected'}
    for name in selection:
        item = records.get(name)
        entry = {'filename': name, 'state': 'unavailable', 'patch': None, 'reasons': []}
        report['files'].append(entry)
        if item is None:
            entry['reasons'] = ['selected_path_missing']
            continue
        for key in ('status', 'sha', 'previous_filename', 'additions', 'deletions', 'changes'):
            if key in item:
                entry[key] = item[key]
        if item['changes'] != item['additions'] + item['deletions']:
            entry['reasons'].append('file_change_count_mismatch')
        if item['additions'] == item['deletions'] == 0:
            entry['state'] = 'metadata-only'
            entry['reasons'].append('rename_only' if item.get('status') == 'renamed'
                                    else 'zero_text_changes_binary_or_metadata')
            continue
        entry['reasons'].extend(patch_reasons(item.get('patch'), item['additions'], item['deletions']))
        if not entry['reasons']:
            entry['state'] = 'validated-api-patch'
            entry['patch'] = item['patch']
    report['api_consistent'] = not reasons and all(not entry['reasons'] for entry in report['files'])
    if report['api_consistent']:
        reasons.append('api_only_completeness_unproven')


def encode(report):
    return json.dumps(report, ensure_ascii=True, separators=(',', ':')).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pr', help='https://github.com/OWNER/REPO/pull/NUMBER or OWNER/REPO')
    parser.add_argument('number', nargs='?', help='PR number when using OWNER/REPO')
    parser.add_argument('--file', action='append', required=True, help='exact current filename; repeat to select several')
    parser.add_argument('--max-output-bytes', type=int, default=1048576, help='JSON cap, 1024..8388608 (default 1048576)')
    args = parser.parse_args()
    report = {'revision': {}, 'selection': list(dict.fromkeys(args.file)), 'files': [],
              'complete': False, 'api_consistent': False, 'reasons': [], 'completeness_scope': 'selected_text_patch_api_accounting',
              'limitations': ['API consistency does not prove byte-for-byte equivalence to a local Git diff.',
                              'Binary and metadata-only changes have no verified text patch.',
                              'Revision checks cannot detect a change followed by a revert between requests.']}
    target = args.pr if args.number is None else f'https://github.com/{args.pr}/pull/{args.number}'
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?', target)
    if not match or not 1024 <= args.max_output_bytes <= 8388608:
        report['reasons'].append('invalid_arguments')
    else:
        endpoint = f'repos/{match[1]}/{match[2]}/pulls/{match[3]}'
        try:
            collect(endpoint, report['selection'], report)
        except Unavailable as error:
            report['complete'] = False
            report['reasons'].append(str(error))
    budget = args.max_output_bytes if 1024 <= args.max_output_bytes <= 8388608 else 1024
    data = encode(report)
    if len(data) + 1 > budget:
        report = {'revision': report['revision'], 'selection': [], 'files': [], 'complete': False,
                  'reasons': ['output_limit'], 'selection_count': len(report['selection']),
                  'selection_omitted': True, 'completeness_scope': report['completeness_scope']}
        data = encode(report)
        if len(data) + 1 > budget:
            report['revision'] = {}
            data = encode(report)
    print(data.decode('utf-8'))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
