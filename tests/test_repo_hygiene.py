"""Checks on the repository itself rather than on a module's behavior:
every tracked file with a shebang is executable in git, so ruff's EXE001
(which only sees the exec bit on Linux, i.e. on CI) can't fail a push that
passed lint on Windows.

Run with: python -m unittest discover -s tests
"""

import os
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


if __name__ == "__main__":
    unittest.main()
