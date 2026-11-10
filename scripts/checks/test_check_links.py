import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_links.py")


def make_repo(files):
    """Create a temporary git repo holding the given {path: text} files."""
    tmp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", tmp.name], check=True)
    for rel, text in files.items():
        path = os.path.join(tmp.name, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    subprocess.run(["git", "-C", tmp.name, "add", "-A"], check=True)
    return tmp


def run(root):
    p = subprocess.run([sys.executable, SCRIPT, root], capture_output=True, text=True)
    return p.returncode, p.stdout


class CheckLinksTest(unittest.TestCase):
    def test_good_tree_passes(self):
        with make_repo({
            "README.md": "[doc](docs/a.md#top) ![pic](docs/pic.png?raw=1) [dir](docs/)\n"
                         "[web](https://example.com) [m](mailto:a@b.c) [h](#here)\n",
            "docs/a.md": "[up](../README.md) [self](a.md#x)\n",
            "docs/pic.png": "",
        }) as tmp:
            code, out = run(tmp)
            self.assertEqual(code, 0, out)

    def test_bad_tree_fails_and_names_item(self):
        with make_repo({
            "README.md": "[ok](docs/a.md)\n",
            "docs/a.md": "line one\n[gone](missing.md#frag)\n![img](../nope.png)\n",
        }) as tmp:
            code, out = run(tmp)
            self.assertEqual(code, 1)
            self.assertIn("docs/a.md:2: broken link 'missing.md#frag'", out)
            self.assertIn("docs/a.md:3: broken link '../nope.png'", out)
            self.assertNotIn("README.md", out)

    def test_fenced_code_is_skipped(self):
        with make_repo({"README.md": "```\n[x](nowhere.md)\n```\n~~~\n[y](nowhere.md)\n~~~\n"}) as tmp:
            code, out = run(tmp)
            self.assertEqual(code, 0, out)

    def test_nested_and_labelled_fences_stay_closed(self):
        # A longer fence holds a shorter one, and a fence with an info string
        # does not close a block; the link after the real close is checked.
        text = (
            "````\n```\n[a](nowhere.md)\n```\n[b](nowhere.md)\n````\n"
            "```\n```python\n[c](nowhere.md)\n```\n"
            "[real](missing.md)\n"
        )
        with make_repo({"README.md": text}) as tmp:
            code, out = run(tmp)
            self.assertEqual(code, 1, out)
            self.assertIn("README.md:11: broken link 'missing.md'", out)
            self.assertNotIn("nowhere.md", out)

    def test_untracked_markdown_is_ignored(self):
        with make_repo({"README.md": "hi\n"}) as tmp:
            with open(os.path.join(tmp, "extra.md"), "w") as f:
                f.write("[x](nowhere.md)\n")
            code, out = run(tmp)
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
