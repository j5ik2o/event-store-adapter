#!/usr/bin/env python3
"""Check that a dispatch plan and its Orca terminal claims can be verified.

The coordinator reports that work was launched, delegated, or verified. This
tool makes the two mistakes that class of report allows impossible to pass
unnoticed:

* two tracks that run the same verification, which duplicates finished work;
* a claim that names a terminal that Orca never created.

It only inspects the JSON files it is given (or, with ``--from-orca``, the
output of ``orca terminal list --json``). It does not create terminals or
launch work, and it uses the standard library only.
"""

import argparse
import json
import posixpath
import subprocess
import sys
from pathlib import Path

OK_PLAN = "dispatch plan: OK ({count} tracks)"
OK_CLAIMS = "dispatch claims: OK ({count} claims)"

PLAN_FIELDS = ("id", "phase", "worktree", "scope", "verification")
CLAIM_FIELDS = ("track", "terminal", "worktree", "title")


class DispatchError(Exception):
    """Input that cannot be checked at all: a missing file or a wrong shape."""


def load_json(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DispatchError(f"cannot read {path}: {error}") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise DispatchError(f"{path} is not valid JSON: {error}") from error


def normalized_verification(text: str) -> str:
    """Collapse whitespace so that reformatting the same command stays equal."""
    return " ".join(text.split())


def scopes_overlap(first: str, second: str) -> bool:
    """Return whether two scopes share any path, using normpath prefix matching."""
    left = posixpath.normpath(first)
    right = posixpath.normpath(second)
    if left == right:
        return True
    if left in ("/", ".") or right in ("/", "."):
        return True
    return left.startswith(right + "/") or right.startswith(left + "/")


def require_text(container: dict, name: str, where: str) -> str:
    value = container.get(name)
    if not isinstance(value, str) or not value:
        raise DispatchError(f"{where}.{name} must be a non-empty string")
    return value


def require_tracks(document: object) -> list:
    if not isinstance(document, dict):
        raise DispatchError("plan must be a JSON object")
    tracks = document.get("tracks")
    if not isinstance(tracks, list):
        raise DispatchError("plan.tracks must be a list")
    return tracks


def check_plan(document: object) -> list[str]:
    """Return every plan violation, each prefixed with the offending track id."""
    tracks = require_tracks(document)
    violations = []
    seen_ids = {}
    seen_worktrees = {}
    verifications = []
    scopes = []

    for index, track in enumerate(tracks):
        where = f"plan.tracks[{index}]"
        if not isinstance(track, dict):
            raise DispatchError(f"{where} must be a JSON object")
        for field in PLAN_FIELDS:
            if field not in track:
                raise DispatchError(f"{where} is missing {field}")

        track_id = require_text(track, "id", where)
        worktree = require_text(track, "worktree", where)
        verification = require_text(track, "verification", where)
        scope = track["scope"]
        if not isinstance(scope, list) or not all(isinstance(path, str) and path for path in scope):
            raise DispatchError(f"{where}.scope must be a list of non-empty strings")

        if track_id in seen_ids:
            violations.append(f"track {track_id}: duplicate id")
        else:
            seen_ids[track_id] = index

        if worktree in seen_worktrees:
            violations.append(
                f"track {track_id}: duplicate worktree '{worktree}'"
                f" (first used by track '{seen_worktrees[worktree]}')"
            )
        else:
            seen_worktrees[worktree] = track_id

        command = normalized_verification(verification)
        duplicate = next((other for other in verifications if other[1] == command), None)
        if duplicate is not None:
            violations.append(
                f"track {track_id}: duplicate verification"
                f" (same as track '{duplicate[0]}'): {command}"
            )
        verifications.append((track_id, command))
        scopes.append((track_id, scope))

    for left_index in range(len(scopes)):
        for right_index in range(left_index + 1, len(scopes)):
            left_id, left_scope = scopes[left_index]
            right_id, right_scope = scopes[right_index]
            overlap = next(
                (
                    (left_path, right_path)
                    for left_path in left_scope
                    for right_path in right_scope
                    if scopes_overlap(left_path, right_path)
                ),
                None,
            )
            if overlap is not None:
                violations.append(
                    f"track {right_id}: scope '{overlap[1]}'"
                    f" overlaps track '{left_id}' scope '{overlap[0]}'"
                )

    return violations


def require_claims(document: object) -> list:
    if not isinstance(document, dict):
        raise DispatchError("claims must be a JSON object")
    claims = document.get("claims")
    if not isinstance(claims, list):
        raise DispatchError("claims.claims must be a list")
    return claims


def terminals_from(document: object) -> list:
    """Read the terminal records from `orca terminal list --json` output."""
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        raise DispatchError("terminals JSON must be an object or a list")
    if document.get("ok") is False:
        raise DispatchError("`orca terminal list --json` reported ok=false")
    result = document.get("result")
    if isinstance(result, dict) and isinstance(result.get("terminals"), list):
        return result["terminals"]
    if isinstance(document.get("terminals"), list):
        return document["terminals"]
    raise DispatchError(
        "terminals JSON is not the output of `orca terminal list --json` (result.terminals)"
    )


def check_claims(document: object, terminals_document: object) -> list[str]:
    """Return every claim violation, each prefixed with the claim's track id."""
    claims = require_claims(document)
    terminals = terminals_from(terminals_document)
    by_handle = {}
    for terminal in terminals:
        if isinstance(terminal, dict) and isinstance(terminal.get("handle"), str):
            by_handle[terminal["handle"]] = terminal

    violations = []
    for index, claim in enumerate(claims):
        where = f"claims.claims[{index}]"
        if not isinstance(claim, dict):
            raise DispatchError(f"{where} must be a JSON object")
        for field in CLAIM_FIELDS:
            if field not in claim:
                raise DispatchError(f"{where} is missing {field}")

        track_id = require_text(claim, "track", where)
        handle = require_text(claim, "terminal", where)
        worktree = require_text(claim, "worktree", where)
        title = require_text(claim, "title", where)

        terminal = by_handle.get(handle)
        if terminal is None:
            violations.append(f"track {track_id}: terminal '{handle}' is not listed by Orca")
            continue

        known_worktrees = [
            value
            for value in (terminal.get("worktreeId"), terminal.get("worktreePath"))
            if isinstance(value, str)
        ]
        if worktree not in known_worktrees:
            actual = terminal.get("worktreePath") or terminal.get("worktreeId") or "<unknown>"
            violations.append(
                f"track {track_id}: terminal '{handle}' runs in worktree '{actual}',"
                f" not '{worktree}'"
            )

        actual_title = terminal.get("title")
        if actual_title != title:
            shown = actual_title if isinstance(actual_title, str) and actual_title else "<none>"
            violations.append(
                f"track {track_id}: terminal '{handle}' has title '{shown}', not '{title}'"
            )

    return violations


def read_terminals(path: Path | None, from_orca: bool) -> object:
    if from_orca:
        try:
            completed = subprocess.run(
                ["orca", "terminal", "list", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise DispatchError(f"cannot run `orca terminal list --json`: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit {completed.returncode}"
            raise DispatchError(f"`orca terminal list --json` failed: {detail}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise DispatchError(f"`orca terminal list --json` returned invalid JSON: {error}") from error
    if path is None:
        raise DispatchError("--terminals is required unless --from-orca is given")
    return load_json(path)


def run_plan(path: Path, stdout, stderr) -> int:
    try:
        document = load_json(path)
        violations = check_plan(document)
        count = len(require_tracks(document))
    except DispatchError as error:
        print(f"dispatch: {error}", file=stderr)
        return 1
    if violations:
        for violation in violations:
            print(violation, file=stderr)
        return 1
    print(OK_PLAN.format(count=count), file=stdout)
    return 0


def run_claims(path: Path, terminals_path: Path | None, from_orca: bool, stdout, stderr) -> int:
    try:
        document = load_json(path)
        terminals_document = read_terminals(terminals_path, from_orca)
        violations = check_claims(document, terminals_document)
        count = len(require_claims(document))
    except DispatchError as error:
        print(f"dispatch: {error}", file=stderr)
        return 1
    if violations:
        for violation in violations:
            print(violation, file=stderr)
        return 1
    print(OK_CLAIMS.format(count=count), file=stdout)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dispatch.py",
        description="Check dispatch plans and Orca terminal claims.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="check a dispatch plan")
    plan.add_argument("plan", type=Path)

    claims = commands.add_parser("claims", help="check claims against Orca terminals")
    claims.add_argument("claims", type=Path)
    claims.add_argument("--terminals", type=Path)
    claims.add_argument("--from-orca", action="store_true")

    check = commands.add_parser("check", help="run plan and claims checks in order")
    check.add_argument("plan", type=Path)
    check.add_argument("claims", type=Path)
    check.add_argument("--terminals", type=Path)
    check.add_argument("--from-orca", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "plan":
        return run_plan(arguments.plan, sys.stdout, sys.stderr)

    if arguments.command == "claims":
        return run_claims(
            arguments.claims,
            arguments.terminals,
            arguments.from_orca,
            sys.stdout,
            sys.stderr,
        )

    plan_status = run_plan(arguments.plan, sys.stdout, sys.stderr)
    claims_status = run_claims(
        arguments.claims,
        arguments.terminals,
        arguments.from_orca,
        sys.stdout,
        sys.stderr,
    )
    return 0 if plan_status == 0 and claims_status == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
