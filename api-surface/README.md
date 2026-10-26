<a id="公開-api-の形"></a>
# Public API shape

This is the "shape" that core contract v5 requires of each language's public API, written in language-independent JSON. Each language checks in CI whether its own public API satisfies this shape.

**Status: the check has been introduced in all 6 languages and made an acceptance condition (0.1.0, 2026-10-14).** On 2026-10-14 we prototyped the check in go and confirmed that it can detect deviations ([hub PR #28](https://github.com/j5ik2o/event-store-adapter/pull/28)). The owner decided on a phased adoption, and on the same day the check was introduced into the CI of all 6 languages (see "How each language performs the check" below). After all 6 languages were in place, the owner decided to include the check in the acceptance conditions (item 4 of chapter 5 of the [implementation plan](../docs/plan/implementation-plan.md)). The `status` of `surface.json` remains `experimental`. Changing it changes the SHA-256 and requires redistributing to the 6 languages, so it will be changed to `stable` the next time the version is raised (see "Procedure when raising the version" below).

<a id="何を書くか何を書かないか"></a>
## What is written and what is not

What is written is only what the specification decides regardless of language.

- The elements of the two envelopes, and the elements required at construction (1.2 and 1.4, T-2 and T-10)
- The pair returned by reading the latest snapshot (3.4, R-2)
- The inputs and outputs of the store's four operations (chapter 3)
- The five error categories (chapter 4, E-1)

What is not written is what the specification leaves to each language.

- The spelling of names (`persist_event` / `persistEvent` / `PersistEvent`)
- How failure is returned (`Result`, exceptions, an `error` value), and whether it is asynchronous
- How a pair is represented (a struct, a tuple, and so on), and how "none" is represented (`Option`, `null`, `undefined`, a pointer)
- Arguments added by the conventions of the language (such as go's `context.Context`)

Behavior (the conditions of checking, retention, error categories, and so on) cannot be expressed in this shape. Behavior is verified with the [conformance test data](../docs/conformance-guide.md).

<a id="書き方"></a>
## Notation

| Notation | Meaning |
|:--|:--|
| `P`, `A` | Types decided by the user (the event payload, the aggregate state). Expressed with the language's type parameters |
| `aggregate_id`, `seq_nr`, `timestamp`, `string` | Kinds of values. Their meanings are written in `value_types` |
| `optional<T>` | `T` is present or absent |
| `list<T>` | A sequence of `T` (ordered) |
| `none` | There is no value to return on success |
| `required: true` | An element that must always be given at construction. `required: false` can be omitted, and when omitted it takes the value of `default` |

<a id="各言語での照合"></a>
## Checking in each language

The repository of each language has the following two.

1. A copy of this `surface.json` (`api-surface/surface.json`). CI confirms that it matches the SHA-256 below (distributed in the same way as the conformance test data).
2. A name mapping table (such as `api-surface/<言語>.json`, where `<言語>` is the language). It maps the common names (`event_envelope`, `occurred_at`, and so on) to the names and types of that language's public API. The mapping table is placed only in each language's repository, and the hub does not hold it.

The checking tests confirm at least the following.

- Each type exists, along with a means of reading its elements (fields, getter functions, and so on). The element types match the kinds of values.
- The means of construction (a function, a builder, and so on) always accepts the elements with `required: true`, and can omit the elements with `required: false`.
- The store's four operations exist, and the inputs and outputs match (how failure is returned and how asynchrony is wrapped are decided by the language's mapping table).
- The caller can distinguish the five error categories by type or by value.

The checking tests also demonstrate by tests that they can report it when the shape is deliberately shifted (removing an element, renaming it, changing a type, removing a category, and so on).

<a id="各言語の照合の方式"></a>
## How each language performs the check

| Language | How the public API is read | Deviations confirmed by negative tests | PR |
|:--|:--|:--|:--|
| go | `go/types` (an importer that reads the source) | Missing elements, renamed elements, changed types, missing required arguments of the construction function, return values of operations, missing error categories, constraints on type arguments, gaps in the mapping table | [go #438](https://github.com/j5ik2o/event-store-adapter-go/pull/438) |
| java | Reflection (builders are actually called to confirm the required elements) | Missing elements, renamed elements, changed types, omitted required elements, argument types of builders, return values of operations, constraints on type arguments, gaps in the correspondence between synchronous and asynchronous stores | [java #740](https://github.com/j5ik2o/event-store-adapter-java/pull/740) |
| js | TypeScript compiler API (creates a trial file that applies the types) | Missing elements, renamed elements, changed types, mistakes in optional elements, return values of operations, missing error categories, constraints on type arguments, a type no longer being exported | [js #1058](https://github.com/j5ik2o/event-store-adapter-js/pull/1058) |
| rs | rustdoc JSON of a date-pinned nightly (`rustdoc-types`) | Missing elements, renamed elements, changed types, missing required arguments of the construction function, return values of operations (down to inside the `async_trait` rewrite, including that `Future` is `Send`), missing error categories, constraints on type arguments, gaps in the mapping table | [rs #298](https://github.com/j5ik2o/event-store-adapter-rs/pull/298) |
| kotlin | `kotlin-reflect` | Missing operations and return values, asynchronous operations that are not `suspend`, return values that cannot express none, constraints on type arguments, gaps in the correspondence of synchronous and `suspend` stores and of the exception base class | [kotlin #857](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/857) |
| scala | Java reflection (including generic type information) | Return values of operations (how `Try`, `Future`, and `Option` wrap them), missing elements of `SnapshotReadResult`, constraints on type arguments, gaps in the correspondence of store, element, and exception classes | [scala #879](https://github.com/j5ik2o/event-store-adapter-scala/pull/879) |

kotlin and scala use java's envelopes and exceptions as they are, so the shape of the envelope elements and exception categories is left to java's check, and only that the classes can be resolved is confirmed. kotlin checks its own store operations (`SnapshotReadResult` is also java's), and scala checks its own store and `SnapshotReadResult`. What cannot be confirmed in each language (such as scala's `implicit` marker and the `AnyRef` upper bound) is written in each language's `api-surface/README.md`.

<a id="版を上げるときの手順"></a>
## Procedure when raising the version

`surface.json` is changed when the core contract's version changes and the shape of the public API changes (adding or removing elements, whether something is required, the inputs and outputs of operations, the error categories), or when `surface.json` did not copy the contract correctly. Fixing only the wording of the description also changes the SHA-256, so unless it is urgent, bundle it with the next time the shape changes.

Each language's CI checks its own repository's copy against its own repository's pinned value. Changing the hub's `surface.json` does not make any language's CI fail. Instead, each language keeps checking with the old version until it is redistributed, so the coordinator redistributes to the 6 languages (the same as the conformance test data).

1. Change `surface.json` in the hub and raise `version`. If the contract's version changes, update `contract` as well. If `status` is still `experimental`, make it `stable`. Compute the SHA-256 and add a row to the table "Versions and SHA-256" below. If the method of checking changes for any language, also fix the table "How each language performs the check" above.
2. In each language, align the following in one PR.
   - Replace `api-surface/surface.json` with the same content as the hub's.
   - Replace the pinned SHA-256 value in `.github/workflows/ci.yml`. For java, rs, kotlin, and scala, also replace the version in the step name (`Verify API surface 0.1.0`).
   - Replace the version and SHA-256 written in each language's `api-surface/README.md` (all 6 languages write the version; java, kotlin, and scala write the whole SHA-256, and rs also writes an abbreviated form). Find anything left unreplaced by running `git grep -n -e '<前の版>' -e '<前の SHA-256 の先頭の 8 文字>' -- api-surface .github` (the previous version, and the first 8 characters of the previous SHA-256) in each language's repository.
   - Set `surface_version` in the mapping table `api-surface/<言語>.json` to the new version (go's mapping table does not have this element). For java, scala, and rs, the checking test confirms that it matches the version of the copy.
   - Add the elements that were added or changed to the mapping table and the checking tests. Also add, to the negative tests, the case in which those elements are shifted.
   - If the shape changes, include the change to the library's public API in the same PR. The check is included in `CI Success`, so replacing only the copy makes CI fail.
3. kotlin and scala use java's envelopes and exceptions as they are, and leave the check of that shape to java ("How each language performs the check" above). Merge java's change first, and for kotlin and scala, raise the dependency to that java before replacing the copy.

<a id="版と-sha-256"></a>
## Versions and SHA-256

| Version | SHA-256 of `surface.json` |
|:--|:--|
| 0.1.0 | `37c91f8f94e10c73513a9c1deef990ea4deea96d5001ae700d6bf799658d0e32` |
