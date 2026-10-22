"""Checks on the repository itself rather than on a module's behavior:
every tracked file with a shebang is executable in git, so ruff's EXE001
(which only sees the exec bit on Linux, i.e. on CI) can't fail a push that
passed lint on Windows; and every test that docs/seeding-policy.md names as
pinning a rule exists, so the policy table can't silently point at a
renamed or deleted test.

Run with: python -m unittest discover -s tests
"""

import ast
import os
import re
import shutil
import subprocess
import unittest

import helpers


def setUpModule():
    helpers.isolate_module()


def shebang_files_not_executable(entries):
    """The paths in `entries` ((git mode, path, first two bytes) triples)
    that start with a shebang but aren't recorded as 100755."""
    return [path for mode, path, head in entries if head == b"#!" and mode != "100755"]


def tracked_files(git):
    """(git mode, path, first two bytes) for every file in the index."""
    listing = subprocess.run(
        [git, "ls-files", "-s", "-z"],
        cwd=helpers.REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout.decode()
    for record in filter(None, listing.split("\0")):
        meta, path = record.split("\t", 1)
        mode = meta.split()[0]
        full = os.path.join(helpers.REPO_ROOT, path)
        if mode == "120000" or not os.path.isfile(full):
            continue  # a symlink, or deleted in the working tree
        with open(full, "rb") as f:
            yield mode, path, f.read(2)


SEEDING_POLICY = os.path.join(helpers.REPO_ROOT, "docs", "seeding-policy.md")


def policy_test_references(text):
    """(test module, Class.test_name) for every test a policy table row
    names. A row's last cell lists them as `test_module`: `Class.test_x`,
    with several modules separated by `;`."""
    references = []
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        pinned_by = line.rstrip(" |").rsplit(" | ", 1)[-1]
        for group in pinned_by.split(";"):
            module = re.match(r"\s*`(test_\w+)`:", group)
            if module:
                for name in re.findall(r"`(\w+\.test_\w+)`", group):
                    references.append((module.group(1), name))
    return references


def defined_tests(source):
    """Every Class.test_name defined in a test module's source."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    names.add(f"{node.name}.{item.name}")
    return names


class ShebangFilesNotExecutableTests(unittest.TestCase):
    def test_flags_a_shebang_file_without_the_exec_bit(self):
        self.assertEqual(
            shebang_files_not_executable([("100644", "a.py", b"#!")]),
            ["a.py"],
        )

    def test_passes_an_executable_shebang_file(self):
        self.assertEqual(shebang_files_not_executable([("100755", "a.py", b"#!")]), [])

    def test_ignores_files_without_a_shebang(self):
        self.assertEqual(shebang_files_not_executable([("100644", "a.py", b'""')]), [])


class RepositoryTests(unittest.TestCase):
    def test_every_tracked_shebang_file_is_executable_in_git(self):
        git = shutil.which("git")
        if git is None or not os.path.exists(os.path.join(helpers.REPO_ROOT, ".git")):
            self.skipTest("not a git checkout")

        self.assertEqual(
            shebang_files_not_executable(tracked_files(git)),
            [],
            "mark scripts executable with `git update-index --chmod=+x "
            "<file>` (chmod does nothing on Windows), or drop the shebang "
            "from a module that is only imported",
        )


class SeedingPolicyReferencesTests(unittest.TestCase):
    def test_reads_every_module_and_test_a_row_names(self):
        row = (
            "| A rule. | `test_a`: `A.test_one`, `A.test_two`; "
            "`test_b`: `B.test_three` |"
        )
        self.assertEqual(
            policy_test_references(row),
            [
                ("test_a", "A.test_one"),
                ("test_a", "A.test_two"),
                ("test_b", "B.test_three"),
            ],
        )

    def test_ignores_the_header_separator_and_prose(self):
        text = "| Rule | Pinned by |\n| --- | --- |\nSee `test_a`: `A.test_one`."
        self.assertEqual(policy_test_references(text), [])

    def test_finds_methods_only_on_their_own_class(self):
        source = "class A:\n    def test_x(self): pass\n    def helper(self): pass\n"
        self.assertEqual(defined_tests(source), {"A.test_x"})

    def test_every_test_the_seeding_policy_names_exists(self):
        # The image's test stage copies tests/ but not docs/ or .git; in a
        # checkout the doc must exist, so a deleted one fails here.
        if not os.path.exists(os.path.join(helpers.REPO_ROOT, ".git")):
            self.skipTest("not a git checkout")
        with open(SEEDING_POLICY, encoding="utf-8") as f:
            references = policy_test_references(f.read())
        self.assertGreater(len(references), 0)
        missing = []
        for module, name in references:
            with open(
                os.path.join(helpers.REPO_ROOT, "tests", f"{module}.py"),
                encoding="utf-8",
            ) as f:
                if name not in defined_tests(f.read()):
                    missing.append(f"{module}: {name}")
        self.assertEqual(
            missing, [], "docs/seeding-policy.md names tests that don't exist"
        )


if __name__ == "__main__":
    unittest.main()
