#!/usr/bin/env python3
"""Inventory the ESA line's Orca worktrees and worker terminals, and clean up only what is provably safe.

Without --apply nothing is changed. A worktree is removed only when all three facts were observed:
its branch has a merged PR, it is clean (no changes, no untracked files), and no commit is unpushed.
A worker terminal is released only when its task is settled and nothing runs or waits for input in it.
Anything that cannot be observed is kept and listed with the reason.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

REPOS = (
    'event-store-adapter',
    'event-store-adapter-java',
    'event-store-adapter-rs',
    'event-store-adapter-go',
    'event-store-adapter-js',
    'event-store-adapter-scala',
    'event-store-adapter-kotlin',
    'cqrs-es-example',
    'cqrs-es-example-java',
    'cqrs-es-example-rs',
    'cqrs-es-example-go',
    'cqrs-es-example-js',
    'cqrs-es-example-scala',
    'cqrs-es-example-kotlin',
)
PROJECTS = {f'github:j5ik2o/{name}': f'j5ik2o/{name}' for name in REPOS}
PARALLEL_MARKERS = ('parallel', '並列')
SETTLED = {'succeeded', 'failed', 'cancelled'}
LOG = Path.home() / '.local' / 'state' / 'esa-orca-cleanup' / 'log.jsonl'
TIMEOUT = 60


def run(args, cwd=None):
    """Return stdout, or None when the command failed or timed out."""
    try:
        done = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def run_json(args):
    out = run(args)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


# ---- decisions (pure) -------------------------------------------------------------------------


def decide_worktree(facts):
    """facts: dict with keys main, seat, parallel, attached, merged_pr, clean, unpushed_free.

    Each fact is True, False or None (not observed). Returns (action, reason).
    """
    if facts['main']:
        return 'keep', 'ghq のプライマリ（main worktree）'
    if facts['seat']:
        return 'keep', 'coordinator の座'
    if facts['attached'] is not False:
        return 'keep', '生きているワーカーかターミナルがある' if facts['attached'] else '付いているターミナルを確かめられない'
    missing = [name for name in ('merged_pr', 'clean', 'unpushed_free') if facts[name] is None]
    if missing:
        return 'keep', '確認不能: ' + ', '.join(missing)
    if not facts['merged_pr']:
        return 'keep', '対応する PR がマージされていない'
    if not facts['clean']:
        return 'keep', '未コミットの変更か未追跡のファイルがある'
    if not facts['unpushed_free']:
        return 'keep', '未 push のコミットがある'
    if facts['parallel']:
        return 'list', '並列 worktree: 条件は満たすが、記録した掃除担当・時期に従う'
    return 'remove', '3 条件を満たす（PR マージ済み・クリーン・未 push なし）'


def decide_worker(worker, own_terminal, released_terminals=frozenset()):
    """worker: worker-show result merged with worker-list. Returns (action, reason)."""
    if worker.get('terminal') == own_terminal:
        return 'keep', 'coordinator 自身のターミナル'
    if not worker.get('terminal'):
        return 'skip', 'ターミナルを持たない'
    if worker.get('terminalState') is None and worker['terminal'] in released_terminals:
        return 'skip', '後続のディスパッチに引き継いだターミナルは解放済み'
    if worker.get('terminalState') in ('released', None) and worker.get('liveness') in ('exited', None):
        return 'skip', 'ターミナルはもうない'
    if worker.get('state') not in SETTLED or worker.get('stage') not in ('settled', None):
        return 'keep', f"タスクが完了していない（state={worker.get('state')}）"
    if worker.get('terminalState') != 'retained':
        return 'keep', f"terminalState={worker.get('terminalState')}"
    liveness = worker.get('liveness')
    if liveness == 'exited':
        return 'release', 'タスク完了、プロセスは終了済み'
    if liveness != 'live':
        return 'keep', f'確認不能: liveness={liveness}'
    if worker.get('activity') != 'idle':
        return 'keep', f"実行中（activity={worker.get('activity')}）"
    waiting = worker.get('waitingOnHuman')
    if waiting is True or waiting == 'yes':
        return 'keep', '入力待ちで停滞（要判断）'
    if waiting not in (False, 'no'):
        return 'keep', f'確認不能: 入力待ちかどうか分からない（waitingOnHuman={waiting}）'
    return 'release', 'タスク完了、アイドルで入力待ちなし'


# ---- observation ------------------------------------------------------------------------------


def branch_name(ref):
    return ref[len('refs/heads/'):] if ref and ref.startswith('refs/heads/') else None


def merged_prs(repo, branch):
    data = run_json(['gh', 'pr', 'list', '-R', repo, '--head', branch, '--state', 'merged',
                     '--json', 'number,headRefOid', '--limit', '20'])
    return data


def observe_worktree(wt, seat, attached):
    path = wt['path']
    repo = PROJECTS[wt['projectId']]
    branch = branch_name(wt.get('branch'))
    facts = {
        'main': bool(wt.get('isMainWorktree')),
        'seat': wt['id'] == seat,
        'parallel': any(m in (wt.get('comment') or '').lower() for m in PARALLEL_MARKERS),
        'attached': attached,
        'merged_pr': None,
        'clean': None,
        'unpushed_free': None,
    }
    detail = {'repo': repo, 'branch': branch, 'path': path}
    if facts['main'] or facts['seat']:
        return facts, detail
    head = run(['git', '-C', path, 'rev-parse', 'HEAD'])
    head = head.strip() if head else None
    status = run(['git', '-C', path, 'status', '--porcelain', '--untracked-files=all'])
    if status is not None:
        facts['clean'] = status.strip() == ''
    prs = merged_prs(repo, branch) if branch else None
    if prs is not None:
        facts['merged_pr'] = len(prs) > 0
        detail['prs'] = [p['number'] for p in prs]
    unpushed = run(['git', '-C', path, 'rev-list', 'HEAD', '--not', '--remotes'])
    if unpushed is not None:
        if unpushed.strip() == '':
            facts['unpushed_free'] = True
        elif head and prs is not None:
            # A deleted remote branch drops its refs; a merged PR whose head is this HEAD still
            # holds every commit on GitHub.
            facts['unpushed_free'] = any(p['headRefOid'] == head for p in prs)
        else:
            facts['unpushed_free'] = None if head is None else False
    detail['head'] = head
    return facts, detail


def other_live_workspaces(own_runs):
    """Workspaces that a worker of any other Run still holds. None when that cannot be observed."""
    held, cursor = set(), None
    while True:
        args = ['orca', 'orchestration', 'run-list', '--json'] + (['--cursor', cursor] if cursor else [])
        page = run_json(args)
        if page is None:
            return None
        for item in page['result']['runs']:
            if item['id'] in own_runs:
                continue
            workers = run_json(['orca', 'orchestration', 'worker-list', '--run', item['id'], '--json'])
            if workers is None:
                return None
            for worker in workers['result']['workers']:
                if worker.get('liveness') != 'exited' or worker.get('terminalState') == 'retained':
                    held.add(worker.get('workspace'))
        cursor = page['result'].get('nextCursor')
        if not cursor:
            return held


def inventory(runs, apply):
    own_terminal = os.environ.get('ORCA_TERMINAL_HANDLE')
    seat = os.environ.get('ORCA_WORKTREE_ID')
    result = {'at': datetime.now(timezone.utc).isoformat(), 'apply': apply,
              'workers': [], 'worktrees': [], 'terminals': [], 'errors': []}

    live_workspaces = set()
    for run_id in runs:
        listed = run_json(['orca', 'orchestration', 'worker-list', '--run', run_id, '--json'])
        if listed is None:
            result['errors'].append(f'worker-list に失敗: {run_id}')
            continue
        released = {w.get('terminal') for w in listed['result']['workers']
                    if w.get('terminalState') == 'released'}
        for item in listed['result']['workers']:
            shown = run_json(['orca', 'orchestration', 'worker-show', '--dispatch', item['dispatchId'], '--json'])
            worker = dict(item, **(shown['result'] if shown else {}))
            action, reason = decide_worker(worker, own_terminal, released)
            if action == 'skip':
                continue
            entry = {'dispatch': item['dispatchId'], 'task': item.get('taskId'),
                     'workspace': item.get('workspace'), 'action': action, 'reason': reason}
            if action == 'release' and apply:
                done = run_json(['orca', 'orchestration', 'worker-release', '--dispatch', item['dispatchId'], '--json'])
                entry['done'] = bool(done and done.get('ok'))
                if not entry['done']:
                    entry['action'], entry['reason'] = 'keep', 'release に失敗'
            if entry['action'] != 'release' or not apply:
                live_workspaces.add(item.get('workspace'))
            result['workers'].append(entry)

    others = other_live_workspaces(set(runs))
    if others is None:
        result['errors'].append('ほかの Run のワーカーを確かめられない')
    else:
        live_workspaces |= others

    terminals = run_json(['orca', 'terminal', 'list', '--json', '--limit', '500'])
    terminal_worktrees = None
    if terminals is None:
        result['errors'].append('terminal list に失敗')
    else:
        terminal_worktrees = set()
        for term in terminals['result']['terminals']:
            path = term.get('worktreePath') or ''
            if not any(f'/{name}' in path for name in REPOS):
                continue
            terminal_worktrees.add(term.get('worktreeId'))
            reason = ('coordinator 自身のターミナル' if term['handle'] == own_terminal
                      else '確認不能: 対応するタスクが分からない（Run のワーカーではない）')
            result['terminals'].append({'handle': term['handle'], 'title': term.get('title'),
                                        'worktree': term.get('worktreeId'), 'action': 'keep', 'reason': reason})

    worktrees = run_json(['orca', 'worktree', 'list', '--json', '--limit', '500'])
    if worktrees is None:
        result['errors'].append('worktree list に失敗')
        return result
    for wt in worktrees['result']['worktrees']:
        if wt.get('projectId') not in PROJECTS:
            continue
        if terminal_worktrees is None or others is None:
            attached = None
        else:
            attached = wt['id'] in live_workspaces or wt['id'] in terminal_worktrees
        facts, detail = observe_worktree(wt, seat, attached)
        action, reason = decide_worktree(facts)
        if facts['main']:
            continue
        entry = dict(detail, id=wt['id'], action=action, reason=reason, facts=facts)
        if action == 'remove' and apply:
            done = run_json(['orca', 'worktree', 'rm', '--worktree', f"id:{wt['id']}", '--delete-branch', '--json'])
            entry['done'] = bool(done and done.get('ok'))
            if not entry['done']:
                entry['action'], entry['reason'] = 'keep', 'worktree rm に失敗'
        result['worktrees'].append(entry)
    return result


def summary(result):
    removed = [w for w in result['worktrees'] if w['action'] == 'remove' and w.get('done')]
    released = [w for w in result['workers'] if w['action'] == 'release' and w.get('done')]
    pending = ([w for w in result['worktrees'] if w['action'] == 'list']
               + [w for w in result['workers'] if '停滞' in w['reason']]
               + [w for w in result['worktrees'] + result['workers'] + result['terminals']
                  if w['reason'].startswith('確認不能') and 'coordinator' not in w['reason']])
    return {'removed_worktrees': len(removed), 'released_workers': len(released),
            'needs_judgement': len(pending), 'errors': len(result['errors'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', action='append', required=True, help='coordinator の Run ID（複数可）')
    parser.add_argument('--apply', action='store_true', help='条件を満たすものを実際に消す')
    parser.add_argument('--log', type=Path, default=LOG)
    args = parser.parse_args(argv)
    result = inventory(args.run, args.apply)
    result['summary'] = summary(result)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open('a', encoding='utf-8') as log:
        log.write(json.dumps(result, ensure_ascii=False) + '\n')
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
