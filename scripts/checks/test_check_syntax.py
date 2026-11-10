"""Exercise the syntax check against tracked files in temporary repositories."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("check_syntax.py").resolve()


class CheckSyntaxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo with spaces"
        self.root.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", str(self.root)], check=True, capture_output=True
        )

    def write(self, path, source, tracked=True):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        if tracked:
            subprocess.run(
                ["git", "add", "--", path], cwd=self.root,
                check=True, capture_output=True,
            )

    def run_check(self, explicit_root=True):
        command = [sys.executable, str(SCRIPT)]
        if explicit_root:
            command.append(str(self.root))
        return subprocess.run(command, cwd=self.root, capture_output=True, text=True)

    def test_good_tree_and_scope(self):
        self.write("poc/nested/good.py", "import missing_dependency\nraise RuntimeError('never run')\n")
        self.write("titles/example/nested/good.json", '{"ok": true}\n')
        self.write("poc/graphs/nested/good.json", "[]\n")
        self.write("poc/untracked.py", "def broken(:\n", tracked=False)
        self.write("titles/untracked.json", "{", tracked=False)
        self.write("poc/graphs/untracked.json", "{", tracked=False)
        self.write("elsewhere/bad.py", "def broken(:\n")
        self.write("elsewhere/bad.json", "{")
        self.write("poc/not-a-graph.json", "{")
        self.write("titles/not-python.py", "def broken(:\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "Checked 1 Python files and 2 JSON files.\n")
        self.assertFalse(list(self.root.rglob("*.pyc")))
        self.assertFalse(list(self.root.rglob("__pycache__")))

    def test_bad_tree_reports_every_item_once(self):
        self.write("poc/nested/bad.py", "def broken(:\n")
        self.write("titles/example/bad.json", '{\n"bad":\n}\n')
        self.write("poc/graphs/bad.json", "{")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 3, result.stdout)
        for path in ("poc/nested/bad.py", "titles/example/bad.json", "poc/graphs/bad.json"):
            self.assertTrue(any(line.startswith(path + ": ") for line in lines), result.stdout)
        self.assertIn("invalid syntax", result.stdout)
        self.assertIn("Expecting", result.stdout)

    def test_defaults_to_current_directory(self):
        self.write("poc/good.py", "x = 1\n")
        result = self.run_check(explicit_root=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "Checked 1 Python files and 0 JSON files.\n")


if __name__ == "__main__":
    unittest.main()
