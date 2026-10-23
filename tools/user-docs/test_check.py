"""利用者向けの文書の照合の道具（check.py）を、小さな文書の木で確かめる。"""

import json
from pathlib import Path
import posixpath
import subprocess
import sys
import tempfile
import unittest

import check

TOOLS = Path(__file__).resolve().parent
HUB = TOOLS.parents[1]
TEMPLATE = HUB / "user-docs" / "template.json"

PACKAGE = "sample-package"
ALL_STORAGES = ("memory", "dynamodb", "sqlite", "spanner", "bigtable")
JAPANESE_FIRST_LINE = "> この文書は [{english}]({english}) の日本語版です。英語版が正本で、食い違うときは英語版に従います。"
CONFIG = "user-docs/repo.json"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def japanese_path(english: str) -> str:
    return english[: -len(".md")] + ".ja.md"


def first_line(english: str) -> str:
    return JAPANESE_FIRST_LINE.replace("{english}", posixpath.basename(english))


def headings_body(h1: str, h2_entries: list, lang: str, storage_names=None, storages_h2=None) -> str:
    lines = [f"# {h1}", ""]
    for entry in h2_entries:
        name = entry[lang]
        lines += [f"## {name}", "", "Text.", ""]
        if storage_names is not None and entry["en"] == storages_h2:
            for storage in storage_names:
                lines += [f"### {storage}", "", "Text.", ""]
        else:
            lines += ["### Detail", "", "Text.", ""]
    return "\n".join(lines)


def build_tree(root: Path, *, docs_root=".", storages=ALL_STORAGES, extra=(), moved=None) -> None:
    """型どおりの正しい文書の木を root の下に作る。"""
    moved = dict(moved or {})
    template_text = TEMPLATE.read_text(encoding="utf-8")
    template = json.loads(template_text)
    write(root / "user-docs" / "template.json", template_text)
    repo = {
        "package": PACKAGE,
        "docs_root": docs_root,
        "storages": list(storages),
        "extra_documents": list(extra),
        "moved": moved,
    }
    write(root / CONFIG, json.dumps(repo, ensure_ascii=False, indent=2) + "\n")
    base = root / docs_root
    base.mkdir(parents=True, exist_ok=True)

    selected = [s for s in template["storages"] if s["id"] in storages]
    documents = template["documents"]

    def put_pair(english: str, en_text: str, ja_text: str) -> None:
        write(base / english, en_text)
        write(base / japanese_path(english), first_line(english) + "\n\n" + ja_text)

    readme = documents["readme"]
    put_pair(
        readme["path"],
        headings_body(PACKAGE, readme["h2"], "en", [s["en"] for s in selected], readme["storages_h2"]),
        headings_body(PACKAGE, readme["h2"], "ja", [s["ja"] for s in selected], readme["storages_h2"]),
    )
    schema = documents["schema"]
    for storage in selected:
        if storage["schema_prefix"] is None:
            continue
        h1 = {
            lang: schema["h1"][lang].replace("{en}", storage["en"]).replace("{ja}", storage["ja"])
            for lang in ("en", "ja")
        }
        put_pair(
            schema["path"].replace("{prefix}", storage["schema_prefix"]),
            headings_body(h1["en"], schema["h2"], "en"),
            headings_body(h1["ja"], schema["h2"], "ja"),
        )
    guide = documents["migration_guide"]
    put_pair(
        guide["path"],
        headings_body(guide["h1"]["en"], guide["h2"], "en"),
        headings_body(guide["h1"]["ja"], guide["h2"], "ja"),
    )
    for english in extra:
        put_pair(english, "# Extra\n\n### Free form\n", "# 追加\n\n## 自由な見出し\n")
    for old, new in moved.items():
        directory = posixpath.dirname(old) or "."
        link_en = posixpath.relpath(new, directory)
        link_ja = posixpath.relpath(japanese_path(new), directory)
        write(base / old, template["moved"]["en"].replace("{link}", link_en))
        write(
            base / japanese_path(old),
            template["moved"]["ja"].replace("{first_line}", first_line(old)).replace("{link}", link_ja),
        )


class UserDocsCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="user-docs-test-")
        self.base = Path(self.temporary.name)
        self.counter = 0

    def tearDown(self):
        self.temporary.cleanup()

    def tree(self, **options) -> Path:
        self.counter += 1
        root = self.base / f"tree{self.counter}"
        root.mkdir()
        build_tree(root, **options)
        return root

    def problems(self, root: Path) -> list:
        return check.check(root)[0]

    def edit(self, root: Path, relative: str, old: str, new: str) -> None:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, f"試験の前提: {relative} に {old!r} がある")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def edit_repo(self, root: Path, change) -> None:
        path = root / CONFIG
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def line_of(self, root: Path, relative: str, text: str) -> int:
        lines = (root / relative).read_text(encoding="utf-8").split("\n")
        return lines.index(text) + 1

    def insert_after(self, root: Path, relative: str, anchor: str, text: str) -> None:
        path = root / relative
        lines = path.read_text(encoding="utf-8").split("\n")
        position = lines.index(anchor) + 1
        lines[position:position] = text.split("\n")
        path.write_text("\n".join(lines), encoding="utf-8")

    def run_cli(self, *arguments, cwd=None):
        command = [sys.executable, "-S", str(TOOLS / "check.py"), *arguments]
        return subprocess.run(command, capture_output=True, text=True, cwd=cwd)

    def assertSingleProblem(self, problems: list, path: str, line=None) -> None:
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertEqual(problems[0].path, path)
        if line is not None:
            self.assertEqual(problems[0].line, line)

    # --- C1, C2, C3: 型の正本 ---

    def test_template_content(self):
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(template["version"], "1.0.0")
        self.assertEqual(template["japanese_first_line"], JAPANESE_FIRST_LINE)
        self.assertEqual(
            template["storages"],
            [
                {"id": "memory", "en": "Memory", "ja": "メモリ", "schema_prefix": None},
                {"id": "dynamodb", "en": "DynamoDB", "ja": "DynamoDB", "schema_prefix": "DYNAMODB"},
                {"id": "sqlite", "en": "SQLite", "ja": "SQLite", "schema_prefix": "SQLITE"},
                {"id": "spanner", "en": "Spanner", "ja": "Spanner", "schema_prefix": "SPANNER"},
                {"id": "bigtable", "en": "Bigtable", "ja": "Bigtable", "schema_prefix": "BIGTABLE"},
            ],
        )
        readme = template["documents"]["readme"]
        self.assertEqual(readme["path"], "README.md")
        self.assertEqual(readme["h1"], "package")
        self.assertEqual(readme["storages_h2"], "Storages")
        self.assertEqual(
            [(h["en"], h["ja"]) for h in readme["h2"]],
            [
                ("Overview", "概要"),
                ("Installation", "インストール"),
                ("Quick start", "はじめに"),
                ("Storages", "保存先"),
                ("Serialization", "直列化"),
                ("Retention", "保持"),
                ("Errors", "エラー"),
                ("Migration", "移行"),
                ("Conformance", "適合"),
                ("License", "ライセンス"),
            ],
        )
        schema = template["documents"]["schema"]
        self.assertEqual(schema["path"], "docs/{prefix}_DATABASE_SCHEMA.md")
        self.assertEqual(schema["h1"], {"en": "{en} storage schema", "ja": "{ja} の保存先のスキーマ"})
        self.assertEqual(
            [(h["en"], h["ja"]) for h in schema["h2"]],
            [
                ("Layout", "配置"),
                ("Configuration", "設定"),
                ("Initialization", "初期化"),
                ("Records", "記録"),
                ("Writes and reads", "書き込みと読み取り"),
                ("Retention", "保持"),
                ("Operations", "運用"),
            ],
        )
        guide = template["documents"]["migration_guide"]
        self.assertEqual(guide["path"], "docs/MIGRATION_GUIDE.md")
        self.assertEqual(guide["h1"], {"en": "Migration guide", "ja": "移行ガイド"})
        self.assertEqual(
            [(h["en"], h["ja"]) for h in guide["h2"]],
            [
                ("Overview", "概要"),
                ("Code changes", "コードの変更"),
                ("Data migration", "データの移行"),
                ("Verification and cutover", "確認と切り替え"),
            ],
        )

    def test_moved_files_template_shape(self):
        moved = json.loads(TEMPLATE.read_text(encoding="utf-8"))["moved"]
        english = moved["en"].split("\n")
        self.assertTrue(english[0].startswith("# "), "英語は H1 で始まる")
        self.assertEqual(moved["en"].count("]({link})"), 1)
        japanese = moved["ja"].split("\n")
        self.assertEqual(japanese[0], "{first_line}", "日本語は先頭の一行で始まる")
        self.assertEqual(len([line for line in japanese if line.startswith("# ")]), 1)
        self.assertEqual(moved["ja"].count("]({link})"), 1)

    # --- C15: 正しい木 ---

    def test_valid_trees(self):
        cases = {
            "root": ({}, 12),
            "packages/library": ({"docs_root": "packages/library"}, 12),
            "memory only": ({"storages": ("memory",)}, 4),
            "all five": ({"storages": ALL_STORAGES}, 12),
        }
        for name, (options, documents) in cases.items():
            with self.subTest(name):
                root = self.tree(**options)
                problems, count = check.check(root)
                self.assertEqual([p.render() for p in problems], [])
                self.assertEqual(count, documents)

    # --- C4, C5, C14: コマンドライン ---

    def test_cli_standard_library_only(self):
        root = self.tree()
        ok = self.run_cli("--root", str(root))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("OK (12 documents", ok.stdout)
        (root / "docs" / "SQLITE_DATABASE_SCHEMA.ja.md").unlink()
        failed = self.run_cli("--root", str(root))
        self.assertEqual(failed.returncode, 1)
        self.assertIn("docs/SQLITE_DATABASE_SCHEMA.ja.md", failed.stderr)

    def test_cli_reads_given_root(self):
        root = self.tree()
        other = self.base / "elsewhere"
        other.mkdir()
        result = self.run_cli("--root", str(root), cwd=other)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_reads_current_directory_by_default(self):
        root = self.tree()
        result = self.run_cli(cwd=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK (12 documents", result.stdout)
        (root / "docs" / "STRAY.md").write_text("# stray\n", encoding="utf-8")
        failed = self.run_cli(cwd=root)
        self.assertEqual(failed.returncode, 1)

    def test_reports_all_errors(self):
        root = self.tree()
        (root / "docs" / "SQLITE_DATABASE_SCHEMA.ja.md").unlink()
        (root / "docs" / "STRAY.md").write_text("# stray\n", encoding="utf-8")
        problems = self.problems(root)
        self.assertEqual(sorted(p.path for p in problems), ["docs/SQLITE_DATABASE_SCHEMA.ja.md", "docs/STRAY.md"])
        result = self.run_cli("--root", str(root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/SQLITE_DATABASE_SCHEMA.ja.md", result.stderr)
        self.assertIn("docs/STRAY.md", result.stderr)

    # --- C6: 設定の誤り ---

    def test_config_errors(self):
        def unknown_id(value):
            value["storages"].append("oracle")

        def missing_key(value):
            del value["package"]

        def absolute_extra(value):
            value["extra_documents"] = ["/etc/NOTES.md"]

        def missing_docs_root(value):
            value["docs_root"] = "no-such-directory"

        cases = {
            "unknown storage id": unknown_id,
            "missing required key": missing_key,
            "absolute path": absolute_extra,
            "docs_root without directory": missing_docs_root,
        }
        for name, change in cases.items():
            with self.subTest(name):
                root = self.tree(storages=("memory", "dynamodb"))
                self.edit_repo(root, change)
                problems = self.problems(root)
                self.assertIn(CONFIG, [p.path for p in problems], [p.render() for p in problems])

    def test_config_error_unknown_storage_id_is_the_only_problem(self):
        root = self.tree(storages=("memory", "dynamodb"))
        self.edit_repo(root, lambda value: value["storages"].append("oracle"))
        self.assertSingleProblem(self.problems(root), CONFIG)

    def test_config_error_missing_repo_json(self):
        root = self.tree()
        (root / CONFIG).unlink()
        problems = self.problems(root)
        self.assertIn(CONFIG, [p.path for p in problems])
        self.assertEqual(self.run_cli("--root", str(root)).returncode, 1)

    # --- C7: 照合 1（文書がある） ---

    def test_missing_document(self):
        cases = ["docs/SQLITE_DATABASE_SCHEMA.md", "docs/MIGRATION_GUIDE.ja.md", "README.ja.md"]
        for relative in cases:
            with self.subTest(relative):
                root = self.tree()
                (root / relative).unlink()
                problems = self.problems(root)
                self.assertIn(relative, [p.path for p in problems])
                self.assertEqual(
                    [p.path for p in problems if p.path != relative],
                    [japanese_path(relative)] if not relative.endswith(".ja.md") else [],
                    "英語の文書がなければ、日本語版の先頭の一行のリンクも切れる",
                )

    def test_missing_document_under_nested_docs_root(self):
        root = self.tree(docs_root="packages/library")
        (root / "packages/library/docs/MIGRATION_GUIDE.ja.md").unlink()
        self.assertSingleProblem(self.problems(root), "packages/library/docs/MIGRATION_GUIDE.ja.md")

    def test_memory_only_tree_does_not_require_schema_documents(self):
        root = self.tree(storages=("memory",))
        self.assertFalse((root / "docs" / "DYNAMODB_DATABASE_SCHEMA.md").exists())
        self.assertEqual(self.problems(root), [])

    # --- C8: 照合 2（見出し） ---

    def test_headings_code_blocks_are_not_counted(self):
        root = self.tree()
        fragment = "\n".join(
            [
                "",
                "```",
                "# install",
                "```",
                "",
                "~~~",
                "## not heading",
                "~~~",
                "",
                "````",
                "```",
                "# x",
                "````",
                "",
            ]
        )
        self.insert_after(root, "README.md", "## Installation", fragment)
        self.assertEqual([p.render() for p in self.problems(root)], [])

    def test_headings_unclosed_code_block_hides_following_headings(self):
        root = self.tree()
        self.insert_after(root, "README.md", "## Installation", "\n```")
        problems = self.problems(root)
        self.assertTrue(problems)
        self.assertEqual({p.path for p in problems}, {"README.md"})

    def test_headings_indented_or_spaceless_marker_is_not_a_heading(self):
        for replacement in ("    ## Retention", "#Retention"):
            with self.subTest(replacement):
                root = self.tree()
                self.edit(root, "README.md", "## Retention\n", replacement + "\n")
                problems = self.problems(root)
                self.assertTrue(problems)
                self.assertEqual({p.path for p in problems}, {"README.md"})

    def test_headings_h1_must_match_in_both_languages(self):
        root = self.tree()
        self.edit(root, "README.md", f"# {PACKAGE}\n", "# other-package\n")
        self.assertSingleProblem(self.problems(root), "README.md", self.line_of(root, "README.md", "# other-package"))
        root = self.tree()
        self.edit(root, "README.ja.md", f"# {PACKAGE}\n", "# other-package\n")
        self.assertSingleProblem(
            self.problems(root), "README.ja.md", self.line_of(root, "README.ja.md", "# other-package")
        )

    def test_headings_h2_order_must_match(self):
        root = self.tree()
        self.edit(root, "README.md", "## Errors\n", "## TEMP\n")
        self.edit(root, "README.md", "## Migration\n", "## Errors\n")
        self.edit(root, "README.md", "## TEMP\n", "## Migration\n")
        first_swapped = self.line_of(root, "README.md", "## Migration")
        self.assertSingleProblem(self.problems(root), "README.md", first_swapped)

    def test_headings_h2_missing(self):
        root = self.tree()
        self.edit(root, "README.md", "## Conformance\n", "")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertEqual(problems[0].path, "README.md")
        self.assertIsNotNone(problems[0].line)

    def test_headings_h2_extra(self):
        root = self.tree()
        path = root / "docs" / "MIGRATION_GUIDE.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n## Appendix\n", encoding="utf-8")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertEqual(problems[0].path, "docs/MIGRATION_GUIDE.md")
        self.assertIsNotNone(problems[0].line)

    def test_headings_japanese_h2_must_match(self):
        root = self.tree()
        self.edit(root, "README.ja.md", "## 概要\n", "## 概況\n")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertEqual(problems[0].path, "README.ja.md")

    def test_headings_storages_h3_must_match_provided_storages(self):
        root = self.tree()
        self.edit(root, "README.md", "### SQLite\n", "### Sqlite\n")
        self.assertSingleProblem(self.problems(root), "README.md", self.line_of(root, "README.md", "### Sqlite"))
        root = self.tree(storages=("memory",))
        self.insert_after(root, "README.md", "### Memory", "\nText.\n\n### DynamoDB")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertEqual(problems[0].path, "README.md")

    def test_headings_japanese_storages_h3_must_match(self):
        root = self.tree()
        self.edit(root, "README.ja.md", "### メモリ\n", "### メモリー\n")
        self.assertSingleProblem(
            self.problems(root), "README.ja.md", self.line_of(root, "README.ja.md", "### メモリー")
        )

    def test_headings_h3_count_must_be_equal_between_languages(self):
        root = self.tree()
        self.insert_after(root, "README.md", "## Overview", "\n### Additional")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertIn(problems[0].path, {"README.md", "README.ja.md"})

    def test_headings_schema_and_guide_h1_follow_the_template(self):
        root = self.tree()
        self.edit(root, "docs/SQLITE_DATABASE_SCHEMA.md", "# SQLite storage schema\n", "# SQLite schema\n")
        self.assertSingleProblem(self.problems(root), "docs/SQLITE_DATABASE_SCHEMA.md", 1)
        root = self.tree()
        self.edit(root, "docs/DYNAMODB_DATABASE_SCHEMA.ja.md", "# DynamoDB の保存先のスキーマ\n", "# DynamoDB\n")
        self.assertSingleProblem(
            self.problems(root),
            "docs/DYNAMODB_DATABASE_SCHEMA.ja.md",
            self.line_of(root, "docs/DYNAMODB_DATABASE_SCHEMA.ja.md", "# DynamoDB"),
        )
        root = self.tree()
        self.edit(root, "docs/MIGRATION_GUIDE.md", "# Migration guide\n", "# Guide\n")
        self.assertSingleProblem(self.problems(root), "docs/MIGRATION_GUIDE.md", 1)

    # --- C9: 照合 3（日本語の先頭の一行） ---

    def test_japanese_first_line(self):
        cases = {
            "required document": ("README.ja.md", {}),
            "extra document": ("docs/MIGRATION_GUIDE_v3.ja.md", {"extra": ["docs/MIGRATION_GUIDE_v3.md"]}),
            "moved file": (
                "docs/OLD_NAME.ja.md",
                {"moved": {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}},
            ),
        }
        for name, (relative, options) in cases.items():
            with self.subTest(name):
                root = self.tree(**options)
                path = root / relative
                lines = path.read_text(encoding="utf-8").split("\n")
                lines[0] = "> これは日本語版です。"
                path.write_text("\n".join(lines), encoding="utf-8")
                problems = self.problems(root)
                self.assertIn((relative, 1), [(p.path, p.line) for p in problems], [p.render() for p in problems])
        with self.subTest("required document is the only problem"):
            root = self.tree()
            self.edit(root, "README.ja.md", first_line("README.md") + "\n", "> これは日本語版です。\n")
            self.assertSingleProblem(self.problems(root), "README.ja.md", 1)

    # --- C10: 照合 4（相対リンク） ---

    def test_links_exempt_and_anchored_links_pass(self):
        root = self.tree()
        links = "\n[a](docs/MIGRATION_GUIDE.md#overview)\n[b](https://x)\n[c](mailto:a@b)\n[d](#top)\n"
        self.insert_after(root, "README.md", "## Installation", links)
        self.assertEqual([p.render() for p in self.problems(root)], [])

    def test_links_missing_target_is_reported_with_line(self):
        root = self.tree()
        self.insert_after(root, "README.md", "## Installation", "\n[e](docs/NOPE.md)\n")
        line = self.line_of(root, "README.md", "[e](docs/NOPE.md)")
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertTrue(problems[0].render().startswith(f"README.md:{line}:"), problems[0].render())

    def test_links_inside_code_are_not_checked(self):
        root = self.tree()
        text = "\n```\n[e](docs/NOPE.md)\n```\n\n`[e](docs/NOPE.md)`\n"
        self.insert_after(root, "README.md", "## Installation", text)
        self.assertEqual([p.render() for p in self.problems(root)], [])

    def test_nested_code_blocks_are_code(self):
        bodies = {
            "quote": "\n> ```sh\n> # comment\n> [e](docs/NOPE.md)\n> ```\n",
            "list indent": "\n1. Run:\n\n   ```sh\n   # comment\n   [e](docs/NOPE.md)\n   ```\n\n2. Done\n",
            "nested bullet": "\n- a\n  - b\n\n      ~~~sh\n      # comment\n      [e](docs/NOPE.md)\n      ~~~\n",
        }
        for name, text in bodies.items():
            with self.subTest(name):
                root = self.tree()
                self.insert_after(root, "README.md", "## Installation", text)
                self.assertEqual([p.render() for p in self.problems(root)], [])

    def test_nested_code_block_does_not_leak_after_close(self):
        root = self.tree()
        text = "\n> ```sh\n> # comment\n> ```\n\n[e](docs/NOPE.md)\n"
        self.insert_after(root, "README.md", "## Installation", text)
        problems = self.problems(root)
        self.assertEqual(len(problems), 1, [p.render() for p in problems])
        self.assertIn("NOPE", problems[0].message)

    def test_unreadable_documents_are_reported_and_others_continue(self):
        root = self.tree()
        (root / "README.md").write_bytes(b"\xff\xfe\x00bad")
        self.edit(root, "docs/MIGRATION_GUIDE.md", "# ", "# X")
        problems = self.problems(root)
        paths = [p.path for p in problems]
        self.assertIn("README.md", paths)
        self.assertIn("docs/MIGRATION_GUIDE.md", paths)
        self.assertTrue(any("UTF-8" in p.message for p in problems if p.path == "README.md"))

    # --- C11: 照合 5（型の外の文書） ---

    def test_extra_documents_need_both_languages_and_free_headings(self):
        extra = ["docs/MIGRATION_GUIDE_v3.md"]
        root = self.tree(extra=extra)
        self.assertEqual([p.render() for p in self.problems(root)], [])
        root = self.tree(extra=extra)
        (root / "docs" / "MIGRATION_GUIDE_v3.ja.md").unlink()
        self.assertSingleProblem(self.problems(root), "docs/MIGRATION_GUIDE_v3.ja.md")
        root = self.tree(extra=extra)
        (root / "docs" / "MIGRATION_GUIDE_v3.md").unlink()
        problems = self.problems(root)
        self.assertIn("docs/MIGRATION_GUIDE_v3.md", [p.path for p in problems])
        self.assertEqual({p.path for p in problems}, {"docs/MIGRATION_GUIDE_v3.md", "docs/MIGRATION_GUIDE_v3.ja.md"})

    def test_config_paths_are_normalized(self):
        extra = ["./docs/MIGRATION_GUIDE_v3.md"]
        moved = {"./docs/OLD_NAME.md": "./docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(extra=["docs/MIGRATION_GUIDE_v3.md"], moved={"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"})
        self.edit_repo(root, lambda v: v.update(extra_documents=extra, moved=moved))
        self.assertEqual([p.render() for p in self.problems(root)], [])

    def test_config_paths_outside_root_stay_errors(self):
        for name, change in {
            "parent": lambda v: v.update(extra_documents=["./../OUT.md"]),
            "inner parent": lambda v: v.update(extra_documents=["docs/../OUT.md"]),
            "absolute": lambda v: v.update(extra_documents=["/docs/OUT.md"]),
            "moved parent": lambda v: v.update(moved={"../OLD.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}),
        }.items():
            with self.subTest(name):
                root = self.tree()
                self.edit_repo(root, change)
                self.assertTrue(any(p.path == CONFIG for p in self.problems(root)))

    # --- C3, C12: 照合 6（移ったことを示すファイル） ---

    def test_moved_files_valid(self):
        moved = {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(moved=moved)
        problems, count = check.check(root)
        self.assertEqual([p.render() for p in problems], [])
        self.assertEqual(count, 14)

    def test_moved_files_rejects_changed_shape(self):
        moved = {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(moved=moved)
        write(root / "docs" / "OLD_NAME.md", "# Moved\n\nSee elsewhere.\n")
        self.assertIn("docs/OLD_NAME.md", [p.path for p in self.problems(root)])

    def test_moved_files_rejects_wrong_english_target(self):
        moved = {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(moved=moved)
        path = root / "docs" / "OLD_NAME.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("DYNAMODB_DATABASE_SCHEMA.md", "SQLITE_DATABASE_SCHEMA.md"),
            encoding="utf-8",
        )
        self.assertSingleProblem(self.problems(root), "docs/OLD_NAME.md")

    def test_moved_files_rejects_japanese_pointing_at_english_document(self):
        moved = {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(moved=moved)
        path = root / "docs" / "OLD_NAME.ja.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("DYNAMODB_DATABASE_SCHEMA.ja.md", "DYNAMODB_DATABASE_SCHEMA.md"),
            encoding="utf-8",
        )
        self.assertSingleProblem(self.problems(root), "docs/OLD_NAME.ja.md")

    def test_moved_files_rejects_missing_new_document(self):
        moved = {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
        root = self.tree(moved=moved)
        (root / "docs" / "DYNAMODB_DATABASE_SCHEMA.ja.md").unlink()
        self.assertIn("docs/OLD_NAME.ja.md", [p.path for p in self.problems(root)])

    # --- C13: 照合 7（docs/ の直下） ---

    def test_docs_directory_rejects_unlisted_markdown(self):
        root = self.tree()
        (root / "docs" / "STRAY.md").write_text("# stray\n", encoding="utf-8")
        self.assertSingleProblem(self.problems(root), "docs/STRAY.md")

    def test_docs_directory_ignores_subdirectories(self):
        root = self.tree()
        write(root / "docs" / "dev" / "NOTES.md", "# free\n\n[x](nope.md)\n")
        self.assertEqual([p.render() for p in self.problems(root)], [])

    # --- C17: 説明の文書 ---

    def test_hub_documents_exist_in_pairs(self):
        for directory in (HUB / "user-docs", HUB / "tools" / "user-docs"):
            for name in ("README.md", "README.ja.md"):
                self.assertTrue((directory / name).is_file(), f"{directory / name}")

    def test_hub_documents_first_line(self):
        problems = []
        template = check.load_template(TEMPLATE, HUB, problems)
        self.assertEqual(problems, [])
        for directory in (HUB / "user-docs", HUB / "tools" / "user-docs"):
            with self.subTest(str(directory.relative_to(HUB))):
                found = check.check_first_line(directory / "README.ja.md", "README.md", template, HUB)
                self.assertEqual([p.render() for p in found], [])


if __name__ == "__main__":
    unittest.main()
