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
        schemas, documents, counts, covered, excluded = validate.validate(self.root, validate.DEFAULT_SPEC_ROOT)
        self.assertEqual(schemas, 6)
        self.assertGreater(documents, 0)
        self.assertGreater(counts["scenarios"], 0)
        self.assertGreater(covered, 0)
        self.assertEqual(excluded, 2)

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
        self.mutate("coverage.json", lambda doc: doc["required_rules"].append("T-6"))
        with self.rejected("未網羅"):
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


if __name__ == "__main__":
    unittest.main()
