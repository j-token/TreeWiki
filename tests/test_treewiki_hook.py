from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "treewiki" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import treewiki_hook  # noqa: E402


class TreeWikiHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".knowledge").mkdir()
        self.write_config()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(
        self,
        *,
        capture: str = "explicit",
        execution: str = "same_thread",
        hooks_enabled: bool = True,
    ) -> None:
        config = {
            "memory": {
                "enabled": True,
                "capture": capture,
                "persona_requires_sources": 2,
            },
            "hooks": {
                "enabled": hooks_enabled,
                "execution": execution,
                "memory_stages": ["l0", "l1", "l2"],
                "l3": {"enabled": True, "minimum_sources": 2},
                "runbook": {
                    "enabled": True,
                    "require_user_confirmation": True,
                    "status": "draft",
                },
            },
        }
        (self.root / ".knowledge" / "config.yml").write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def payload(self, event: str, message: str = "작업을 완료했습니다.") -> dict[str, object]:
        return {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.root),
            "hook_event_name": event,
            "last_assistant_message": message,
            "prompt": "기능을 구현해줘",
        }

    def test_stop_never_emits_memory_and_only_reviews_runbook_once(self) -> None:
        output = treewiki_hook.process_event(self.payload("Stop"))
        self.assertIsNotNone(output)
        reason = str(output["reason"])
        self.assertIn("runbook proposal review", reason)
        self.assertIn("이번 작업을 인수인계용 runbook으로 남길까요?", reason)
        self.assertIn("만들거나 기존 파일을 갱신하지", reason)
        self.assertNotIn("lifecycle hook: L0", reason)
        self.assertNotIn("lifecycle hook: L1", reason)
        self.assertNotIn("lifecycle hook: L2", reason)
        self.assertNotIn("L3 eligibility", reason)
        self.assertIsNone(treewiki_hook.process_event(self.payload("Stop")))
        self.assertFalse((self.root / ".knowledge" / "private-memory").exists())

    def test_unfinished_choice_reaches_signal_review_without_forcing_proposal(self) -> None:
        message = "구현 방향을 두 가지로 좁혔습니다. 어느 쪽으로 진행할까요?"
        output = treewiki_hook.process_event(self.payload("Stop", message))
        self.assertIsNotNone(output)
        self.assertIn(
            "아직 승인·선택·추가정보를 기다리는 중이면 질문 없이",
            str(output["reason"]),
        )

    def test_legacy_hook_capture_is_blocked_on_stop_and_session_end(self) -> None:
        self.write_config(capture="hook")
        self.assertIsNone(treewiki_hook.process_event(self.payload("Stop")))
        self.assertIsNone(treewiki_hook.process_event(self.payload("SessionEnd")))
        self.assertFalse(treewiki_hook.state_path(self.root, "session-1").exists())
        self.assertFalse((self.root / ".knowledge" / "private-memory").exists())

    def test_session_end_never_creates_memory_documents(self) -> None:
        output = treewiki_hook.process_event(self.payload("UserPromptSubmit"))
        self.assertIsNotNone(output)
        self.assertIn("Stop과 SessionEnd는 기억 저장·증류를 시작하지 않습니다", str(output))
        self.assertIsNone(treewiki_hook.process_event(self.payload("SessionEnd")))
        self.assertFalse((self.root / ".knowledge" / "private-memory").exists())

    def test_agent_execution_has_same_thread_fallback(self) -> None:
        self.write_config(execution="agent")
        output = treewiki_hook.process_event(self.payload("Stop"))
        self.assertIn("독립 에이전트", str(output["reason"]))
        self.assertIn("현재 스레드", str(output["reason"]))

    def test_global_fallback_is_used_outside_treewiki_repository(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        self.assertEqual(
            treewiki_hook.find_repository(outside, fallback=self.root),
            self.root.resolve(),
        )

    def test_treewiki_settings_take_precedence_over_legacy_settings(self) -> None:
        settings = self.root / "settings"
        settings.mkdir()
        other = self.root / "other"
        (other / ".knowledge").mkdir(parents=True)
        (other / ".knowledge" / "config.yml").write_text("version: 3\n", encoding="utf-8")
        (settings / "treewiki-global.json").write_text(
            json.dumps(
                {
                    "schema": "treewiki.hook-settings/v1",
                    "fallback_repository": str(self.root.resolve()),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (settings / "lmwiki-global.json").write_text(
            json.dumps({"fallback_repository": str(other.resolve())}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(
            Path(treewiki_hook.global_fallback_repository(settings)),
            self.root.resolve(),
        )

    def test_invalid_treewiki_settings_do_not_fall_back_to_legacy(self) -> None:
        settings = self.root / "settings"
        settings.mkdir()
        (settings / "treewiki-global.json").write_text(
            '{"fallback_repository":"relative"}\n', encoding="utf-8"
        )
        (settings / "lmwiki-global.json").write_text(
            json.dumps({"fallback_repository": str(self.root.resolve())}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "schema"):
            treewiki_hook.global_fallback_repository(settings)


if __name__ == "__main__":
    unittest.main()
