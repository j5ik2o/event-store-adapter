#!/usr/bin/env python3
"""ツールの有無を、1つの実行面の1つの信号だけで結論しないための診断の道具。

PATH の引き当て、解決先の実体、走っているプロセスの実行ファイル、版の出力を
別々に観測し、食い違ったまま「無い」と言わない。判定は観測そのものだけから
決まるので、`--from-json` で過去の観測を再生して同じ判定になるかを確かめられる
（OS に触らない）。標準ライブラリだけで動き、macOS と Linux を想定する。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from typing import Any, Mapping

TOOL_PATH = Path(__file__).resolve()
KNOWN_PATH_ENTRIES = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

VERDICT_OK = "ok"
VERDICT_NOT_INSTALLED = "not-installed"
VERDICT_PATH_RESOLUTION_FAILURE = "path-resolution-failure"
VERDICT_BINARY_MISSING_PROCESS_RUNNING = "binary-missing-process-running"
VERDICT_INCONSISTENT = "inconsistent"

EXIT_CODES = {
    VERDICT_OK: 0,
    VERDICT_NOT_INSTALLED: 1,
    VERDICT_PATH_RESOLUTION_FAILURE: 1,
    VERDICT_BINARY_MISSING_PROCESS_RUNNING: 1,
    VERDICT_INCONSISTENT: 1,
}

OBSERVATION_KEYS = (
    "tool",
    "host",
    "surface",
    "path_entries",
    "which",
    "resolved",
    "resolved_exists",
    "which_resolved",
    "processes",
    "version_output",
)
PROCESS_KEYS = ("pid", "command", "exe", "exe_exists")
# 古い観測には無い。無い観測は「which の解決先を確認していない」ものとして扱い、
# ok とは言わない（保守側に倒す）。
OPTIONAL_OBSERVATION_KEYS = ("which_resolved",)


@dataclass(frozen=True)
class Verdict:
    """1つの観測に対する判定。判定名、終了コード、人に読ませる説明を持つ。"""

    name: str
    exit_code: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.name,
            "exit_code": self.exit_code,
            "message": self.message,
        }


def _verdict(name: str, message: str) -> Verdict:
    return Verdict(name=name, exit_code=EXIT_CODES[name], message=message)


def _existing_paths(observation: Mapping[str, Any]) -> list[str]:
    """実体があると観測されたパスを、解決先とプロセスの実行ファイルから集める。"""

    found: list[str] = []
    resolved = observation.get("resolved")
    if resolved and observation.get("resolved_exists"):
        found.append(str(resolved))
    for process in observation.get("processes") or []:
        exe = process.get("exe")
        if exe and process.get("exe_exists"):
            found.append(str(exe))
    return found


def verdict(observation: Mapping[str, Any]) -> Verdict:
    """観測を判定する。OS には触らない。"""

    tool = str(observation.get("tool") or "?")
    which = observation.get("which")
    resolved = observation.get("resolved")
    resolved_exists = bool(observation.get("resolved_exists"))
    which_resolved = observation.get("which_resolved")
    processes = list(observation.get("processes") or [])

    # PATH の引き当てと、そこから解決した実体が同じものを指し、その実体が
    # 存在するときだけ「動く」と言える。どちらか一方だけでは足りない。
    if which and resolved and resolved_exists and which_resolved == resolved:
        return _verdict(
            VERDICT_OK,
            f"{tool}: found on PATH as {resolved}",
        )

    # 走っているプロセスの実行ファイルが消えているなら、PATH の引き当てとは
    # 別の話として、その PID と消えたパスを出す。
    missing = [
        process
        for process in processes
        if process.get("exe") and not process.get("exe_exists")
    ]
    if missing:
        details = ", ".join(
            f"pid {process.get('pid')} -> {process.get('exe')}" for process in missing
        )
        return _verdict(
            VERDICT_BINARY_MISSING_PROCESS_RUNNING,
            f"{tool}: the executable of a running process no longer exists ({details})",
        )

    # PATH では引けない（または which の解決先が実体ではない）が、既知のパスか
    # プロセスの実行ファイルに実体がある。PATH の層だけを見て「無い」とは言わない。
    existing = _existing_paths(observation)
    if existing:
        return _verdict(
            VERDICT_PATH_RESOLUTION_FAILURE,
            f"{tool}: not resolvable through PATH, but the executable exists at {', '.join(existing)}",
        )

    # PATH の引き当てはあったのに実体を確認できない食い違い。実体がどこかにある
    # かもしれないので「無い」とは言わない。
    if which:
        return _verdict(
            VERDICT_INCONSISTENT,
            f"{tool}: PATH lookup returned {which}, but no executable entity was verified at {resolved or which}",
        )

    # PATH で引けず、実体もなく、プロセスも動いていない。この状態だけが「無い」。
    if not processes:
        return _verdict(
            VERDICT_NOT_INSTALLED,
            f"{tool}: not found on PATH, not running in any process, and no executable at the known paths",
        )

    # プロセスは動いているが実行ファイルを確認できない。無いとは言えない。
    return _verdict(
        VERDICT_INCONSISTENT,
        f"{tool}: not found on PATH and no executable entity, but {len(processes)} process(es) are running with an unknown executable",
    )


def known_path_entries() -> list[str]:
    entries = list(KNOWN_PATH_ENTRIES)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and entry not in entries:
            entries.append(entry)
    return entries


def _resolve(
    tool: str, which: str | None, path_entries: list[str]
) -> tuple[str | None, bool, str | None]:
    """(resolved, resolved_exists, which_resolved) を返す。

    which の指す先に実体があれば、その realpath を resolved と which_resolved の
    両方に入れる。which が壊れているときは which_resolved を None のままにし、
    resolved には既知のパスで見つかった実体を入れる（無ければ壊れたパスを返し、
    実体なしとする）。PATH 側と実体側の食い違いを消さずに残すため。
    """

    if which and os.path.exists(which):
        which_resolved = os.path.realpath(which)
        return which_resolved, True, which_resolved
    for entry in path_entries:
        candidate = os.path.join(entry, tool)
        if os.path.exists(candidate):
            return os.path.realpath(candidate), True, None
    if which:
        return os.path.realpath(which), False, None
    return None, False, None


def _process_exe(pid: int) -> str | None:
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        for line in completed.stdout.splitlines():
            if line.startswith("n") and len(line) > 1:
                return line[1:]
        return None
    if sys.platform.startswith("linux"):
        try:
            target = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
        suffix = " (deleted)"
        if target.endswith(suffix):
            target = target[: -len(suffix)]
        return target
    return None


def _processes(tool: str) -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["pgrep", "-fl", tool],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    found: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, _, command = line.partition(" ")
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == os.getpid():
            continue
        exe = _process_exe(pid)
        found.append(
            {
                "pid": pid,
                "command": command.strip(),
                "exe": exe,
                "exe_exists": bool(exe) and os.path.exists(exe),
            }
        )
    return found


def _version_output(executable: str | None) -> str | None:
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout + completed.stderr).strip()
    return text or None


def observe(tool: str) -> dict[str, Any]:
    """実環境を観測する。OS に触れるのはこの関数と、それが呼ぶ補助だけ。"""

    path_entries = known_path_entries()
    which = shutil.which(tool)
    resolved, resolved_exists, which_resolved = _resolve(tool, which, path_entries)
    processes = _processes(tool)
    executable = which_resolved or (resolved if resolved_exists else None)
    return {
        "tool": tool,
        "host": socket.gethostname(),
        "surface": os.environ.get("ORCA_TERMINAL_HANDLE") or "local-shell",
        "path_entries": path_entries,
        "which": which,
        "resolved": resolved,
        "resolved_exists": resolved_exists,
        "which_resolved": which_resolved,
        "processes": processes,
        "version_output": _version_output(executable),
    }


def load_observation(path: Path) -> dict[str, Any]:
    """保存された観測を読み、形を確かめる。OS には触らない。"""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: observation must be a JSON object")
    missing = [
        key
        for key in OBSERVATION_KEYS
        if key not in data and key not in OPTIONAL_OBSERVATION_KEYS
    ]
    if missing:
        raise ValueError(f"{path}: missing key(s): {', '.join(missing)}")
    if not isinstance(data["tool"], str) or not data["tool"]:
        raise ValueError(f"{path}: tool must be a non-empty string")
    for key in ("host", "surface"):
        if not isinstance(data[key], str):
            raise ValueError(f"{path}: {key} must be a string")
    if not isinstance(data["path_entries"], list) or not all(
        isinstance(entry, str) for entry in data["path_entries"]
    ):
        raise ValueError(f"{path}: path_entries must be a list of strings")
    for key in ("which", "resolved", "version_output", "which_resolved"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            raise ValueError(f"{path}: {key} must be a string or null")
    if not isinstance(data["resolved_exists"], bool):
        raise ValueError(f"{path}: resolved_exists must be a boolean")
    if not isinstance(data["processes"], list):
        raise ValueError(f"{path}: processes must be a list")
    for process in data["processes"]:
        if not isinstance(process, dict):
            raise ValueError(f"{path}: each process must be an object")
        missing = [key for key in PROCESS_KEYS if key not in process]
        if missing:
            raise ValueError(f"{path}: process is missing key(s): {', '.join(missing)}")
        if not isinstance(process["pid"], int):
            raise ValueError(f"{path}: process pid must be an integer")
        if not isinstance(process["command"], str):
            raise ValueError(f"{path}: process command must be a string")
        for key in ("exe",):
            if process[key] is not None and not isinstance(process[key], str):
                raise ValueError(f"{path}: process {key} must be a string or null")
        if not isinstance(process["exe_exists"], bool):
            raise ValueError(f"{path}: process exe_exists must be a boolean")
    return data


def render_text(observation: Mapping[str, Any], result: Verdict) -> str:
    lines = [
        f"tool: {observation.get('tool')}",
        f"host: {observation.get('host')}",
        f"surface: {observation.get('surface')}",
        f"verdict: {result.name} (exit {result.exit_code})",
        f"message: {result.message}",
    ]
    return "\n".join(lines)


def build_payload(observation: Mapping[str, Any], result: Verdict) -> dict[str, Any]:
    payload = {
        "tool": observation.get("tool"),
        "host": observation.get("host"),
        "surface": observation.get("surface"),
    }
    payload.update(result.to_dict())
    payload["observation"] = dict(observation)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe a tool through several signals before calling it missing.",
    )
    parser.add_argument("tool", nargs="?", help="command to diagnose")
    parser.add_argument(
        "--from-json",
        metavar="OBS",
        help="judge a saved observation instead of observing the OS",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    if args.from_json:
        if args.tool:
            parser.error("tool cannot be combined with --from-json")
        try:
            observation = load_observation(Path(args.from_json))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"diagnose: {error}", file=sys.stderr)
            return 2
    else:
        if not args.tool:
            parser.error("a tool is required unless --from-json is given")
        observation = observe(args.tool)

    result = verdict(observation)
    if args.json:
        print(json.dumps(build_payload(observation, result), ensure_ascii=False, indent=2))
    else:
        print(render_text(observation, result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
