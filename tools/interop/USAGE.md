<a id="6言語で同じ-dynamodb-local-を読み書きする"></a>
# Read and write the same DynamoDB Local from 6 languages

This is a one-off verification tool that measures the interoperability of the [core contract](../../docs/spec/core-contract.md) and the [DynamoDB storage specification](../../docs/spec/storage/dynamodb.md).
It fetches the source at the specified commits pinned in `snapshots.json` and builds thin drivers for the 6 languages.
It starts DynamoDB Local with Docker and, through only each language's public API, verifies all combinations of the 6 languages' writers and the 6 languages' readers.
The results are saved in `acceptance.json`.

<a id="用意するもの"></a>
## What you need

Docker, Python 3.12 or later (boto3), Java, the Gradle 9.8 distribution, Go, Rust, Node.js 24 or later, pnpm.

<a id="実行する"></a>
## Running it

Place the output destination outside `tools/interop`.

```sh
python3 -m venv /tmp/eswa-interop-env
/tmp/eswa-interop-env/bin/pip install boto3
/tmp/eswa-interop-env/bin/python tools/interop/build.py --output /tmp/eswa-interop-build --gradle /path/to/gradle-9.8/bin/gradle
/tmp/eswa-interop-env/bin/python tools/interop/run.py --build /tmp/eswa-interop-build --output /tmp/eswa-interop-result
```

If the Java artifacts have already been obtained, you can pass that directory with `--java-artifact-directory`.
For the unit tests, run `cd tools/interop && /tmp/eswa-interop-env/bin/python -m unittest test_run -v` in the same venv.

<a id="出力"></a>
## Output

- `acceptance.json`: the results of all verifications and the exit state
- `<language>-calls.jsonl`: the calls to each language's driver and the responses
- `sdk.jsonl`: the requests and responses that the measuring side made directly with boto3 (creating tables, reading the stored items, and so on)
- `queries.jsonl`: the Query requests and responses that the driver sent to the journal, and the byte counts of the actual items
- `buildinputs.json`: the pinned values used and the fetched sources
- `build-commands.json`: the build commands, the location of the logs, the exit values, and the time taken
- `cleanup.json`: the result of the cleanup

<a id="固定する値"></a>
## Pinned values

`snapshots.json` pins the source commits, the SHA-256 of the archives, the Java jar and sources jar published on Maven Central, and the time precision for each language.
JavaScript's precision is milliseconds because its public API uses `Date`.
When you update a commit, also update the SHA-256 of the corresponding archive.
