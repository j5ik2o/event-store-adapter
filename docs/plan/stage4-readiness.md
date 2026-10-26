<a id="段階-4-の準備状況"></a>
# Stage 4 Readiness

This is the record of checking whether each language's first major release satisfies acceptance criteria 1–6 in chapter 5 of the [implementation plan](implementation-plan.md). The owner approves whether to release the major version, language by language (stage 4 in chapter 4).

<a id="確かめ方2026-10-13"></a>
## How We Checked (2026-10-13)

We read origin/main of each repository and looked at the CI run records and artifacts. We did not build or run tests locally. A Sonnet 5.5 worker did the investigation per language, and the coordinator verified the results.

| Language | Commit checked |
|:--|:--|
| rs | `d442caa` |
| js | `c4e794a` |
| java | `96689fb` |
| kotlin | `0a57b83` |
| scala | `719a491` |
| go | `e80385d` |

<a id="結果"></a>
## Results

The table below is the judgment before the fixes (at the time of checking, 2026-10-13). The state after the fixes is in "Results of the Fixes (2026-10-13)"; all six languages satisfy acceptance criteria 1–6.

| Language | 1. Conformance test data | 2. Item shape | 3. CI | 4. Public API design | 5. Documentation | 6. Migration guidance |
|:--|:--|:--|:--|:--|:--|:--|
| rs | Not satisfied | Partly | Satisfied | Satisfied | Partly | Satisfied |
| js | Partly | Satisfied | Satisfied | Satisfied | Partly | Satisfied |
| java | Satisfied | Satisfied | Satisfied | Satisfied | Partly | Satisfied |
| kotlin | Partly | Satisfied | Satisfied | Satisfied | Partly | Satisfied |
| scala | Partly | Satisfied | Satisfied | Satisfied | Partly | Satisfied |
| go | Satisfied | Satisfied | Satisfied | Satisfied | Partly | Satisfied |

The "Partly" for criterion 5 includes that the name of the common contract version (the name of the common contract version in P-46) was not yet aligned. For kotlin and go, there are no other gaps.

<a id="適合テストデータの件数"></a>
### Conformance Test Data Counts

In all languages, the hash of the copied conformance test data matches the v1.0.0 value and is verified in CI. DynamoDB Local is pinned by digest (rs has code that pins it, but the DynamoDB slot of its CI does not start DynamoDB Local). The four FNV-1a 64 cases (K-1 in hash.md) are marked not applicable with a reason in all languages.

| Language | Memory (passed, failed, not applicable, unverified) | DynamoDB (passed, failed, not applicable, unverified) | Report per rule ID |
|:--|:--|:--|:--|
| rs | 58・0・58・0 | 9・0・14・93 | In the CI artifacts |
| js | 60・0・56・0 | 104・0・12・0 | In the report JSON, but CI does not save it |
| java | 60・0・56・0 | 104・0・12・0 | In the CI artifacts |
| kotlin | 60・0・56・0 | 104・0・12・0 | In `report.json`, but CI does not save it |
| scala | 60・0・56・0 | 104・0・12・0 | In `report.json`, but CI does not save it |
| go | 60・0・56・0 | 104・0・12・0 | In the CI artifacts |

The 93 unverified DynamoDB cases in rs are because CI runs the runner without the DynamoDB capability. There is no `--require-all` either, so CI stays green. The behavior of rs's DynamoDB support is checked by the interoperability test in [PR #19](https://github.com/j5ik2o/event-store-adapter/pull/19), but not by the conformance test data.

<a id="不足と対応"></a>
## Gaps and Responses

| Language | Gap | Response |
|:--|:--|:--|
| rs | CI does not run the DynamoDB slot of the conformance tests. The tests of the runner and of the migration executable also do not run in CI | [rs#289](https://github.com/j5ik2o/event-store-adapter-rs/issues/289) |
| rs | `AGENTS.md` is still in the old layout. The v3 migration guide has no note for the old version. The design document has no migration module | [rs#290](https://github.com/j5ik2o/event-store-adapter-rs/issues/290) |
| js | The report per rule ID is not visible from CI. The migration guide still has a sentence that is a work instruction. The migration guide for the old version has no note. Issue #1017 is still open | [js#1049](https://github.com/j5ik2o/event-store-adapter-js/issues/1049) |
| java | The unresolved question Q7 in the design document (the order of the SDK's `ExecutionInterceptor` and how it maps to request observation) is still unresolved after the implementation. The design-time statement "the current tests use LocalStack" remains | [java#730](https://github.com/j5ik2o/event-store-adapter-java/issues/730) |
| kotlin | The report per rule ID is not visible from CI | [kotlin#846](https://github.com/j5ik2o/event-store-adapter-kotlin/issues/846) |
| scala | The report per rule ID is not visible from CI | [scala#871](https://github.com/j5ik2o/event-store-adapter-scala/issues/871) |
| go | staticcheck is not run in CI (chapter 8 said the warnings of the current major would be resolved in the new major) | [go#431](https://github.com/j5ik2o/event-store-adapter-go/issues/431) |

Aligning the name of the common contract version is included in the responses for each language above.

<a id="対応の結果2026-10-13"></a>
## Results of the Fixes (2026-10-13)

The gaps above were fixed with takt (launched from Orca), and the coordinator verified the diffs, CI, and artifacts before merging. After merging, `CI Success` on main is green for all six languages.

| Language | PR | Result |
|:--|:--|:--|
| rs | [rs#292](https://github.com/j5ik2o/event-store-adapter-rs/pull/292) | The DynamoDB slot of the conformance tests now runs against DynamoDB Local with the DynamoDB capability, and `--require-all` was added to both slots. DynamoDB: of 116 cases, 102 passed, 0 failed, 14 not applicable, 0 unverified; memory: 58 passed, 0 failed, 58 not applicable, 0 unverified. The tests of the runner and of the migration executable also run in CI |
| rs | [rs#291](https://github.com/j5ik2o/event-store-adapter-rs/pull/291) | Rewrote `AGENTS.md` to match the current layout, added a note for the old version to the v3 migration guide, and added the public name of the migration to the design document |
| js | [js#1050](https://github.com/j5ik2o/event-store-adapter-js/pull/1050) | Keeps the conformance test report as a CI artifact and writes a table per rule ID to the job summary. Removed the work-instruction sentence from the migration guide and added a note to the migration guide for the old version. The five items of Issue #1017 were closed after confirming that the corresponding conformance cases pass |
| java | [java#732](https://github.com/j5ik2o/event-store-adapter-java/pull/732) | Resolved Q7 in the design document (the order of the SDK's interceptors and how it maps to request observation), with evidence from the implementation and tests. Fixed the LocalStack statement to DynamoDB Local |
| kotlin | [kotlin#847](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/847) | Keeps the conformance test report per JDK as a CI artifact and writes a table per rule ID to the job summary |
| scala | [scala#872](https://github.com/j5ik2o/event-store-adapter-scala/pull/872) | Keeps the conformance test report per JDK and Scala version as a CI artifact and writes a table per rule ID to the job summary |
| go | [go#432](https://github.com/j5ik2o/event-store-adapter-go/pull/432) | Added staticcheck to CI with a pinned version and fixed one warning |

The table per rule ID that js, kotlin, and scala write to the job summary shows all states (passed, failed, not applicable, unverified, not representable value) as columns and adds the reasons for not applicable and not representable values. The four FNV-1a 64 cases (K-1) appear in the table as not applicable with a reason. rs, go, and java have always kept the results per rule ID in the report artifacts of CI. The name of the common contract version was aligned to "common contract v4" in all six languages and linked to the hub's specification. After this, we decided to rename the contract to v5 and align each language's version to 5.0.0 (P-46, P-48).

With this, all six languages satisfied acceptance criteria 1–6. However, because the contract was renamed to v5 afterwards (P-46), criterion 5 is not satisfied until each language's documentation is fixed to "common contract v5". The work to fix it was done in the PR that prepares the release of 5.0.0 (the same PR as the one that adds the input `version` to the version bump workflow), and as shown in "Results of Publishing" below, it was done for all six languages.

<a id="公開の結果2026-10-13"></a>
## Results of Publishing (2026-10-13)

With the owner's approval, we released the first major version of the six languages as 5.0.0 (P-48). In each language, we merged a preparation PR that adds the input `version` to the version bump workflow, and then started it with `version=5.0.0`. We released java first and confirmed that it was reflected on Maven Central; then we switched the dependency of kotlin and scala on java to 5.0.0 and released them.

| Language | Preparation PR | Published to | What we confirmed |
|:--|:--|:--|:--|
| java | [java#735](https://github.com/j5ik2o/event-store-adapter-java/pull/735) | Maven Central | The pom of `event-store-adapter-java` 5.0.0 can be fetched. main is `5.0.1-SNAPSHOT` |
| rs | [rs#294](https://github.com/j5ik2o/event-store-adapter-rs/pull/294) | crates.io | The latest version is 5.0.0 |
| js | [js#1052](https://github.com/j5ik2o/event-store-adapter-js/pull/1052) | npm | `latest` is 5.0.0 |
| go | [go#434](https://github.com/j5ik2o/event-store-adapter-go/pull/434) | Go proxy | Changed the module path to `/v5`. The information for `v5.0.0` can be fetched |
| kotlin | [kotlin#851](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/851), [kotlin#853](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/853) (dependency on java 5.0.0) | Maven Central | The pom of `event-store-adapter-kotlin` 5.0.0 can be fetched |
| scala | [scala#874](https://github.com/j5ik2o/event-store-adapter-scala/pull/874), [scala#875](https://github.com/j5ik2o/event-store-adapter-scala/pull/875) (dependency on java 5.0.0) | Maven Central | The poms of 5.0.0 for Scala 2.13 and 3 can be fetched |

All six languages have a v5.0.0 release on GitHub. java's 2.0.0 is a version released before the decision to align versions, and its content is the same as 5.0.0. The README and the description of the 2.0.0 GitHub release direct users to use 5.0.0.

<a id="適合テストデータの外の規則の確認と-5012026-10-13"></a>
## Checking Rules Outside the Conformance Test Data, and 5.0.1 (2026-10-13)

After releasing 5.0.0, we checked, in the v5.0.0 code and tests of the six languages, the 25 rules that conformance test data 1.0.0 does not cover among the 71 rules defined by the v5 specification (read-only). kotlin and scala leave the implementation to java, so we looked at them together with java.

The 71 are 45 rules of the common contract, 13 of DynamoDB, and 13 of memory. On 2026-10-14, the hashes used for keys, K-1 and K-2, were also finalized in v5 ([the specification](../spec/README.md), P-49), so v5 now has 73 rules. Both are not applicable to the first major release, which has no storage backend that uses hashes. K-1 is covered by four cases of the conformance test data, which all six languages report as not applicable. K-2 (do not divide the hash value by the shard count) is not covered by the conformance test data. This check was done before P-49, so K-1 and K-2 are not included in the numbers.

| Language | Satisfied (with tests) | Satisfied (code only) | Partly | Not satisfied | Not applicable |
|:--|--:|--:|--:|--:|--:|
| rs | 10 | 4 | 3 | 0 | 8 |
| js | 13 | 1 | 3 | 0 | 8 |
| java (including kotlin and scala) | 13 | 3 | 1 | 0 | 8 |
| go | 13 | 2 | 2 | 0 | 8 |

The 8 not-applicable rules are the rules about the change feed and Streams, which the first major release does not provide (F-1 to F-5, the generation of head transitions and the obligations of the subscribing side; DY-13, how to read Streams records; DY-15, resynchronization), and the obligation on the specification side to write the premises in the profile (SP-1). We fixed the gaps we found in 5.0.1, with the owner's approval.

| Gap | What we fixed | PR |
|:--|:--|:--|
| rs's memory backend does not make a TTL without a retention count a configuration error (inconsistent with MEM-3 and MEM-12) | Every TTL specification is a configuration error. Added `MemoryTtlUnsupported` to the reasons | [rs#296](https://github.com/j5ik2o/event-store-adapter-rs/pull/296) |
| js's memory backend does not make an unregistered backend or an unexpected configuration a configuration error at creation (MEM-1, MEM-3) | Configuration error at creation | [js#1054](https://github.com/j5ik2o/event-store-adapter-js/pull/1054) |
| go's memory backend accepts an unknown retention method value (MEM-3). `-race` is not run | Made it a configuration error. Made the CI tests run with `-race` | [go#436](https://github.com/j5ik2o/event-store-adapter-go/pull/436) |
| java's memory backend throws `NullPointerException` for a null backend | Made it `ConfigurationException`. Added tests for modifying values (JSON payloads) and for concurrent calls of the asynchronous store | [java#737](https://github.com/j5ik2o/event-store-adapter-java/pull/737) |
| None of the six languages documents the single-region premise (DY-18) and the single-process premise (MEM-1) | Added the same wording to the README and the schema document in all six languages | The four above, plus [kotlin#854](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/854) and [scala#876](https://github.com/j5ik2o/event-store-adapter-scala/pull/876) |

All six languages released 5.0.1 (kotlin and scala depend on java 5.0.1). DY-19 (do not use Scan; use only requests narrowed to a single aggregate) is satisfied by the implementation in all six languages, but there is no test that checks it directly, so we cover it in the extension of the conformance test data (1.1.0). 1.1.0 was placed in the hub on 2026-10-14 (chapter 6 of the implementation plan).

<a id="メジャーを出すときにやること"></a>
## What to Do When Releasing the Major Version

- As in chapter 4, release java first, and release kotlin and scala after switching their dependency on java from `2.0.0-SNAPSHOT` to the official java 5.0.0 (P-48).
- Start the version bump workflow with the input `version` set to 5.0.0 (P-48; chapter 3 of the implementation plan).
- For rs, replace `[Unreleased]` in the CHANGELOG with the version heading (the procedure for 5.0.0. Since 2026-10-15 the CHANGELOG is not updated, and the record of changes is only the release notes. See "Release notes" in chapter 1 of the repository policy).
- For java, kotlin, and scala, fix the descriptions of the Snapshot version in the README and elsewhere, and the guidance on the Snapshot repository. The README of kotlin and scala still has a provisional description of the version to install.
- java's version bump and publication to Maven Central succeed for the first time with 2.0.0.

<a id="気づき範囲外"></a>
## Observations (Out of Scope)

- scala's CI has an hourly scheduled run (introduced in commit `eb6b383` on 2023-09-12). It publishes a Snapshot every time CI succeeds.
- go's version bump workflow pushes the version-bumping commit to main. It was able to push to main in this form for v1.0.197 on 2026-10-05 as well (commit `1054cf2`).
- js, go, java, kotlin, and scala have no CHANGELOG. The version bump workflow creates the release notes. rs also stops updating its CHANGELOG from 5.0.2 (see "Release notes" in chapter 1 of the repository policy).
