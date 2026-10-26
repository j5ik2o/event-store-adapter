<a id="各言語の実装計画"></a>
# Implementation Plan for Each Language

This plan defines how to bring the implementation of each language into conformance with the [specification](../spec/README.md). The targets are the six repositories registered in Orca (rs, js, java, kotlin, scala, go). Terminology follows [CONTEXT.md](../../CONTEXT.md).

> The decisions IP-D1 to IP-D8 in chapter 1 were agreed with the owner one by one on 2026-10-05. When changing or adding a decision, obtain the owner's agreement one by one and rewrite the status column. The items in chapter 10 are decided in the per-language design stage. This document does not change the rules of the specification (the common contract and the storage profiles).

<a id="1-この計画で決める判断"></a>
## 1. Decisions Made by This Plan

| # | Decision | Option adopted | Main alternative | Status |
|:--|:--|:--|:--|:--|
| IP-D1 | Branch during migration and automatic release | Proceed on main. Release the fix for the current major first, then remove the scheduled run of the version bump. Release the major manually after the acceptance criteria are met (chapter 3) | Proceed on an integration branch and merge into main after completion | Agreed (2026-10-05) |
| IP-D2 | Defects to fix in the current major | Fix only defects that drop events when reading, delete the new history, or return a committed write as a failure (chapter 8) | Do not fix any; fix all defects found | Agreed (2026-10-05) |
| IP-D3 | Storage backends included in the first major | Only the core, DynamoDB, and memory. rs's Bigtable and SQLite and js's Spanner are not discontinued; after confirming how to realize the profiles, they are re-released in a minor version of the same major (chapter 4) | Release after aligning all existing storage backends | Agreed (2026-10-05) |
| IP-D4 | Memory profile | Add a short profile, agree on it, and declare conformance for memory as well. The content of the profile is agreed separately, one item at a time, in stage 0 | Treat memory as for testing without creating a profile | Agreed (2026-10-05) |
| IP-D5 | Memory implementation for the java family | Add a memory implementation to java and make it usable from kotlin and scala as well | Do not add | Agreed (2026-10-05) |
| IP-D6 | When to create the conformance test data | Create it in this repository before the implementation of each language (stage 0) | Extract it while advancing the implementation of one language | Agreed (2026-10-05) |
| IP-D7 | How to distribute the conformance test data | As with takt's templates, copy it with a version to each repository and verify the version and hash in CI (chapter 6) | git submodule; fetch from a pinned commit when running tests | Agreed (2026-10-05) |
| IP-D8 | How to provide migration of old data | For migrations whose procedure is in the specification, attach a migration tool to the library. For migrations outside the specification's scope, provide only a procedure document (chapter 7) | Only a procedure document; add out-of-scope migrations to the specification and build tools | Agreed (2026-10-05) |

<a id="2-現状2026-10-05-時点"></a>
## 2. Current State (as of 2026-10-05)

This is the result of examining main of the six repositories. No implementation conforms to the specification. Except for rs, none has the envelope model, and all six use version-based checking and logical shard keys. The gap from the specification is large, and including rs it amounts to a substantial rewrite.

| Implementation | Current version | Automatic release | Storage backends | Size (excluding tests) |
|:--|:--|:--|:--|:--|
| [rs](https://github.com/j5ik2o/event-store-adapter-rs) | v3.0.5 | Bumps the version with a daily scheduled run and publishes to crates.io from the tag | DynamoDB, Bigtable, SQLite, memory | About 3,500 lines |
| [js](https://github.com/j5ik2o/event-store-adapter-js) | v4.0.0 (2026-10-03) | Version bump is manual. Publishes a Snapshot to npm after CI succeeds on main | DynamoDB, Spanner, memory | About 2,400 lines |
| [java](https://github.com/j5ik2o/event-store-adapter-java) | v1.2.90 | Bumps the version with a daily scheduled run and publishes to Maven Central. Also publishes a Snapshot from main | DynamoDB | About 2,100 lines |
| [kotlin](https://github.com/j5ik2o/event-store-adapter-kotlin) | v1.0.510 | Same as java | Wraps java 1.2.88's DynamoDB | About 460 lines |
| [scala](https://github.com/j5ik2o/event-store-adapter-scala) | v1.0.340 | Same as java (publishes to Central Portal) | Wraps java 1.2.88's DynamoDB | About 530 lines |
| [go](https://github.com/j5ik2o/event-store-adapter-go) | v1.0.196 | Tags with a daily scheduled run (no publishing destination is registered) | DynamoDB, memory | About 1,240 lines |

<a id="21-共通する乖離"></a>
### 2.1 Common Gaps

- **Envelope**: rs has the event envelope. However, its snapshot envelope has no manifest and has a version. The other five remain in the old contract and make domain types implement a library interface (T-6). The default serializers of js and go embed metadata in the payload (T-7).
- **Checking**: All six check by the snapshot's version. The aggregate head exists nowhere (H-1 to H-4). No implementation distinguishes a skipped number as a contract violation (W-8).
- **Keys**: All six use the logical shard `${type name}-${shard number}`, and there are four kinds of hashes (rs `DefaultHasher`, java `Math.abs(hashCode)`, js a string hash with a multiplier of 31, go FNV-1a). The aid string depends on the user's stringification (T-1).
- **Reading**: Events are read with a single Query on the GSI, and reading does not continue. The part beyond 1MB is silently dropped (R-5). No strongly consistent read is done either.
- **Retention**: When the retention process fails, it is returned as a write failure (S-4). rs's DynamoDB, java, and go delete the new history rather than the old (S-2). The retention process is also run after writing only events (D-9).
- **Time and range**: js and java store occurred_at in milliseconds. go has not decided the unit. rs rejects an occurred_at outside the range, but returns an "other" error rather than a contract violation. No implementation checks as contract violations the range of seq_nr (T-9), `-` in the type name (T-11), the length of aid (T-12), or the range of occurred_at (T-13).
- **Errors**: The "configuration" category exists only in js, and "contract violation" only in rs (chapter 4 of the common contract, E-1).
- **Tests**: The tests of java, kotlin, scala, and go are only 4–5 cases of the normal path. The DynamoDB tests use LocalStack. Five use version 2.1.0, and only scala uses docker-controller-scala's default 1.0.3.

<a id="22-現行メジャーで見つかった不具合"></a>
### 2.2 Defects Found in the Current Major

The investigation only read the code; it did not reproduce the defects by running them.

| Implementation | Content | Impact |
|:--|:--|:--|
| rs, js, java, go | Reading events is cut off at one response (1MB) | Events are dropped when replaying an aggregate with many events |
| rs (DynamoDB), java, go | The retention process deletes the new history instead of the old | The new history that should be kept is lost |
| go | When the history is shorter than the retention count, a `uint32` overflow makes the Query `Limit` invalid | With a retention count of 2 or more, a committed write is returned as a failure |
| java | The filter condition of the TTL method uses the reserved word `ttl` as is. It also compares the expiry against the grace seconds rather than epoch seconds | The retention process gets a validation error. After excess entries appear, committed writes are returned as failures every time, including writes of only events |
| rs (Bigtable) | After checking the snapshot row, events are written in a separate write ([bigtable.md](../spec/storage/bigtable.md) chapter 10) | If writing events fails, a missing number is left behind |
| java | Wrongly writes an attribute named `:seq_nr`. In the asynchronous path, an optimistic-lock failure is returned as a read error | An unnecessary attribute remains. The caller cannot decide whether to retry |
| go | Panics when a response is unexpected. The memory implementation has no mutual exclusion | The process crashes. Concurrent use corrupts it |

For a defect that returns a committed write as a failure, if the caller retries, an optimistic-lock error occurs.

<a id="3-移行中のブランチと自動リリースip-d12026-10-05-合意"></a>
## 3. Branch During Migration and Automatic Release (IP-D1, Agreed 2026-10-05)

rs, java, kotlin, scala, and go bump the version and create a tag from the changes that entered main, with a scheduled run every day at 00:00 UTC. The version decision has two problems.

- The four other than scala filter commit subjects by the form `(\(.*\))?:` before deciding. A subject like `feat!:` is dropped by this filter. The decision script (`.github/semver-level.py`) also looks only at subjects, so it does not pick up `BREAKING CHANGE` in the body. With the current workflow, even a manual start cannot create a major from `feat!:`.
- The same script raises the major with just one `perf:` subject. If changes of the new contract are merged into main little by little, once a `perf:` is mixed in, an unfinished API would be released as an unplanned major within 24 hours.

scala bumps the version with `mathieudutour/github-tag-action`, so its decision rules are checked separately.

Proceed in the following order (IP-D1, agreed 2026-10-05).

1. Release the fix for the current major (IP-D2) first. Keep using the automatic release as it is. After releasing the fixed version of java, raise the dependency of kotlin and scala on java (currently pinned to 1.2.88) and release each.
2. Fix the version bump workflow. Remove the scheduled run and keep only manual starts. The decision detects subjects with `!` and `BREAKING CHANGE` in the body, and treats `perf:` as a patch. Also add an input that lets a manual start specify the stage to bump. Do not use the method of stopping the workflow in the repository settings, because it is not kept in git and cannot be reviewed.
3. Merge changes of the new contract into main with a squash merge per PR. Make main's Snapshot be published at the next major's version (such as java's `2.0.0-SNAPSHOT`). kotlin and scala refer to java's new API through this Snapshot.
4. Release the major manually, with the owner's approval, after meeting the acceptance criteria in chapter 5. After releasing, restore the scheduled run.

If, during the migration, a fix to the current major is still needed after step 1, cut a maintenance branch (such as `release/1.x`) from the last tag and release a patch from there. That requires the following changes, so make them when the need arises.

- CI runs only on PRs to main, so make it run on PRs to the maintenance branch as well.
- The version bump workflow assumes a push to main, so make it support the maintenance branch.
- Protect the maintenance branch. Chapter 2 of the repository policy covers only main, so obtain the owner's agreement as a change of policy.
- js does not attach `--tag` when publishing. If 4.x is released after the new major, npm's `latest` goes back to 4.x, so publish maintenance versions with a different tag.
- To deliver the java fix to users of kotlin and scala, also release maintenance versions of kotlin and scala.

The alternative is to proceed on a long-lived integration branch (such as `next`) and merge it into main once after completion. It does not change main's automatic release, and fixes to the current major can still be released from main during the migration. However, it costs the following effort.

- Extend CI and protection to the integration branch too (a change of the repository policy).
- Keep taking Renovate updates that enter main into the integration branch.
- For kotlin and scala to refer to java's new API, release a java pre-release (such as `2.0.0-RC.1`) by tag from the integration branch. Chapter 1 of the repository policy excludes publishing from tags from the condition of being the head of main, so this publishing is within the policy.
- Finally, merge all changes of the integration branch into main in one big PR.

<a id="結果2026-10-05"></a>
### Result (2026-10-05)

After releasing the patch versions of step 1 (chapter 8), we did step 2 in all repositories. We removed the scheduled run from the version bump workflows of rs, java, kotlin, scala, and go, and added the input `level` (auto, patch, minor, major) for choosing the stage at manual start. The decision is: major for a subject with `!` and `BREAKING CHANGE:` (`BREAKING-CHANGE:`) in the body, minor for `feat` and `revert`, and patch for everything else including `perf`. When there is nothing to decide from, it ends with a failure. We added a unit test of the decision and actionlint to each repository's CI and included them in the dependencies of `CI Success`. js has no scheduled run, so only the fix of the decision and the input `level` were put in. scala got the same rules through the configuration of `mathieudutour/github-tag-action`. On the workflow side, a subject with `!` and `BREAKING CHANGE:` or `BREAKING-CHANGE:` in the body is detected and major is specified; for the rest, the action's conventionalcommits rules apply (perf is patch), with an additional rule that makes revert minor.

| Implementation | PR |
|:--|:--|
| rs | [#244](https://github.com/j5ik2o/event-store-adapter-rs/pull/244) |
| js | [#1000](https://github.com/j5ik2o/event-store-adapter-js/pull/1000) |
| java | [#691](https://github.com/j5ik2o/event-store-adapter-java/pull/691) |
| kotlin | [#827](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/827) |
| scala | [#860](https://github.com/j5ik2o/event-store-adapter-scala/pull/860) |
| go | [#387](https://github.com/j5ik2o/event-store-adapter-go/pull/387) |

With this, a change merged into main is never published automatically. The next major is released manually, with the owner's approval, after meeting the acceptance criteria in chapter 5.

On 2026-10-13, we decided to align the first major to 5.0.0 in all languages (P-48). Setting `level` to major computes the next major from the last tag (it would become rs 4.0.0, java 3.0.0, and kotlin, scala, and go 2.0.0), so we add to the version bump workflow an input `version` that specifies the version directly, and release 5.0.0. Skipping numbers happens only this once, and from then on versions are bumped with `level`. java had set `level` to major and released 2.0.0 before this decision (its content is the same as 5.0.0).

<a id="4-進め方"></a>
## 4. How to Proceed

We proceed stage by stage. Repositories in the same stage proceed in parallel. Stage 0 and stage 1 were completed on 2026-10-05 as milestone M1 (see the results in chapters 8, 3, 4.1, and 6). The runner of the conformance test data was moved to stage 2, because the counterpart that executes the scenarios (the new API) is made in stage 2.

| Stage | Where | Content | Prerequisite |
|:--|:--|:--|:--|
| 0 | This repository | Conformance test data (chapter 6). Drafting and agreeing on the memory profile (IP-D4) | Agreement on IP-D4, IP-D6, and IP-D7 |
| 1 | Each repository | Fix the current major (chapter 8) → change release control (chapter 3). In parallel, confirm the test infrastructure (4.1) and copy the conformance test data and verify it in CI (chapter 6) | The fixes and release control can start with only the agreement on IP-D1 and IP-D2, and proceed in parallel with stage 0. Distribution of the data comes after stage 0 |
| 2 | rs, js, go, java | Runner of the conformance test data → core (envelope, checking, validation, error classification) → memory → DynamoDB → documentation. For rs, also the migration tool from v3 | Stage 1 |
| 3 | kotlin, scala | Refer to java's Snapshot and rebuild the wrapping layer on the new API | java's stage 2 |
| 4 | Each repository | Release the major, with the owner's approval, starting with those that meet the acceptance criteria (chapter 5). Release java first; kotlin and scala release after switching their dependency on java from the Snapshot to the official version | Stages 2 and 3 |
| 5 | rs, js | Re-release rs's SQLite and Bigtable and js's Spanner under the new contract (IP-D3). Also migration tools from the old layout | Confirming how to realize each profile |

The reason for temporarily removing the three storage backends in IP-D3 (agreed 2026-10-05) is as follows. For the Spanner, Bigtable, and SQLite profiles, the main decisions are agreed, but the concrete way to realize the rules remains a draft. If these were included in the first major, no language could release until that confirmation is done. This is not a discontinuation of the storage backends ([ADR-0005](../adr/0005-define-append-atomicity-by-observable-commit.md) did not adopt the option of excluding Bigtable from the scope). Until they are re-released in the new major, users can keep using the old major (rs v3, js v4).

<a id="41-試験基盤の確認"></a>
### 4.1 Confirming the Test Infrastructure

The specification presumes `ReturnValuesOnConditionCheckFailure` (D-5), which puts the old item in the transaction's cancellation reasons, and Streams of the head table (DY-12). On 2026-10-05 we checked, with the three options below, whether these can be reproduced in the test environment.

Also, the LocalStack image on Docker Hub has not run without a user account and an auth token (`LOCALSTACK_AUTH_TOKEN`) since 2026-03-23 ([LocalStack's announcement](https://blog.localstack.cloud/2026-upcoming-pricing-changes/)). There is a free tier for open-source projects and CI. Whether the versions that the current tests pin (2.1.0 for five, 1.0.3 for scala) will keep running without a token is to be checked in the next comparison.

At the start of stage 1, compare the following three options in one repository and decide the test environment for all languages.

- Use the latest LocalStack with a token of the open-source tier. The token becomes a Secret, so the owner prepares it (chapter 7 of the repository policy).
- Keep using an old version of LocalStack, pinned.
- Switch to DynamoDB Local distributed by AWS.

Even if there are rules that no option can reproduce, we do not check them on the real production service (the owner decided this on 2026-10-15; chapter 5). As a result of the comparison, all three options could reproduce all items (the result below).

<a id="比べた結果と決定2026-10-05"></a>
#### Comparison Result and Decision (2026-10-05)

With three environments, LocalStack 2.1.0, LocalStack 4.14.0 (the latest official version that runs without a token), and DynamoDB Local 3.3.1, we actually ran and checked the following six items. The comparison scripts and the measurement records are in [tools/spikes/dynamodb-emulators/](../../tools/spikes/dynamodb-emulators/README.md).

- When a TransactWriteItems containing a conditional Update and Put is cancelled, the old item appears in the relevant element of CancellationReasons (D-5)
- With Streams of the head table (NEW_IMAGE), INSERT and MODIFY can be read in order (DY-12)
- A strongly consistent Query exceeding 1MB in one partition can be read through with LastEvaluatedKey (DY-11)
- Strongly consistent reads of BatchGetItem (DY-8, DY-9)
- A sparse KEYS_ONLY GSI (D-3)
- TTL can be enabled on the attribute ttl (DY-2)

All three succeeded on all six items. So we **unify the test environment of each language to DynamoDB Local 3.3.1 and pin the image by digest (`sha256:ff89bd48ff32cd8d9be5fee8873b65b8854dc408f1afe881be6eb00247bc0dab`)**. This is because it is an official AWS image, needs no token, and does not rely on the Streams that LocalStack implements on its own. LocalStack's DynamoDB uses DynamoDB Local internally, so the result of D-5 is determined by the version of the bundled DynamoDB Local.

We did not run the latest LocalStack, which needs a token. Since the two token-free options reproduced all items, we judged that it is not necessary to prepare a Secret just to compare. When writing tests, note the following.

- The region of a DynamoDB Local Streams ARN is `ddblocal`. Do not infer the AWS region from the ARN, and specify the endpoint explicitly for the Streams client too.
- If LocalStack keeps being used, after the table becomes ACTIVE, also wait until Streams is ENABLED and an iterator can be obtained.

The current tests of the repositories (LocalStack 2.1.0 and so on) will be moved to DynamoDB Local when the tests are rewritten in stage 2.

<a id="42-言語ごとの主な作業"></a>
### 4.2 Main Work per Language

- **rs**: Add a manifest to the snapshot envelope and remove version. `persist_event_and_snapshot` receives the snapshot envelope, and reading returns the head's seq_nr. The library builds the aid string, and `KeyResolver` and the shard count are abolished. Revise the timing and failure handling of the retention process in `GenericEventStore`. Rebuild DynamoDB with three tables and the configuration item. Check with a conditional write to the head (dynamodb.md 6.1, W-8) and distinguish the way it failed with the old item (D-5). Also add paging of reads, the sparse GSI, and the pre-check of item size (D-7). Build the migration tool in dynamodb.md chapter 11. SQLite and Bigtable are removed from the new major until stage 5. Also fix the mistakes in the CHANGELOG and AGENTS.md.
- **js**: Following 4.0.0, a second major (5.0.0) will be released after a short interval. Replace the public API with the envelope and remove `version`, `expectedVersion`, and `isCreated`. Add the contract violation classification, and also classify and return failures of reading and creation. Make the serializer handle only the payload. Rebuild DynamoDB and memory. By stage 5, when Spanner is re-released, decide how to split the entry point so that Spanner is an optional dependency (the owner decided this on 2026-10-19: a separate entry `event-store-adapter-js/spanner` of the same package, with `@google-cloud/spanner` as an optional peer dependency. The original entry does not load the Spanner SDK. Chapter 10). Remove unused dependencies (`aws-sdk` v2, `moment`, `winston`).
- **java**: Rebuild the public API (synchronous and asynchronous), the error classification (add contract violation and configuration), the serializer that relies on `Class<T>`, and DynamoDB. Add the memory implementation (IP-D5). Write the tests almost from scratch. Also fix the mixed versions of the test library (Testcontainers).
- **kotlin**: Depend on java's new API with `api(...)` and use `kotlinx.coroutines`'s `await`. Fix the mistakes in the POM's name and URL and in the README's groupId.
- **scala**: Re-wrap java's new API. Add a resolver that refers to the Snapshot. Decide how to create the next major's Snapshot version with sbt-dynver. Fix the mistake in the README's groupId.
- **go**: Make the module path `/v2` (without changing the path, the Go toolchain does not accept a v2 tag). Make an API that receives `context.Context`. Stop panicking and return classified errors, and give the errors `Unwrap`. Move `pkg/common`, which is for tests, to the test side. Add mutual exclusion to the memory implementation.

<a id="5-受け入れ条件最初のメジャー"></a>
## 5. Acceptance Criteria (First Major)

A major can be released for a language when it satisfies all of the following.

1. Pass all cases of the conformance test data with DynamoDB (the test environment decided in 4.1) and memory (IP-D4). All cases means the cases that concern the storage backends released in that version. The four FNV-1a 64 cases for storage backends that use a hash (K-1 in hash.md) are reported as not applicable with a reason, because the first major has no storage backend that uses a hash, and are counted as neither success nor failure. They are run when a storage backend that uses a hash is released in stage 5 (the owner decided this on 2026-10-06). Scenarios that inject failures (such as S-4) are also run on both. If there is a storage backend into which failures cannot be injected, decide an alternative way of checking in the design stage and have the coordinator review it. CI reports the cases per rule ID.
2. The shape of the items written to DynamoDB (attribute names and types) matches the expectation of the conformance test data.
3. `CI Success` on main is green.
4. The shape of the public API is confirmed by the design-stage review and by verification in CI ([the shape of the public API](../../api-surface/README.md)) (within the scope of chapter 8 of the common contract, following the idioms of each language). Verification in CI was added on 2026-10-14, after the six languages released 5.0.0 (chapter 10). 5.0.0 was checked only by the design-stage review. There was no shape discrepancy in the main of the six languages when the verification was introduced either.
5. The README, the schema documents, and the migration guide match the new contract.
6. There is guidance for migrating from the current major (IP-D8).

When the majors of all languages are ready, run once, in this repository, a test in which a table written by one language is read and written by another language. This is because the inability to share tables was one of the motivations for creating the specification ([ADR-0001](../adr/0001-language-neutral-spec-based-on-envelope-model.md)).

On 2026-10-15, we ran this test against DynamoDB Local with the published versions (rs 5.0.2; js, java, kotlin, scala, and go 5.0.1; java is the jar on Maven Central) ([#50](https://github.com/j5ik2o/event-store-adapter/pull/50), `tools/interop/`). The reads and writes of the 36 pairs of 6 writers × 6 readers, the six languages appending in turn to the same aggregate and all languages reading it, the optimistic lock on double writes, time precision (js is milliseconds, the others nanoseconds), paging, and the attribute names and types of journal, snapshot, and head all passed. The earlier run ([#19](https://github.com/j5ik2o/event-store-adapter/pull/19), 2026-10-12) was against pre-release commits.

We do not check on the real production service. Tests of storage backends are done in local emulation environments. For DynamoDB, acceptance is judged by the tests with DynamoDB Local decided in 4.1, and that is sufficient. On 2026-10-13 the owner decided "we will not check with the real DynamoDB service before the first major", and on 2026-10-15 revised it to not checking in production regardless of the storage backend (chapter 10). Spanner and Bigtable in stage 5 are also tested with their respective emulators, and SQLite with a local file. The Spanner and Bigtable profiles have a statement that verification on the real service remains, but this rule replaces it. The profile text will be fixed when the draft rules are finalized ([#44](https://github.com/j5ik2o/event-store-adapter/issues/44), [#45](https://github.com/j5ik2o/event-store-adapter/issues/45)).

<a id="6-適合テストデータip-d6ip-d7"></a>
## 6. Conformance Test Data (IP-D6, IP-D7)

It is language-independent JSON that references rule IDs. It is placed in `conformance/` of this repository. It is created in stage 0, before the rewrite of each language (IP-D6, agreed 2026-10-05).

- **Value tables**: the construction of the aid string and the boundaries of T-11 and T-12, both ends of T-13, and the upper limit of T-9.
- **Operation scenarios**: sequences of writes and reads, and the expected results (returned values, error classification, and the rule ID included in the error message). They center on W-3 to W-9, R-1 to R-8, S-1 to S-3, and E-1 to E-3 of the common contract. Scenarios that need a storage backend failure (such as S-4) are also run on both DynamoDB and memory. For DynamoDB, only the retention process's request is made to fail with a mechanism that plugs into the SDK client (an interceptor or middleware).
- **DynamoDB scenarios**: checking the configuration item (DY-8), distinguishing the way it failed (D-5), classifying conflicts (D-6), the pre-check of item size (D-7), reads with paging (DY-11), and the retention process (dynamodb.md chapter 8). It also has the expected values of the attribute names and types of journal, snapshot, head, and the configuration item.
- **Value tables for stage 5**: the FNV-1a 64 of hash.md was included in v1 because hash.md asks for it (K-1). The fixed binary format of the envelope in ADR-0008 is not used by the first major's DynamoDB and memory, so it will be added before stage 5.
- **How to distribute (IP-D7, agreed 2026-10-05)**: As with the takt templates in chapter 8 of the [repository policy](../operations/repository-policy.md), copy the same content to each repository. Verify the copied version and hash in CI. When the data of this repository is changed, the coordinator distributes it to all repositories.

v1.0.0 was placed in [conformance/](../../conformance/README.md) on 2026-10-05. It has 30 value-table cases, 85 operation scenarios (42 for the common contract, 43 for DynamoDB), and 1 layout case, covering 54 rules. The not-applicable ones are the deleted W-5 and R-7, which is a recommendation for the caller. In addition to the schema, references, rule IDs, and manifest, the verification tool in `tools/conformance/` checks the expected values with a reference model that replays write and read scenarios as a state machine. The S-3 (expiry method) scenarios target only DynamoDB, which is consistent with the agreement on the memory profile (it does not provide the expiry method and the change feed).

v1.1.0 was placed on 2026-10-14 (the owner decided the scope). Without changing the cases of 1.0.0, we added the following.

- Two DynamoDB scenarios for DY-19 (do not use Scan; use only requests narrowed to a single aggregate). With the new observation `request_scope`, the runner checks the kinds of requests between operations and the aid of the items read and written.
- Two scenarios in which a configuration that asks for the expiry method and change feed that memory does not provide becomes a configuration error at creation (MEM-3, MEM-12, MEM-13). A language that cannot express that request in its configuration API reports "not representable" with a reason.
- The verification tool checks that all 73 rules defined by the four specification documents have either a case or a reason for being not applicable. The memory profile was also added as a source of rule definitions.

It covers 30 value-table cases, 89 operation scenarios (42 common contract, 45 DynamoDB, 2 memory), and 1 layout case, with 58 rules. It was distributed to the six languages on 2026-10-15, and the four new cases became success or not representable with a reason in the six languages (conformance status in the [repository policy](../operations/repository-policy.md)).

v1.2.0 was placed on 2026-10-15 ([#51](https://github.com/j5ik2o/event-store-adapter/pull/51). The owner narrowed the scope to MEM-2 and MEM-6). Without changing the cases of 1.0.0 and 1.1.0, we added the following.

- Two MEM-2 scenarios (`memory/stores.json`). Using the operation `createStore`, which creates a second store midway through a scenario, they check that a newly created store is empty and independent, and that an explicitly shared store shares records and the optimistic lock.
- Two MEM-6 scenarios (`memory/payload-isolation.json`). They check that after `mutateWrittenPayload`, which modifies the written payload, and `mutateReadPayload`, which modifies the retrieved result, a re-read returns the value as it was when written. An implementation that cannot express the modification in its language's types or API may report "not representable" with a reason for these two only.
- The verification tool rejects as data errors a case that modifies a position not in the written payload, a modification to the same value (a no-op), and a case that only reads a new store without writing first.

It covers 30 value-table cases, 93 operation scenarios (42 common contract, 45 DynamoDB, 6 memory), and 1 layout case, with 60 rules. It was distributed to the six languages on 2026-10-15, and the four new cases succeeded on memory in all six languages (conformance status in the [repository policy](../operations/repository-policy.md)). The MEM-6 modifications could be expressed in all six languages, so no language reported "not representable".

v1.3.0 was placed on 2026-10-17 ([#61](https://github.com/j5ik2o/event-store-adapter/pull/61) and [#62](https://github.com/j5ik2o/event-store-adapter/pull/62). The scope was agreed with the owner in [#47](https://github.com/j5ik2o/event-store-adapter/issues/47)). It bundled the three storage backends of stage 5 into one version. Without changing the cases of 1.0.0 to 1.2.0 except for `backends` in the common contract scenarios, we added the following.

- Added `sqlite`, `spanner`, and `bigtable` to `backends` of the 42 common contract scenarios.
- Configuration error scenarios for each storage backend: a configuration that asks for a capability that is not provided, and a mismatch with the configuration recorded in the storage backend. The mismatch is created by a logical configuration seeding (`seed.configuration`) written with the profile's config item names.
- Failure scenarios that can be written by injection at logical stages. For SQLite, an operation in which another connection holds the write lock (SQ-7); for Spanner, retry on abort and its limit (SPN-7) and loss of the commit response (SPN-8); for Bigtable, failure to write the journal and loss of the conditional update's response (BT-7).
- For Bigtable, a scenario that rejects with a contract violation, before writing, an append of an envelope that exceeds the per-store limit (BT-16). No failure is injected.
- A scenario of a second store that shares the same storage backend (`scenarios/stores/shared.json`).
- 10 cases of the value table of Bigtable's fixed binary format of the envelope (`values/bigtable-envelope.json`, BT-D6a).
- For memory, one scenario that checks that a shared store also shares its configuration (MEM-2. The point raised in js#1071 after 1.2.0).
- Added the SQLite, Spanner, and Bigtable profiles as sources of rule definitions. Items that depend on raw rows or SDK response shapes, truly concurrent conflicts, and the table shapes of SQLite and Spanner are left to each language's tests, with the reasons written in `coverage.json`.

It covers 40 value-table cases, 128 operation scenarios (42 common contract, 45 DynamoDB, 7 memory, 7 SQLite, 14 Spanner, 12 Bigtable, and 1 shared scenario common to the three storage backends), and 1 layout case, with 75 rules. All of the 124 rules defined by the seven specification documents have either a case or a reason for being not applicable. It was distributed to the six languages on 2026-10-19, and the scenario of sharing memory configuration succeeded in all six languages. The SQLite, Spanner, and Bigtable scenarios are reported as not applicable with a reason in all six languages because they do not provide those storage backends (conformance status in the [repository policy](../operations/repository-policy.md)).

Each repository copies `conformance/` (conversion of line endings is stopped with `.gitattributes`) and `tools/conformance/manifest.py`, and CI runs `manifest.py verify` and compares the SHA-256 of `conformance/manifest.json` (v1.0.0 is `61c26614dbbfba88eebce72cc1d2b0220218839e74dcfb64c19268f7ee2302ce`, v1.1.0 is `0e4dfe44dec0a912ed9d6b28f0634af9fd0dc840895734790e87cf96772e1d50`, v1.2.0 is `432241f3a9e45fc169b3fcdead480b505832af1eed9f4f48357210daccce84eb`, v1.3.0 is `0157c012042afa9a19f0bff509a433a4bd5ddc5b674de864a41bec453c460691`). When the data is redistributed, update these values too.

<a id="7-旧データの移行ip-d82026-10-05-合意"></a>
## 7. Migration of Old Data (IP-D8, Agreed 2026-10-05)

| Migration source | Procedure in the specification | How it is provided |
|:--|:--|:--|
| rs v3's DynamoDB | [dynamodb.md](../spec/storage/dynamodb.md) chapter 11 | Attach a migration tool to rs's new major (stage 2) |
| rs's Bigtable and SQLite, js's Spanner | The migration chapter of each profile | Attach a migration tool when the storage backend is re-released (stage 5) |
| The old DynamoDB layout of js, java, and go (including kotlin and scala) | Out of scope (end of dynamodb.md chapter 11) | Provide only a procedure document. It shows the flow of reading with the old API and rewriting with the new API |

The old layout has payloads with embedded metadata, aids that depend on the user's stringification, and millisecond times. We do not fill in lost precision or type information by guessing.

<a id="8-現行メジャーで直す不具合ip-d22026-10-05-合意"></a>
## 8. Defects to Fix in the Current Major (IP-D2, Agreed 2026-10-05)

From the table in 2.2, we fix the following three kinds of defects and release patches (IP-D2, agreed 2026-10-05). All were found by reading code, so we reproduce them with tests before fixing.

- Events are dropped (the read being cut off. rs, js, java, go)
- The new history that should be kept is deleted (rs's DynamoDB, java, go)
- A committed write is returned as a failure (go's overflow, java's TTL method)

In addition, we do the following two.

- After releasing the fixed version of java, raise the dependency of kotlin and scala on java (currently pinned to 1.2.88) and release each.
- rs v3's Bigtable missing numbers cannot be fixed with the current layout. We will call attention to it in the README and resolve it with the new layout in stage 5.

We release them in step 1 of chapter 3 (before removing the scheduled run of the version bump). rs's tests confirm as correct a wrong behavior in which the new history is not kept, so when fixing it the tests are also revised. The other defects in the table in 2.2 are resolved in the new major.

<a id="結果2026-10-05-1"></a>
### Result (2026-10-05)

We reproduced each defect with a LocalStack test before fixing it, and published the following patch versions.

| Implementation | Version | PR |
|:--|:--|:--|
| rs | 3.0.6 (crates.io) | [#243](https://github.com/j5ik2o/event-store-adapter-rs/pull/243) |
| js | 4.0.1 (npm) | [#999](https://github.com/j5ik2o/event-store-adapter-js/pull/999) |
| java | 1.2.91 (Maven Central) | [#690](https://github.com/j5ik2o/event-store-adapter-java/pull/690) |
| kotlin | 1.0.511 (depends on java 1.2.91) | [#825](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/825) |
| scala | 1.0.341 (depends on java 1.2.91) | [#859](https://github.com/j5ik2o/event-store-adapter-scala/pull/859) |
| go | v1.0.197 | [#386](https://github.com/j5ik2o/event-store-adapter-go/pull/386) |

In review (CodeRabbit), we found that TTL-method retention also counts, as part of the count, the history already marked with an expiry. If writing starts from a state in which the old version marked the new history, the history that should be kept also gets marked. Since this is a defect that loses the new history that should be kept, in rs, java, and go we fixed it to count only the history without a mark, select it from the oldest, and not extend the expiry of history that is already marked (consistent with the nature of S-3 of the common contract). In js, the decision of whether reading finishes in one page now also includes an empty `LastEvaluatedKey`. We also fixed the description of the old-style retention in rs's `docs/DATABASE_SCHEMA`.

What was reported as out of scope and not fixed is as follows, to be resolved in the new major: the mistake of java's `:seq_nr` attribute, java's and go's lack of splitting for the 25-item limit of BatchWriteItem, and the 8 existing warnings of go's staticcheck.

<a id="9-実行体制"></a>
## 9. Execution Structure

- Changes to each repository are made by the coordinator (the session of this repository) instructing workers through Orca's orchestration. Workers go as far as creating a PR, and the coordinator merges ([repository policy](../operations/repository-policy.md) chapter 6).
- The coordinator runs on Opus 5.5, and for workers we use models and harnesses other than Opus (Sonnet 5.5, GPT-6.1-Sol, Ollama Cloud and OpenCode Go) (chapter 6 of the repository policy). Actual work may be done through Orca's orchestration or through takt.
- When using takt, the division of roles follows chapter 8 of the repository policy. aidlc is not used.
- PRs are divided by the work of each stage in chapter 4, so that one PR corresponds to one group of rules.

<a id="10-設計段階で決めること"></a>
## 10. What to Decide in the Design Stage

The following points are decided in the design stage of each language, and the coordinator reviews them. Only what needs a decision is escalated to the owner.

- Whether kotlin and scala expose java's envelope types as they are, or have their own types that fit the language's idioms (decided on 2026-10-13. See "Decisions (2026-10-13)" below).
- The form of rs's migration tool (a workspace executable, or a library function).
- Handling of the change feed. Whether to include in the first major a function that builds head transitions from Streams records of the head table, and a helper for resynchronization (DY-15).
- Whether js returns read failures as a `Result` or as exceptions.
- How to split java's synchronous and asynchronous APIs, and the serializer API.
- go's package name (currently `pkg`).

<a id="決めたこと2026-10-06"></a>
### Decisions (2026-10-06)

The coordinator reviewed the design documents of rs, js, go, and java (`docs/design/next-major.md` in each repository), and the owner decided the following points.

| Item | Decision |
|:--|:--|
| Change feed | The first major includes neither a function that builds head transitions nor a helper for resynchronization (DY-15). Writes leave a record in the head table's Streams as specified, so users can read it themselves. It will be decided again when a change feed scenario is added to the conformance test data |
| rs's migration tool | Build the body of the migration as a library function, and also attach a thin executable that calls it |
| How js returns failures | In all operations of write, read, and creation, return failures as a `Result` value |
| java's public API | Make synchronous and asynchronous separate interfaces. Make the serializer a form in which the type is decided when the store is created (stop passing `Class<T>` on every call). Make all five categories of exceptions unchecked exceptions |
| go's packages | Place the envelope, error, and operation types at the module root (`eventstore`), and split by storage backend into the `memory` and `dynamodb` packages |
| FNV-1a 64 of the conformance test data | As in criterion 1 of the acceptance criteria in chapter 5, report it as not applicable in the first major |
| js's memory MEM-4 | As in the js note of MEM-4 in [memory.md](../spec/storage/memory.md), satisfy it by protecting asynchronous overlap within the same thread |

The following points follow from the specification and the already agreed rules, so the coordinator decided them. go's payload type is a generic. rs's SQLite and Bigtable are removed from the new major (IP-D3. They remain in the old major). Notification of retention process failures requires logging, as in S-4 and MEM-D7. The memory configuration is held by the storage backend, as in MEM-3 and MEM-D11.

Of the questions about the specification left in chapter 10 of the design documents, the owner decided the following four points, which change the body of the specification (P-42 to P-45 of the [agreement status of the specification](../spec/README.md)). We decided them before implementation so that the languages do not diverge in how they handle them.

| Item | Decision |
|:--|:--|
| Missing required elements of the envelope | Make it a contract violation (T-2, T-10). If the language's type cannot express the omission, no check is needed. The conformance test data is not changed, and it is checked by unit tests of the languages that can express the omission |
| When the DynamoDB cancellation has multiple reasons | Look at `TransactionConflict` first and treat it as an optimistic lock. If there is none, in the order of the head's condition failing, the journal's condition failing, and other (dynamodb.md 6.2). This is the same handling as the description of the conformance test data, so the data is not redistributed |
| `TransactionConflict` when creating the DynamoDB configuration item | Re-read with strong consistency, as with a condition failure. If the configuration item is still absent after re-reading, do not repeat; return a storage backend error (DY-8) |
| Procedure for migrating from rs v3 | Before writing to the new table, the old journal may be read to the end and the continuity check completed (dynamodb.md chapter 11) |

The following points can be read from the body of the specification, so the coordinator answered them. A missing required setting (the serializer, the table name, and so on) is a configuration error ("invalid configuration values at creation" in chapter 4). A TTL grace of 0 is allowed, a negative value is a configuration error, and no upper limit is defined (the minimum in the conformance test data schema is 0). An empty type name or empty value of an aggregate ID is allowed (the specification does not forbid it, and since the aid string contains `-`, it never becomes empty).

<a id="決めたこと2026-10-13"></a>
### Decisions (2026-10-13)

In preparing for the first major, we checked whether each language satisfies the acceptance criteria (chapter 5) ([Stage 4 Readiness](stage4-readiness.md)). In the course of it, we decided the following points.

| Item | Decision | Decided by |
|:--|:--|:--|
| Envelope types of kotlin and scala | Expose java's envelope types (`EventEnvelope`, `SnapshotEnvelope`, and so on) as they are. The wrapping layer adapts only the parts that differ by language (kotlin's nullable types and coroutines, scala's `Try`, `Future`, and `Option`). The envelope is a value type, so using it as is does not depart much from the language's idioms. Having its own types would require two-way conversion and increase the room to drift from the contract. kotlin has no design document, so this record serves as its design-stage review | Coordinator |
| Snapshot version of scala | Keep the version that sbt-dynver derives from the last tag (in the form `1.0.341-9-<commit>-SNAPSHOT`). For the official version, start the version bump workflow with the input `version` set to 5.0.0 to create the tag `v5.0.0`, and sbt-dynver derives 5.0.0 from that tag (P-48). The "way to create the next major's Snapshot version" in 4.2 is sufficiently covered by this form, so we do not build a new mechanism | Coordinator |
| Name of the common contract version | Call the specification's version "v5" ([agreement status of the specification](../spec/README.md), P-46. On the same day it was decided as "v4" and then revised) | Owner |
| Version of each language | Align each language's major number to the contract's version, and make the first major 5.0.0 in all languages (P-48) | Owner |
| Checking with the real DynamoDB service | Not done before the first major (chapter 5). On 2026-10-15 it was revised to not checking in production regardless of the storage backend | Owner |

We found that the following two points do not need to be decided.

- That js's occurred_at is in milliseconds: T-3 of the common contract says "if the language's standard time type cannot represent nanoseconds, it may be rounded to that type's precision (js's `Date` is milliseconds)", and [ADR-0003](../adr/0003-fix-storage-value-representations.md) takes the same approach. js stores in nanosecond units and documents the millisecond limit.
- JSON null at the root of the payload: java's `PayloadSerializer.deserialize` has been fixed to `@Nullable`, and the conformance case `core-json-root-values` passes on memory in rs, and on memory and DynamoDB in the other five languages. rs's DynamoDB is unverified because CI does not run the conformance tests.

<a id="決めたこと2026-10-14"></a>
### Decisions (2026-10-14)

| Item | Decision | Decided by |
|:--|:--|:--|
| Verifying the shape of the public API | Write the shape that common contract v5 requires of the public API as language-independent JSON ([api-surface/](../../api-surface/README.md), 0.1.0) and verify it in each language's CI. Prototype in go to confirm the effect, then adopt it in stages (go → js and java → rs → kotlin and scala). Whether to include it in the acceptance criteria (chapter 5) is decided after the six languages are ready. We do not adopt existing tools that generate code from an IDL, because they cannot express type arguments and each language's conventions | Owner |
| Whether to include the verification in the acceptance criteria | Include it, since the six languages are ready. We revised item 4 of chapter 5 to "confirmed by the design-stage review and by verification in CI". The verification is included in main's required check (`CI Success`) in all six languages, so we only aligned the document with the actual state. The procedure for bumping the shape's version is written in [api-surface/](../../api-surface/README.md) | Owner |

<a id="決めたこと2026-10-15"></a>
### Decisions (2026-10-15)

In deciding the next milestone, we decided the following points. The work was made into issues per task.

| Item | Decision | Decided by |
|:--|:--|:--|
| Checking on the real production service | Not done. Tests of storage backends are done in local emulation environments. For DynamoDB, tests with DynamoDB Local are sufficient (that the six items the specification presumes can be reproduced was confirmed in 4.1). Spanner and Bigtable in stage 5 are tested with their respective emulators, and SQLite with a local file. The 2026-10-13 decision "we will not check with the real DynamoDB service before the first major" was revised into a decision limited neither by period nor by storage backend | Owner |
| Scope of the storage backends of stage 5 | Only restore the storage backends each language previously had (rs's SQLite and Bigtable, js's Spanner). Do not align them across all languages; broaden later, starting with the storage backends that become necessary. The profile agreement is common to all languages, so there is no need to recreate the profiles when broadening. The issues are [#44](https://github.com/j5ik2o/event-store-adapter/issues/44) to [#47](https://github.com/j5ik2o/event-store-adapter/issues/47), [rs#309](https://github.com/j5ik2o/event-store-adapter-rs/issues/309) and [rs#310](https://github.com/j5ik2o/event-store-adapter-rs/issues/310), and [js#1067](https://github.com/j5ik2o/event-store-adapter-js/issues/1067) | Owner |
| Scope of conformance test data 1.2.0 | Only MEM-2 and MEM-6 of memory. Data needed for stage 5 is added together with stage 5 ([#41](https://github.com/j5ik2o/event-store-adapter/issues/41)) | Owner |
| Failures of non-required checks | Build a mechanism to notice when a check outside `CI Success` fails on main ([#43](https://github.com/j5ik2o/event-store-adapter/issues/43)) | Owner |
| Tests that occasionally fail | Fix the existing DynamoDB-using tests of java and go as small work separate from the milestone ([java#747](https://github.com/j5ik2o/event-store-adapter-java/issues/747), [go#446](https://github.com/j5ik2o/event-store-adapter-go/issues/446)) | Owner |
| Approval to publish fix versions | Do not approve in bulk in advance. As before, ask the owner every time before releasing | Owner |

The test in chapter 5 that reads and writes a table across languages has been done only with pre-release commits, so we will redo it with the published versions ([#42](https://github.com/j5ik2o/event-store-adapter/issues/42)).

<a id="決めたこと2026-10-19"></a>
### Decisions (2026-10-19)

After the three profiles and conformance test data 1.3.0 were ready, we decided how to proceed with the implementation of stage 5.

| Item | Decision | Decided by |
|:--|:--|:--|
| Order of implementation of stage 5 | Start rs's SQLite ([rs#309](https://github.com/j5ik2o/event-store-adapter-rs/issues/309)) and js's Spanner ([js#1067](https://github.com/j5ik2o/event-store-adapter-js/issues/1067)) side by side. rs's Bigtable ([rs#310](https://github.com/j5ik2o/event-store-adapter-rs/issues/310)) starts after the SQLite storage backend of the same crate is merged. Each storage backend proceeds in two parts: the implementation of the storage backend and its conformance tests, and the migration tool and documentation | Owner |
| js's Spanner entry | A separate entry of the same package, `event-store-adapter-js/spanner`. `@google-cloud/spanner` is an optional peer dependency, and the original entry does not load the Spanner SDK (4.2) | Owner |

<a id="進み具合と決めたこと2026-10-23"></a>
### Progress and Decisions (2026-10-23)

For all three storage backends, both the implementation of the storage backend with its conformance tests and the migration tool with documentation are ready (2026-10-22). js's Spanner migration tool was left out once because the coordinator mistakenly wrote "do not build a migration tool" in the instructions for the second half ([js#1083](https://github.com/j5ik2o/event-store-adapter-js/issues/1083)) (not the owner's decision), but it was added afterwards in line with chapter 7 (IP-D8). On 2026-10-22, with the owner's approval, we published rs as 5.1.0 (crates.io, [release](https://github.com/j5ik2o/event-store-adapter-rs/releases/tag/v5.1.0)) and js as 5.1.0 (npm, [release](https://github.com/j5ik2o/event-store-adapter-js/releases/tag/v5.1.0)). Both are versions that add features, so we raised the second number of the version. java, kotlin, scala, and go have no stage 5 changes, so we have not released versions for them.

| Storage backend | Storage backend implementation and conformance tests | Migration tool and documentation |
|:--|:--|:--|
| rs's SQLite | [rs#319](https://github.com/j5ik2o/event-store-adapter-rs/pull/319) | [rs#324](https://github.com/j5ik2o/event-store-adapter-rs/pull/324) (`migrate_v3_sqlite` of the feature `sqlite-migration`, and the SQLite arguments of the migration tool) |
| js's Spanner | [js#1081](https://github.com/j5ik2o/event-store-adapter-js/pull/1081) | [js#1084](https://github.com/j5ik2o/event-store-adapter-js/pull/1084) (documentation of the schema and initialization, and guidance for migration from v4) and [js#1088](https://github.com/j5ik2o/event-store-adapter-js/pull/1088) (`migrateV4Spanner` of the entry `event-store-adapter-js/spanner`. v4's `aggregate_id` is the result of the application's `asString()` and cannot be restored from the key, so the type name and value are restored by a restoring function that the user passes) |
| rs's Bigtable | [rs#321](https://github.com/j5ik2o/event-store-adapter-rs/pull/321) | [rs#328](https://github.com/j5ik2o/event-store-adapter-rs/pull/328) (a creation function that receives a token source) and [rs#330](https://github.com/j5ik2o/event-store-adapter-rs/pull/330) (`migrate_v3_bigtable` of the feature `bigtable-migration`, and the Bigtable arguments of the migration tool) |

| Item | Decision | Decided by |
|:--|:--|:--|
| Input for creating rs's Bigtable (first half, 2026-10-20) | Limited to a form that receives two connections, one for data and one for administration (`Channel` of tonic, the Rust gRPC library), and does not handle authentication. This cannot be used in production as is, so decide how to handle authentication before publishing a version | Owner |
| Authentication of rs's Bigtable (2026-10-21) | Add one more creation function that also receives an asynchronous token source that the user prepares. The store attaches `authorization: Bearer <token>` to all requests of the data API and the administration API. Google's authentication library is not added to the library's dependencies. The current creation function and the items of types such as the connection are not changed | Owner |
| Authentication of rs's migration tool for Bigtable (2026-10-21) | Only the migration tool, which is not published, depends on Google's authentication library and refreshes the token automatically with Google's Application Default Credentials. Authentication is skipped with the emulator's arguments | Owner |
| Display of rs's migration errors (2026-10-20) | Make the display of `MigrationError`, shared by the DynamoDB and SQLite migrations, `migration failed during …`. The word "DynamoDB" disappears from the standard-error wording of the DynamoDB migration, but the items, exit codes, and JSON report are unchanged. Adding an item that distinguishes the storage backend would break constructing a struct that has public items | Owner |
| GC of Bigtable's `config` column family (2026-10-22) | Do not add a rule; write an explanation in chapter 2 of the profile (P-60). Attaching age-based GC to `config` would remove the configuration row, and with the finalized rules every later creation would become a configuration error, so we recommend a layout without it. At first we agreed to add it as a rule of BT-2, but there is a rule (P-47, P-55) that changing a finalized rule requires raising the version of the specification or the conformance test data, so we kept it to an explanation. Found in the review of rs#330 | Owner |

In migration from v3's SQLite, the retention history remaining in the old file is migrated to match the retention count of the new file (if the retention count is n, the newest n entries per aggregate; with no retention, nothing is migrated). This is a reading that matches "do not fabricate deleted or unretained past history" in chapter 6 of the SQLite profile, and it is written in rs's migration guide.

In migration from v3's Bigtable too, the rows of the old history are migrated with the same idea. v5's Bigtable also counts head's current snapshot as part of the number of history entries (chapter 7 of the [Bigtable profile](../spec/storage/bigtable.md)), so the newest n entries are migrated from the set that aligns the positions of the old history rows and the position of the current snapshot. With no retention, nothing is migrated. It is written in rs's migration guide.

Also, the problem that Bigtable's tests occasionally fail ([rs#325](https://github.com/j5ik2o/event-store-adapter-rs/issues/325)) was fixed in [rs#333](https://github.com/j5ik2o/event-store-adapter-rs/pull/333).

The four FNV-1a 64 cases (K-1 in hash.md) are run on storage backends that use a hash, as in chapter 5. js's Spanner conformance tests have been run and succeed since [js#1081](https://github.com/j5ik2o/event-store-adapter-js/pull/1081). rs's Bigtable uses this hash for the prefix of the row key, but the conformance test runner was still reporting it as not applicable for the reason of the first major. We found this on 2026-10-23, and in [rs#337](https://github.com/j5ik2o/event-store-adapter-rs/pull/337) made Bigtable's leg run the four cases with the same hash function as the storage backend, and they succeeded. The hash function is the same as in 5.1.0, so no re-release of the version is needed. The other legs, and the languages that do not provide a storage backend that uses a hash, remain not applicable with a reason.

<a id="次のマイルストーン-文書を整える2026-10-23"></a>
### Next Milestone: Tidy the Documentation (2026-10-23)

After stages 0 to 5 were all done, the owner and the coordinator decided, one question at a time, to make the next milestone "Tidy the documentation".

| Item | Decision | Decided by |
|:--|:--|:--|
| Theme | Tidy the documentation | Owner |
| Language of documents | English is the default and canonical (`X.md`). Japanese documents are auxiliary (`X.ja.md`) and follow the English. When they differ, follow the English | Owner |
| User-facing and developer-facing | Separate them. Do user-facing first, and developer-facing in the second half of this milestone. Developers are the people who commit to this project (currently only the owner), and users are developers who use the library | Owner |
| Set of user-facing documents | For all six languages, three kinds: the README, the schema document for each storage backend provided, and the migration guide. Align the file names, locations, and section structure; only the language-specific code and setup procedures differ | Owner |
| The template to align to | Place the canonical source in this repository and verify each repository against it ("Verifying the User-Facing Documentation" in chapter 1 of the [repository policy](../operations/repository-policy.md)) | Owner |
| Developer-facing documents | Same language rules as user-facing. Includes this repository's specification, plan, repository policy, ADRs, and glossary, and the files of instructions to agents (CLAUDE.md, AGENTS.md, and so on). The specification is treated as developer-facing | Owner |
| Records of finished designs | Each language's `docs/design/next-major.md` is kept as a developer-facing document, separate from user-facing ones | Owner |
| Publishing | When a language has finished aligning its user-facing documents, ask the owner about a patch release (go has no package registry and pkg.go.dev reads the tagged commit, so a tag is attached) | Owner |
| Order of languages | Try the template with rs, which has the most documents, and then proceed with the remaining five languages side by side | Coordinator (reported to the owner) |
| Content of the section structure | The template file itself (`user-docs/template.json`) is the content, and it is shown to the owner in that PR | Coordinator (reported to the owner) |
| Completion condition | For each language: the template verification passes in a job in the dependencies of `CI Success`, the three kinds of documents are ready in English and Japanese, and the coordinator's review confirms that the body, excluding language-specific code and setup procedures, corresponds across the six languages and that the Japanese has the same content as the English (the verification tool does not look at the body), and a patch version is released (or the owner's judgment not to release is obtained). The milestone is complete when the six languages are ready and the second half for developer-facing is done | Coordinator (reported to the owner) |
| Documents outside the template | Historical materials such as rs's migration guide for the 3 line may be kept if listed in each repository's configuration. For a document whose name was changed, leave at the old path a short file that only points to where it moved, so that links from published READMEs are not broken | Coordinator (reported to the owner) |

The progress as of 2026-10-26 is as follows. For the user-facing documents, the template verification and content check are done for all six languages. rs has published 5.1.1 ([rs#339](https://github.com/j5ik2o/event-store-adapter-rs/pull/339)). The remaining five languages were merged on 2026-10-25 ([js#1096](https://github.com/j5ik2o/event-store-adapter-js/pull/1096), [java#765](https://github.com/j5ik2o/event-store-adapter-java/pull/765), [kotlin#877](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/877), [scala#898](https://github.com/j5ik2o/event-store-adapter-scala/pull/898), [go#460](https://github.com/j5ik2o/event-store-adapter-go/pull/460)). We published js 5.1.1 and go 5.0.2 and confirmed that the tidied documents are included in the distributed artifacts. For java, kotlin, and scala, the owner chose not to publish a stable version only for documentation. The tidying of developer-facing documents is in progress, and the milestone is not yet complete.

<a id="全言語で全保存先を提供する2026-10-26"></a>
### Provide All Storage Backends in All Languages (2026-10-26)

On 2026-10-26 the owner said "全部サポートしてほしい。" ("I want all of them supported.") and showed a table of memory, DynamoDB, SQLite, Spanner, and Bigtable. The target is to provide all five storage backends in each of the six languages (rs, js, java, kotlin, scala, and go), 30 combinations in total. The 15 combinations that were not provided until now are treated as unimplemented remaining work. This widens the "Scope of the storage backends of stage 5" in [Decisions (2026-10-15)](#決めたこと2026-10-15) (only restore the storage backends each language previously had, and broaden later, starting with the storage backends that become necessary). The earlier line is kept as the record of that time. The current state is not "all 30 combinations are implemented". The 15 combinations marked "Implemented" below and the reports of their success are kept as they are.

State as of 2026-10-26:

| Language | Memory | DynamoDB | SQLite | Spanner | Bigtable |
|:--|:--|:--|:--|:--|:--|
| rs | Implemented | Implemented | Implemented | Remaining (independent implementation) | Implemented |
| js | Implemented | Implemented | Remaining (independent implementation) | Implemented | Remaining (independent implementation) |
| java | Implemented | Implemented | Remaining (independent implementation) | Remaining (independent implementation) | Remaining (independent implementation) |
| kotlin | Implemented | Implemented | Remaining (support that uses java's implementation) | Remaining (support that uses java's implementation) | Remaining (support that uses java's implementation) |
| scala | Implemented | Implemented | Remaining (support that uses java's implementation) | Remaining (support that uses java's implementation) | Remaining (support that uses java's implementation) |
| go | Implemented | Implemented | Remaining (independent implementation) | Remaining (independent implementation) | Remaining (independent implementation) |

Of the 30 combinations, 15 are implemented and 15 remain. The 15 remaining combinations are split into 9 independent storage backend implementations (rs 1, js 2, java 3, go 3) and 6 combinations of kotlin and scala that use java's implementation (3 storage backends each).

| Item | Decision | Decided by |
|:--|:--|:--|
| Target | All five storage backends in all six languages (30 combinations). The 15 combinations not provided until now are unimplemented remaining work | Owner |
| Version of takt | Use the latest. 0.72.0, the latest on npm, is used. The pin of 0.68.0 is updated in this working tree, and takt is not started with the old version | Owner |
| Rewriting flash-default | Allowed ("書き換えていいよ flash-default"). The body of flash-default and the child workflows it needs may be updated to match the latest takt. The existing division of models is kept | Owner |
| How the remaining work is split | 9 independent storage backend implementations (rs 1, js 2, java 3, go 3) and 6 combinations of kotlin and scala that use java's implementation | Coordinator (reported to the owner) |
| The unit of the first verification | The first one, java's SQLite, is one unit of verification. Only after its conformance tests, documentation, and review hold, broaden to the other implementations. The implementations of the same repository are not edited at the same time. In principle, up to 4 pieces of work run in parallel | Coordinator (reported to the owner) |
| How the work is run | Delegate to takt in an independent working tree managed by Orca, using flash-default. Planning is Opus 5.5, implementation and tests are Sonnet 5.5, and review is Sonnet 5.5, DeepSeek V4.1 Flash, and GLM 5.3 Flash | Coordinator (reported to the owner) |
| What is not changed | Common contract v5, the profile of each storage backend, conformance test data 1.3.0, and the definition of the shape of the public API. The rules and the distributed data are not changed for convenience | Coordinator (reported to the owner) |
| Where tests run | Only on local SQLite files and on the emulators of DynamoDB Local, Spanner, and Bigtable. Do not connect to real services. This follows the owner's decision of 2026-10-15 (checking on the real production service is not done) | Owner (2026-10-15) |
| Out of scope for now | Migration of production data, publishing libraries, and releasing new stable versions are handled after the finished deliverables are shown. Adding a change feed is not mixed into this addition of storage backends | Coordinator (reported to the owner) |

Completion conditions (conditions for the future; they do not describe the current state):

- All five storage backends can be used from each of the six languages.
- Conformance tests against the corresponding real local storage backend (SQLite files) or emulator (DynamoDB Local, Spanner, Bigtable) finish with 0 failures and 0 unverified.
- The documents are aligned in English and Japanese.
- A whole storage backend is not excluded from the conformance tests, and the work is not accepted, on the grounds that it is not provided. A legitimate exclusion, such as an input that cannot be expressed in the language's types or a scene where the storage backend differs, is kept separately with its reason.

As of 2026-10-26, the coordinator started java's SQLite with takt 0.72.0. The remaining combinations are not yet implemented.

<a id="11-リスクと対策"></a>
## 11. Risks and Countermeasures

| Risk | Countermeasure |
|:--|:--|
| The test environment does not reproduce D-5 or Streams | Check first with the comparison in 4.1, and change the test environment or the checking procedure |
| New versions of LocalStack need an auth token | In the comparison in 4.1, choose among the token, an old version, and DynamoDB Local |
| js users receive two breaking changes in a short interval | Summarize the differences from 4.0 in the migration guide |
| During the migration, the current major cannot be released from main | Release the main fixes before removing the scheduled run. Fixes needed after that are released on a maintenance branch (chapter 3) |
| Renovate updates conflict with the rewrite's PRs | During stage 2, defer taking in major updates until after the rewrite |
| The workload for java, go, and js is large | Split PRs by stage in chapter 4 and proceed in parallel |
| CodeRabbit's free-tier limit stops reviews (it happened many times on 2026-10-05) | For code PRs, wait for CodeRabbit's result. Documentation PRs proceed with the coordinator's review and an independent review (a non-Opus subagent) |
| A Claude Code worker stops at the confirmation screen for the pre-approval of `.claude/settings.json` in a new worktree | Start workers with Codex (GPT-6.1-Sol). If Sonnet 5.5 is used, decide first how to get past this confirmation |
