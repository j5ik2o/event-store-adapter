# Check the rendered ADR0009 peer cell

Run this manual check when a source table looks correct but GitHub might truncate a pipe-containing expression. It reads saved HTML without network access. Python 3.9 or later and its standard library are sufficient. No CI or publication behavior changes.

## Run the offline controls

From the repository root, run:

```sh
python3 tools/pm/rendered_table_check.py --language en --example positive
python3 tools/pm/rendered_table_check.py --language ja --example positive
python3 tools/pm/rendered_table_check.py --language en --example negative
python3 tools/pm/rendered_table_check.py --language ja --example negative
python3 -m unittest discover -s tools/pm -p test_rendered_table_check.py -v
```

The positive examples return JSON `PASS` and exit 0. The negative examples return `FAIL` and exit 1 because the complete expression is absent. These are synthetic HTML controls bundled in `rendered_table_examples.json`. They require no author files, GitHub access, or Markdown renderer. The tests also mutate counts, versions, cell placement, and duplicates.

To replay saved HTML, run:

```sh
python3 tools/pm/rendered_table_check.py --language en --html saved-en.html
python3 tools/pm/rendered_table_check.py --language ja --html saved-ja.html
```

## Acquire the historical public controls

Acquisition is separate from validation. The following optional command uses authenticated `gh` and sends only freshly fetched public repository source to GitHub's Markdown API. It accepts no local document input. It saves requests, original Markdown, raw HTML, process results, timestamps, and hashes in a new `rendered-table-evidence` directory. Run it from the repository root.

```sh
python3 - <<'PY'
import base64, datetime, hashlib, json, pathlib, subprocess
root = pathlib.Path('rendered-table-evidence')
root.mkdir(exist_ok=False)
manifest = []
def run(name, argv):
    process = subprocess.run(argv, capture_output=True)
    (root / (name + '.stdout')).write_bytes(process.stdout)
    (root / (name + '.stderr')).write_bytes(process.stderr)
    (root / (name + '.run.json')).write_text(json.dumps({
        'argv': argv, 'exit': process.returncode,
        'time': datetime.datetime.now(datetime.timezone.utc).isoformat()}))
    if process.returncode:
        raise SystemExit('acquisition failed: ' + name)
    return process.stdout
repo = 'j5ik2o/event-store-adapter'
if json.loads(run('repo', ['gh', 'api', 'repos/' + repo]))['private']:
    raise SystemExit('public source required')
for label, sha in [('old', '43d9ee40c2a6dbe32f4cffd6f892fb8d86d16472'),
                   ('fixed', 'c4a181a4d43bc21394bbe33ebf2887dbf73c1365')]:
    for lang, suffix in [('en', ''), ('ja', '.ja')]:
        name = label + '-' + lang
        path = 'docs/adr/0009-bound-manual-spanner-aborted-retry-waits' + suffix + '.md'
        source = base64.b64decode(json.loads(run(name + '-source', [
            'gh', 'api', 'repos/' + repo + '/contents/' + path + '?ref=' + sha]))['content'])
        (root / (name + '.md')).write_bytes(source)
        request = root / (name + '-request.json')
        request.write_text(json.dumps({'text': source.decode('utf-8'),
                                      'mode': 'gfm', 'context': repo}), encoding='utf-8')
        html = run(name + '-render', ['gh', 'api', 'markdown', '--method', 'POST',
                                     '--input', str(request)])
        (root / (name + '.html')).write_bytes(html)
        manifest.append({'name': name, 'sha': sha, 'path': path,
                         'source_sha256': hashlib.sha256(source).hexdigest(),
                         'html_sha256': hashlib.sha256(html).hexdigest()})
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
PY
```

Replay each `old-*.html` and `fixed-*.html` with the offline command above. Expect old English and Japanese to fail and fixed English and Japanese to pass. An acquisition error is not a negative control. The old render can retain two cells while losing the second alternative, so cell counts alone do not prove preservation. Do not send private or arbitrary local Markdown to the API.

## Declared contract and limits

`rendered_table_examples.json` declares each language's exact two header texts, four rows including the header, and two cells per row. It requires exactly one matching table. Row 3, column 1 must contain exactly one complete `code` element with semantic text `^8.7.1 || ^9.0.0`. Coordinates are zero-based. Row 3's first cell must uniquely identify `JS main 4f4f5b800aea89b7e880a77cc90d76929dc889bc`. This expression comes from the actual old-to-fixed ADR0009 source diff in both languages. No dependency versions are inferred.

The parser decodes HTML entities and joins inline text. Header and row-label whitespace is normalized. Code expression text must match exactly, including spaces and both alternatives. An expression in prose, another row, another column, or a separate table cannot satisfy the target cell.

A content mismatch or missing or duplicate target returns `FAIL`, exit 1. Invalid input files, invalid contracts, unbalanced table markup, nested tables, spans, and hidden or styled table content return `UNKNOWN`, exit 2. CLI usage errors also exit 2. No missing inspection becomes `PASS`. Use `--contract path.json` to supply a saved declaration with the same `contracts` schema. Review contract changes as changes to the assertion.

`PASS` covers only the declared table shape and peer cell in supplied HTML. This is a narrow semantic content check, not a complete HTML validator or a browser visibility check. It does not authenticate source or rendering, validate other tables or CSS, prove product compatibility, authorize publication, or establish merge eligibility. Hashes and provenance records support replay, not authenticity. Independent review remains separate.
