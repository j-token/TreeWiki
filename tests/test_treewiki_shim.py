from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "skills" / "lmwiki" / "scripts" / "knowledge_cli.py"


class TreeWikiShimTests(unittest.TestCase):
    def test_legacy_cli_warns_and_forwards_to_treewiki(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SHIM), "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("deprecated", result.stderr)
        self.assertIn("TreeWiki", result.stdout)

    def test_clean_machine_shim_reports_exact_install_command_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            isolated = root / "skills" / "lmwiki" / "scripts" / "knowledge_cli.py"
            isolated.parent.mkdir(parents=True)
            shutil.copy2(SHIM, isolated)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            result = subprocess.run(
                [sys.executable, str(isolated), "--help"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("LEGACY_TARGET_MISSING", result.stderr)
            self.assertIn(
                "npx skills add j-token/treewiki --skill treewiki -g -a codex -y --copy",
                result.stderr,
            )
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
