"""配布時の改変と不正なケースを、検証ツールが拒否することを確認する。"""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import manifest
import validate

TOOLS = Path(__file__).resolve().parent


class ConformanceToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="conformance-test-", dir=TOOLS)
        self.root = Path(self.temporary.name) / "conformance"
        shutil.copytree(manifest.DEFAULT_ROOT, self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def mutate(self, relative, transformation):
        path = self.root / relative
        value = manifest.read_json(path)
        transformation(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def check(self):
        return validate.validate(self.root, validate.DEFAULT_SPEC_ROOT, check_manifest=False)

    def rejected(self, message):
        return self.assertRaisesRegex(ValueError, message)

    def test_distributed_data_is_valid(self):
        schemas, documents, counts, covered, excluded, checked, skipped = validate.validate(self.root, validate.DEFAULT_SPEC_ROOT)
        self.assertEqual(schemas, 6)
        self.assertGreater(documents, 0)
        self.assertGreater(counts["scenarios"], 0)
        self.assertGreater(covered, 0)
        self.assertEqual(excluded, 36)
        self.assertGreater(checked, 0)

    def test_manifest_cli_uses_only_standard_library_and_detects_change(self):
        command = [sys.executable, "-S", str(TOOLS / "manifest.py"), "verify", "--root", str(self.root)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        (self.root / "README.md").write_text("改変\n", encoding="utf-8")
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        rebuild = [sys.executable, "-S", str(TOOLS / "manifest.py"), "rebuild", "--root", str(self.root)]
        self.assertEqual(subprocess.run(rebuild, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_manifest_rejects_missing_or_extra_files(self):
        path = self.root / "README.md"
        original = path.read_bytes()
        path.unlink()
        with self.rejected("manifest"):
            manifest.verify(self.root)
        path.write_bytes(original)
        (self.root / "extra.txt").write_text("追加\n", encoding="utf-8")
        with self.rejected("manifest"):
            manifest.verify(self.root)

    def test_manifest_rejects_wrong_version_and_duplicate_entries(self):
        self.mutate("manifest.json", lambda doc: doc.update(version="2.0.0"))
        with self.rejected("manifest"):
            manifest.verify(self.root)
        value = manifest.inventory(self.root)
        value["files"].append(copy.deepcopy(value["files"][0]))
        (self.root / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
        with self.rejected("manifest"):
            manifest.verify(self.root)

    def test_manifest_rejects_symlinks(self):
        (self.root / "linked.md").symlink_to(self.root / "README.md")
        with self.rejected("シンボリックリンク"):
            manifest.verify(self.root)

    def test_schema_rejects_unknown_operation_and_extra_field(self):
        relative = "scenarios/core/write-read.json"
        original = manifest.read_json(self.root / relative)
        self.mutate(relative, lambda doc: doc["cases"][0]["steps"][0].update(op="unknownOperation"))
        with self.rejected("Schema 不一致"):
            self.check()
        (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
        self.mutate(relative, lambda doc: doc["cases"][0].update(unknown_field=True))
        with self.rejected("Schema 不一致"):
            self.check()
        result = subprocess.run([sys.executable, str(TOOLS / "validate.py"), "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validation: FAILED", result.stderr)

    def test_schema_rejects_unknown_error_category(self):
        self.mutate("scenarios/core/retention-errors.json", lambda doc:
                    doc["cases"][0]["initialization"]["expect"]["error"].update(category="other"))
        with self.rejected("Schema 不一致"):
            self.check()

    def test_schema_requires_draft_2020_12(self):
        self.mutate("schema/values.schema.json", lambda doc:
                    doc.update({"$schema": "http://json-schema.org/draft-07/schema#"}))
        with self.rejected("draft 2020-12"):
            self.check()

    def test_rule_must_be_active_definition(self):
        for rule in ["D-999", "W-5"]:
            with self.subTest(rule=rule):
                self.mutate("values/aid.json", lambda doc: doc["cases"][0].update(rules=[rule]))
                with self.rejected("規則が仕様に定義"):
                    self.check()

    def test_case_ids_are_globally_unique(self):
        identifier = manifest.read_json(self.root / "scenarios/core/write-read.json")["cases"][0]["id"]
        self.mutate("values/aid.json", lambda doc: doc["cases"][0].update(id=identifier))
        with self.rejected("ID 重複"):
            self.check()

    def test_references_must_exist(self):
        self.mutate("scenarios/core/write-read.json", lambda doc:
                    doc["cases"][0]["steps"][2]["arguments"].update(event="missing-event"))
        with self.rejected("未定義の event"):
            self.check()

    def test_fault_operation_and_phase_must_match(self):
        relative = "dynamodb/read.json"
        original = manifest.read_json(self.root / relative)
        self.mutate(relative, lambda doc: doc["cases"][1]["faults"][0].update(operation=999))
        with self.rejected("障害の操作番号"):
            self.check()
        (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
        self.mutate(relative, lambda doc: doc["cases"][1]["faults"][0].update(phase="commit"))
        with self.rejected("障害の段階"):
            self.check()

    def test_interleaved_operation_reference_must_exist(self):
        self.mutate("dynamodb/read.json", lambda doc:
                    doc["cases"][2]["faults"][0]["details"]["interleaved_operation"]["arguments"].update(event="missing-event"))
        with self.rejected("差し込みイベントが未定義"):
            self.check()

    def test_coverage_requires_each_requested_rule(self):
        self.mutate("coverage.json", lambda doc: doc["required_rules"].append("D-8"))
        with self.rejected("未網羅"):
            self.check()

    def test_coverage_rejects_defined_rule_without_case_or_reason(self):
        # T-6 は仕様が定義する規則で、ケースがなく対象外の理由だけを持つ。理由を除くと未網羅になる。
        self.mutate("coverage.json", lambda doc: doc.update(
            exclusions=[x for x in doc["exclusions"] if x["rule"] != "T-6"]))
        with self.rejected("未網羅"):
            self.check()

    def test_every_defined_rule_has_case_or_reason(self):
        _, _, defined = validate.specification_rules(validate.DEFAULT_SPEC_ROOT)
        self.assertEqual(len(defined), 92)
        rows = {}
        for line in (manifest.DEFAULT_ROOT / "COVERAGE.md").read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.strip("|").split(" | ")]
            if len(cells) == 3 and cells[0] in defined:
                rows[cells[0]] = cells
        self.assertEqual(set(rows), defined)
        for rule, (_, cases, reason) in rows.items():
            with self.subTest(rule=rule):
                self.assertTrue(cases != "—" or reason != "—")

    def test_schema_rejects_unknown_request_scope_attribute(self):
        self.case_mutation("dynamodb/single-aggregate-requests.json", "dynamodb-single-aggregate-delete", lambda c:
                           c["steps"][0]["observe"]["request_scope"].update(unknown=True))
        with self.rejected("Schema 不一致"):
            self.check()

    def test_request_scope_requires_all_dy19_apis(self):
        def drop_query(case):
            scope = case["steps"][0]["observe"]["request_scope"]
            scope["apis"] = [api for api in scope["apis"] if api != "Query"]
        self.case_mutation("dynamodb/single-aggregate-requests.json", "dynamodb-single-aggregate-delete", drop_query)
        with self.rejected("DY-19"):
            self.check()

    def test_dy19_case_requires_request_scope_on_every_step(self):
        def drop_all_scopes(case):
            for step in case["steps"]:
                step["observe"].pop("request_scope")
        self.case_mutation("dynamodb/single-aggregate-requests.json", "dynamodb-single-aggregate-delete", drop_all_scopes)
        with self.rejected("request_scope が必要"):
            self.check()

    def test_unsupported_memory_setting_requires_configuration_error(self):
        self.case_mutation("memory/configuration.json", "memory-change-feed-unsupported", lambda c: c.pop("initialization"))
        with self.rejected("configuration エラーを期待する"):
            self.check()
        shutil.copyfile(manifest.DEFAULT_ROOT / "memory/configuration.json", self.root / "memory/configuration.json")
        self.case_mutation("memory/configuration.json", "memory-ttl-unsupported", lambda c:
                           c["initialization"]["expect"]["error"].update(category="storage"))
        with self.rejected("configuration エラーを期待する"):
            self.check()

    def test_sq_rule_without_case_or_reason_is_rejected(self):
        # SQ-14 は操作の場面で表せず、対象外の理由だけを持つ。理由を除くと未網羅になる。
        self.mutate("coverage.json", lambda doc: doc.update(
            exclusions=[x for x in doc["exclusions"] if x["rule"] != "SQ-14"]))
        with self.rejected("未網羅"):
            self.check()

    def test_sq_rules_are_collected_from_definition_lines_only(self):
        _, _, defined = validate.specification_rules(validate.DEFAULT_SPEC_ROOT)
        self.assertEqual({r for r in defined if r.startswith("SQ-")},
                         {f"SQ-{n}" for n in range(1, 21) if n != 13})
        self.assertNotIn("SQ-D1a", defined)
        coverage = (manifest.DEFAULT_ROOT / "COVERAGE.md").read_text(encoding="utf-8")
        self.assertIn("| SQ-12 |", coverage)
        self.assertNotIn("| SQ-13 |", coverage)
        self.assertNotIn("SQ-D1a", coverage)

    def test_write_lock_requires_sqlite_only_backends(self):
        relative, identifier = "sqlite/write-lock.json", "sqlite-write-lock-busy"
        self.check()
        original = manifest.read_json(self.root / relative)
        for backends in (["sqlite", "memory"], ["memory"], ["sqlite", "spanner", "bigtable"]):
            with self.subTest(backends=backends):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, identifier, lambda c: c.update(backends=backends))
                with self.assertRaises(ValueError):
                    self.check()

    def test_write_lock_release_without_hold_is_rejected(self):
        self.case_mutation("sqlite/write-lock.json", "sqlite-write-lock-busy", lambda c:
                           c.update(steps=[s for s in c["steps"] if s["op"] != "holdWriteLock"]))
        with self.rejected("持っていないロック"):
            self.check()

    def test_write_lock_cannot_be_held_twice(self):
        def hold_twice(case):
            index = next(i for i, s in enumerate(case["steps"]) if s["op"] == "holdWriteLock")
            case["steps"].insert(index + 1, copy.deepcopy(case["steps"][index]))
        self.case_mutation("sqlite/write-lock.json", "sqlite-write-lock-busy", hold_twice)
        with self.assertRaises(ValueError):
            self.check()

    def test_write_lock_requires_wait_time_and_sq7(self):
        relative, identifier = "sqlite/write-lock.json", "sqlite-write-lock-busy"
        original = manifest.read_json(self.root / relative)
        changes = {
            "no-wait-time": lambda c: c["store"].pop("lock_wait_milliseconds"),
            "no-sq7": lambda c: c.update(rules=[r for r in c["rules"] if r != "SQ-7"]),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, identifier, change)
                with self.assertRaises(ValueError):
                    self.check()

    def test_new_store_is_rejected_on_stage5_backends(self):
        relative, identifier = "scenarios/stores/shared.json", "store-shared-persistent"
        self.check()
        def use_new(case):
            step = next(s for s in case["steps"] if s["op"] == "createStore")
            step["arguments"]["storage"] = "new"
            step["arguments"].pop("shared_with", None)
        self.case_mutation(relative, identifier, use_new)
        with self.rejected("storage = new"):
            self.check()

    def test_stage5_shared_store_rejects_reserved_name_and_provider_specific_rules(self):
        relative, identifier = "scenarios/stores/shared.json", "store-shared-persistent"
        original = manifest.read_json(self.root / relative)
        changes = {
            "reserved-name": lambda c: next(s for s in c["steps"] if s["op"] == "createStore")["arguments"].update(name="primary"),
            "memory-rule": lambda c: c["rules"].append("MEM-2"),
            "memory-backend": lambda c: c.update(backends=["memory", "sqlite"]),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, identifier, change)
                with self.assertRaises(ValueError):
                    self.check()

    def test_memory_store_case_still_requires_memory_backend_and_mem2(self):
        relative = "memory/stores.json"
        original = manifest.read_json(self.root / relative)
        changes = {
            "no-mem2": lambda c: c.update(rules=[r for r in c["rules"] if r != "MEM-2"]),
            "sqlite-backend": lambda c: c.update(backends=["sqlite"]),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, "memory-store-shared", change)
                with self.assertRaises(ValueError):
                    self.check()

    def test_new_store_remains_available_on_memory_backend(self):
        self.case_mutation("memory/stores.json", "memory-store-new-independent", lambda c:
                           self.assertTrue(any(s["op"] == "createStore" and s["arguments"]["storage"] == "new"
                                               for s in c["steps"])))
        self.check()

    def test_sqlite_unsupported_setting_requires_configuration_error(self):
        relative = "sqlite/configuration.json"
        original = manifest.read_json(self.root / relative)
        unsupported = [c["id"] for c in original["cases"]
                       if "seed" not in c and "error" in c["initialization"]["expect"]]
        self.assertEqual(len(unsupported), 2)
        for identifier in unsupported:
            with self.subTest(case=identifier):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, identifier, lambda c:
                                   c["initialization"]["expect"]["error"].update(category="storage"))
                with self.rejected("configuration エラーを期待する"):
                    self.check()

    def test_seeded_configuration_requires_initialization_and_known_keys(self):
        relative = "sqlite/configuration.json"
        original = manifest.read_json(self.root / relative)
        seeded = next(c["id"] for c in original["cases"] if "configuration" in c.get("seed", {}))
        changes = {
            "no-initialization": lambda c: c.pop("initialization"),
            "unknown-key": lambda c: c["seed"]["configuration"].update(table_name="x"),
            "raw-items-mixed": lambda c: c["seed"].update(items=[]),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, seeded, change)
                with self.assertRaises(ValueError):
                    self.check()

    def test_generated_coverage_must_match_case_data(self):
        self.mutate("values/aid.json", lambda doc: doc["cases"][0].update(id="renamed-aid-case"))
        with self.rejected("COVERAGE.md"):
            self.check()

    def test_value_table_detects_incorrect_epoch_and_byte_boundary(self):
        relative = "values/occurred-at.json"
        self.mutate(relative, lambda doc: doc["cases"][0]["input"].update(epoch_nanoseconds="0"))
        with self.rejected("エポックナノ秒が不一致"):
            self.check()
        shutil.copyfile(manifest.DEFAULT_ROOT / relative, self.root / relative)
        self.mutate("values/aid.json", lambda doc: doc["cases"][0]["expect"].update(value="wrong-aid"))
        with self.rejected("値の期待が入力と不一致"):
            self.check()

    def test_json_rejects_duplicate_keys_and_nonstandard_numbers(self):
        path = self.root / "values/aid.json"
        for contents in ['{"format":"values","format":"values"}', '{"number":NaN}', '{"number":Infinity}']:
            with self.subTest(contents=contents):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    manifest.read_json(path)


    def case_mutation(self, relative, identifier, change):
        self.mutate(relative, lambda doc: change(next(c for c in doc["cases"] if c["id"] == identifier)))

    def test_message_number_cannot_hide_in_aid_or_rule(self):
        relative = "scenarios/core/write-read.json"
        original = manifest.read_json(self.root / relative)
        for token in ["9", "8", ""]:
            with self.subTest(token=token):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, "core-gap-event", lambda c:
                                   c["steps"][1]["expect"]["error"]["message"]["must_contain"].append(token))
                with self.rejected("must_contain"):
                    self.check()

    def test_d7_cannot_be_required_error_rule(self):
        self.case_mutation("dynamodb/write-errors.json", "dynamodb-item-size-event", lambda c:
                           c["steps"][0]["expect"]["error"].update(rule="D-7"))
        with self.rejected("判断番号"):
            self.check()

    def test_cancellation_vector_requires_none_for_other_actions(self):
        self.case_mutation("dynamodb/write-errors.json", "dynamodb-condition-equal", lambda c:
                           c["faults"][0]["details"]["cancellation_reasons"].pop(0))
        with self.rejected("CancellationReasons"):
            self.check()

    def test_fault_fields_use_single_types_and_explicit_injection(self):
        relative = "dynamodb/read.json"
        original = manifest.read_json(self.root / relative)
        for update in [{"times": "until-operation-finishes"}, {"repeat": 1}, {"operation": "initialize"}]:
            with self.subTest(update=update):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, "dynamodb-latest-unprocessed", lambda c: c["faults"][0].update(update))
                with self.rejected("Schema 不一致"):
                    self.check()
        (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
        self.case_mutation(relative, "dynamodb-latest-unprocessed", lambda c: c["faults"][0].pop("injection"))
        with self.rejected("Schema 不一致"):
            self.check()

    def test_ambiguous_context_and_expression_strings_are_rejected(self):
        self.case_mutation("scenarios/core/write-read.json", "core-existing-create-event", lambda c:
                           c["steps"][2]["expect"]["error"]["message"].update(context_only={}))
        with self.rejected("Schema 不一致"):
            self.check()
        shutil.copyfile(manifest.DEFAULT_ROOT / "scenarios/core/write-read.json", self.root / "scenarios/core/write-read.json")
        self.case_mutation("dynamodb/retention.json", "dynamodb-retention-ttl-once", lambda c:
                           c["steps"][0]["observe"]["requests"][0]["constraints"].update(update_expression="SET #ttl = :expires"))
        with self.rejected("Schema 不一致"):
            self.check()

    def test_value_message_requires_related_sequence_number(self):
        def incorrect(doc):
            scenario = next(c for c in doc["cases"] if "error" in c["expect"])
            scenario["expect"]["error"]["message"]["must_contain"] = ["T-13", "42"]
        self.mutate("values/occurred-at.json", incorrect)
        with self.rejected("関係する番号のメッセージ期待"):
            self.check()

    def test_operation_may_target_a_created_store_by_name(self):
        self.case_mutation("memory/stores.json", "memory-store-shared", lambda c:
                           self.assertEqual(c["steps"][2]["store"], "second"))
        self.check()

    def test_store_name_must_be_unique_reserved_and_created_before_use(self):
        relative = "memory/stores.json"
        original = manifest.read_json(self.root / relative)
        changes = {
            "reserved-name": lambda c: c["steps"][1]["arguments"].update(name="primary"),
            "duplicate-name": lambda c: c["steps"].insert(2, copy.deepcopy(c["steps"][1])),
            "use-before-creation": lambda c: c["steps"][2].update(store="third"),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, "memory-store-shared", change)
                with self.assertRaises(ValueError):
                    self.check()

    def test_payload_mutation_with_a_different_value_is_accepted(self):
        self.case_mutation("memory/payload-isolation.json", "memory-payload-written-mutation", lambda c:
                           c["steps"][1]["arguments"].update(pointer="/items/0/qty", value=7))
        self.check()

    def test_payload_mutation_pointer_must_exist_in_written_payload(self):
        relative = "memory/payload-isolation.json"
        original = manifest.read_json(self.root / relative)
        for pointer in ["/items/0/missing", "/items/1/qty", "/items/-", "/items/01/qty", "/note/x"]:
            with self.subTest(pointer=pointer):
                (self.root / relative).write_text(json.dumps(original), encoding="utf-8")
                self.case_mutation(relative, "memory-payload-written-mutation", lambda c:
                                   c["steps"][1]["arguments"].update(pointer=pointer))
                with self.rejected("JSON Pointer"):
                    self.check()

    def test_payload_mutation_to_the_current_value_is_rejected_as_vacuous(self):
        self.case_mutation("memory/payload-isolation.json", "memory-payload-written-mutation", lambda c:
                           c["steps"][1]["arguments"].update(pointer="/note", value="original"))
        with self.assertRaises(ValueError):
            self.check()

    def test_independent_store_case_requires_write_before_reading_new_store(self):
        self.case_mutation("memory/stores.json", "memory-store-new-independent", lambda c: c["steps"].pop(0))
        with self.rejected("独立の場面は"):
            self.check()

    def test_hash_table_rejects_incorrect_output(self):
        self.mutate("values/hash.json", lambda doc: doc["cases"][0]["expect"].update(value="0x0000000000000000"))
        with self.rejected("値の期待が入力と不一致"):
            self.check()

    def test_validation_uses_reference_model_for_classification(self):
        def incorrect(case):
            e = case["steps"][1]["expect"]["error"]
            e["category"] = "optimistic-lock"
            e["message"]["must_contain"].append("Order-9")
        self.case_mutation("scenarios/core/write-read.json", "core-gap-event", incorrect)
        with self.rejected("参照モデルと期待が不一致"):
            self.check()

    def test_validation_uses_reference_model_for_ttl(self):
        self.case_mutation("dynamodb/retention.json", "dynamodb-retention-ttl-once", lambda c:
                           c["steps"][0]["observe"]["history"]["marked"][1].update(ttl=1))
        with self.rejected("参照モデルの履歴・TTL期限"):
            self.check()


if __name__ == "__main__":
    unittest.main()
