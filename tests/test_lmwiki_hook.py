from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "lmwiki" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import lmwiki_hook  # noqa: E402


class LmwikiHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".knowledge").mkdir()
        self.write_config()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self, *, capture: str = "hook", execution: str = "same_thread") -> None:
        config = {
            "memory": {
                "enabled": True,
                "capture": capture,
                "persona_requires_sources": 2,
            },
            "hooks": {
                "enabled": True,
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

    def test_stop_emits_l0_l1_l2_then_runbook_proposal_review(self) -> None:
        reasons = []
        for _ in range(4):
            output = lmwiki_hook.process_event(self.payload("Stop"))
            self.assertIsNotNone(output)
            reasons.append(str(output["reason"]))
        self.assertIn("L0", reasons[0])
        self.assertIn("L1", reasons[1])
        self.assertIn("L2", reasons[2])
        self.assertIn("runbook proposal review", reasons[3])
        self.assertIn("이번 작업을 인수인계용 runbook으로 남길까요?", reasons[3])
        self.assertIn("만들거나 기존 파일을 갱신하지", reasons[3])
        self.assertIsNone(lmwiki_hook.process_event(self.payload("Stop")))

    def test_l3_requires_programmatic_source_threshold(self) -> None:
        memory_dir = self.root / ".knowledge" / "private-memory" / "l1"
        memory_dir.mkdir(parents=True)
        for index in (1, 2):
            (memory_dir / f"source-{index}.md").write_text(
                "---\n"
                f"id: MEMORY-L1-TEST-00{index}\n"
                "type: memory\nstatus: active\nauthority: informative\n"
                "memory:\n  level: l1\n  subject: user:owner\n  confidence: 0.8\n"
                "---\n\n# source\n",
                encoding="utf-8",
            )
        outputs = [lmwiki_hook.process_event(self.payload("Stop")) for _ in range(4)]
        self.assertIn("L3 eligibility passed", str(outputs[3]["reason"]))
        output = lmwiki_hook.process_event(self.payload("Stop"))
        self.assertIn("runbook proposal review", str(output["reason"]))

    def test_unfinished_choice_reaches_signal_review_without_forcing_proposal(self) -> None:
        message = "구현 방향을 두 가지로 좁혔습니다. 어느 쪽으로 진행할까요?"
        reasons = []
        for _ in range(4):
            output = lmwiki_hook.process_event(self.payload("Stop", message))
            self.assertIsNotNone(output)
            reasons.append(str(output["reason"]))
        self.assertIn("아직 승인·선택·추가정보를 기다리는 중이면 질문 없이", reasons[3])

    def test_existing_persona_coverage_suppresses_l3(self) -> None:
        memory_dir = self.root / ".knowledge" / "private-memory"
        (memory_dir / "l1").mkdir(parents=True)
        (memory_dir / "l3").mkdir(parents=True)
        for index in (1, 2):
            (memory_dir / "l1" / f"source-{index}.md").write_text(
                "---\n"
                f"id: MEMORY-L1-TEST-00{index}\n"
                "type: memory\nstatus: active\nauthority: informative\n"
                "memory:\n  level: l1\n  subject: user:owner\n  confidence: 0.8\n"
                "---\n",
                encoding="utf-8",
            )
        (memory_dir / "l3" / "persona.md").write_text(
            "---\n"
            "id: PERSONA-TEST-001\ntype: persona\nstatus: active\nauthority: informative\n"
            "relations:\n"
            "  - type: distilled_from\n    target: MEMORY-L1-TEST-001\n"
            "  - type: distilled_from\n    target: MEMORY-L1-TEST-002\n"
            "memory:\n  level: l3\n  subject: user:owner\n  confidence: 0.8\n"
            "---\n",
            encoding="utf-8",
        )
        self.assertEqual(lmwiki_hook.l3_candidates(self.root, 2), {})

    def test_explicit_capture_does_not_emit_memory_layers(self) -> None:
        self.write_config(capture="explicit")
        output = lmwiki_hook.process_event(self.payload("Stop"))
        self.assertIn("runbook proposal review", str(output["reason"]))

    def test_agent_execution_has_same_thread_fallback(self) -> None:
        self.write_config(execution="agent")
        output = lmwiki_hook.process_event(self.payload("Stop"))
        self.assertIn("독립 에이전트", str(output["reason"]))
        self.assertIn("현재 스레드", str(output["reason"]))

    def test_global_fallback_is_used_outside_lmwiki_repository(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        self.assertEqual(
            lmwiki_hook.find_repository(outside, fallback=self.root),
            self.root.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
