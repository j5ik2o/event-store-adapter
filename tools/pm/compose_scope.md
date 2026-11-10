# Manual Compose scope comparison

Use `compose_scope.py` before running an e2e cleanup that could affect a regular
stack. This is a manual, offline review aid, not a CI gate or Docker lifecycle
manager. It executes no Docker commands. Requires Python 3.9+ and no packages.

Save each actual invocation's `docker compose ... config --format json` output
inside an envelope with `argv` (the complete acquisition argument array),
`compose_version` (the actual `docker compose version` result), and `config`
(the parsed effective output). Keep the same cwd, environment, files, profiles,
and project options as the intended invocation. For example, from the intended
working directory, capture without starting anything:

```python
import json, subprocess
argv = ['docker', 'compose', '-p', 'my_e2e', '-f', 'compose.yml',
        'config', '--format', 'json']
config = subprocess.check_output(argv, text=True)
version = subprocess.check_output(['docker', 'compose', 'version'], text=True).strip()
with open('e2e.json', 'w') as output:
    json.dump({'argv': argv, 'compose_version': version,
               'config': json.loads(config)}, output, indent=2)
```

Record relevant environment overrides alongside the envelope when capturing.
Treat these files as potentially sensitive: effective configs can contain secrets.
The tool reports acquisition argv separately from `config.name`. The effective
name already accounts for `-p`, `COMPOSE_PROJECT_NAME`, top-level `name`, defaults,
and overrides; the tool does not reimplement their precedence.

```sh
python3 tools/pm/compose_scope.py normal.json e2e.json
python3 -m unittest discover -s tools/pm -p test_compose_scope.py -v
```

Exit 0 / PASS means no collision or unresolved inspected fields were found in
these inputs. Exit 1 / FAIL means a project collision or shared storage was
observed. Exit 2 / UNKNOWN means acquisition/shape/identity information is missing
without an observed collision. FAIL can also contain unknowns. Inspect both
`findings` and `unknowns`; later errors do not erase earlier observations.
Duplicate JSON keys, malformed JSON, missing effective project names, unresolved
volume names, unsupported mounts and anonymous mounts produce unknowns.
Nonempty or malformed `volumes_from` also produces unknowns because inherited
mounts are not resolved. An empty list adds no inherited mounts.
This validates the fields it consumes, not the whole Compose/YAML schema.

- A project collision is hazardous even without a named volume: cleanup can
  stop/remove regular containers, losing in-memory state and attached anonymous
  volumes with `-v`.
- Nonexternal top-level named volumes are reported as `down -v` removal
  candidates, including explicit `name` values that cross project boundaries.
  A candidate is not proof of deletion: live users and Docker failures matter.
- External volumes and bind paths can be shared, but `down -v` does not delete
  those volumes or host directories. They still fail this conservative isolation
  check. Read-only source-code mounts can therefore require human interpretation.
  Bind paths overlap when either directory contains the other, using normalized
  POSIX path components. Findings retain both original paths. This lexical check
  does not resolve symlinks or prove the filesystem entry's type.
- Image-declared anonymous volumes and current containers are not inventoried.
  No source authenticity, same-daemon/host, simultaneous-state, symlink/path alias,
  remote-driver backing-store isolation, or complete deletion-range guarantee is
  made. Unknown driver options are reported. Matching bind paths on different
  hosts do not prove shared storage. Different names do not prove full isolation.

## Self-contained offline contrast

The examples are synthetic, not past execution captures. Split them and run:

```sh
python3 - <<'PY'
import json, pathlib
examples = json.load(open('tools/pm/compose_scope_examples.json'))
root = pathlib.Path('/tmp/compose-scope-example')
root.mkdir(exist_ok=True)
for key, value in examples.items():
    (root / (key + '.json')).write_text(json.dumps(value))
PY
python3 tools/pm/compose_scope.py /tmp/compose-scope-example/normal.json /tmp/compose-scope-example/danger.json
# exit 1: shared project and nonexternal named volume
python3 tools/pm/compose_scope.py /tmp/compose-scope-example/normal.json /tmp/compose-scope-example/isolated.json
# exit 0: distinct effective projects and named volumes
```

## Issue 126 source and experimental evidence

The fixed [old build/e2e procedure](https://github.com/j5ik2o/cqrs-es-example-js/blob/951364a284205c856e4b886179234a25f31ed182/docs/BUILD_AND_TEST.md)
invokes `pnpm docker-compose-e2e-test` and describes host-port isolation.
The [old e2e script](https://github.com/j5ik2o/cqrs-es-example-js/blob/951364a284205c856e4b886179234a25f31ed182/tools/scripts/docker-compose-e2e-test.sh)
defaults to `cqrs-es-example-js` and calls `compose down -v --remove-orphans`.
The [regular start script](https://github.com/j5ik2o/cqrs-es-example-js/blob/951364a284205c856e4b886179234a25f31ed182/tools/scripts/docker-compose-up.sh)
uses that same project. Host-port isolation does not provide cleanup isolation.
The corrected [English warning](https://github.com/j5ik2o/cqrs-es-example-js/blob/c623c1c20717e3c20f1702a45a8b86b37825eb76/docs/LOCAL_RUNTIME_CONFIG.md)
and [Japanese warning](https://github.com/j5ik2o/cqrs-es-example-js/blob/c623c1c20717e3c20f1702a45a8b86b37825eb76/docs/LOCAL_RUNTIME_CONFIG.ja.md)
explicitly describe e2e data deletion. That commit adds documentation; it does
not isolate the scripts. No product or other-repository edit is needed to add
this manual detector; changing the actual JS lifecycle is a separate decision.

Implementation verification used Python 3.9.6 and 3.15.2, Docker Compose v5.6.1
and Docker Engine 29.9.2. Fixed old/corrected source files were obtained through
GitHub's primary API and rendered with current Compose. Both retain project
collision; changing only `-p` still reports shared bind paths. Historical cwd,
environment and saved runtime config were unavailable: these are reconstructions,
not recovery of the original execution or proof of its precise deletion range.

Live controls used only two newly created random-prefix fixture projects with
one BusyBox container and one nonexternal named volume each, no network or host
mounts. The negative control used the normal-role project for e2e cleanup:
its nonce marker was readable before `down -v`, and its volume was absent after.
The positive control used distinct projects: after e2e `down -v`, the normal-role
volume existed and its exact marker remained readable. These demonstrate the
danger class; the named-volume fixture does not reproduce the full JS stack or
its image-declared anonymous volumes. No original stack command was executed.

Before cleanup, container IDs, ownership nonce labels, Compose project labels,
mount identities and volume users were checked against a local manifest. All
fixture containers and volumes were verified absent after cleanup. The rerun
script, manifest, acquisition argv/configs, raw inspect/operation results, source
snapshots, CLI outputs and mutation assertion are local evidence under
`/tmp/pm-compose-scope/` (not committed). Tests also prove that removing the
project-collision guard makes the project-only contrast fail with exit 0 instead
of expected exit 1; an exception or zero tests is not counted as detection.
Independent review and acceptance belong to the PM.
