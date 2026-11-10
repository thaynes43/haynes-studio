"""Tests for the tracked-file media guard."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / 'check_no_media.py'


def git(repo, *args):
    subprocess.run(
        [
            'git', '-C', str(repo),
            '-c', 'user.name=Test',
            '-c', 'user.email=test@example.com',
            '-c', 'commit.gpgsign=false',
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def check(repo):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
    )


class CheckNoMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        git(self.repo, 'init', '-b', 'main')
        for name in ('notes.md', 'data.json', 'tool.py', 'page.html'):
            (self.repo / name).write_text('text\n', encoding='utf-8')
        git(self.repo, 'add', '--', 'notes.md', 'data.json', 'tool.py', 'page.html')
        git(self.repo, 'commit', '-m', 'add text files')

    def test_good_tree_passes(self):
        # Untracked media is outside the check; only git ls-files counts.
        (self.repo / 'draft.png').write_text('', encoding='utf-8')
        result = check(self.repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    def test_bad_tree_fails_and_names_the_file(self):
        (self.repo / 'shot.MP4').write_text('', encoding='utf-8')
        git(self.repo, 'add', '-f', '--', 'shot.MP4')
        git(self.repo, 'commit', '-m', 'add a clip')
        result = check(self.repo)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout,
            'shot.MP4: tracked file has media or model-weight extension .mp4\n',
        )


if __name__ == '__main__':
    unittest.main()
