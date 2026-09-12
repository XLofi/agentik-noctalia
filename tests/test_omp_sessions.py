import datetime
import importlib.util
import json
import os
import tempfile
import sqlite3
import unittest
from unittest import mock
import time
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "omp_sessions.py"
SPEC = importlib.util.spec_from_file_location("omp_sessions", MODULE_PATH)
omp_sessions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(omp_sessions)


class SessionCollectorTests(unittest.TestCase):
    now = 1_000.0

    def collect(self, records: list[dict], live: bool | None = None) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "2026-01-01_example.jsonl"
            journal.write_text("\n".join(json.dumps(record) for record in records))
            os.utime(journal, (self.now - 3, self.now - 3))
            result = omp_sessions.session(journal, self.now, live=live)
        self.assertIsNotNone(result)
        return result

    def test_current_todo_is_exposed_as_active_task(self) -> None:
        result = self.collect([
            {"message": {"role": "assistant", "content": [{
                "type": "toolCall", "arguments": {"cwd": "/work/agentik"},
            }]}},
            {"data": {"intent": "Implement attention surface"}},
            {"message": {"role": "toolResult", "toolName": "todo", "content": [{
                "type": "text",
                "text": "Remaining items (1):\n  - Render attention state [in_progress] (Implementation)",
            }]}},
        ])

        self.assertEqual(result["project"], "agentik")
        self.assertEqual(result["cwd"], "/work/agentik")
        self.assertEqual(result["task"], "Render attention state")
        self.assertEqual(result["attention"], "active")
        self.assertEqual(result["state"], "composing")
        self.assertTrue(result["todo_active"])

    def test_todo_progress_is_exposed_from_snapshot(self) -> None:
        result = self.collect([
            {"message": {"role": "toolResult", "toolName": "todo", "content": [{
                "type": "text",
                "text": (
                    "Remaining items (4):\n"
                    "  - Render progress circle [in_progress] (Widget)\n"
                    "Overall: 3/7 done, 4 open."
                ),
            }]}},
        ])

        self.assertEqual(result["task"], "Render progress circle")
        self.assertEqual(result["todo_completed"], 3)
        self.assertEqual(result["todo_total"], 7)
        self.assertTrue(result["todo_active"])

    def test_blocked_todo_takes_precedence_over_waiting_intent(self) -> None:
        result = self.collect([
            {"data": {"intent": "Waiting for user input"}},
            {"message": {"role": "toolResult", "toolName": "todo", "content": [{
                "type": "text",
                "text": "Remaining items (1):\n  - Authenticate GitHub account (blocked: credentials unavailable)",
            }]}},
        ])

        self.assertEqual(result["task"], "Authenticate GitHub account")
        self.assertEqual(result["attention"], "blocked")
        self.assertEqual(result["state"], "listening")
        self.assertFalse(result["todo_active"])

    def test_listening_intent_is_marked_waiting(self) -> None:
        result = self.collect([{"data": {"intent": "Awaiting user input"}}])

        self.assertIsNone(result["task"])
        self.assertIsNone(result["agent"])
        self.assertEqual(result["attention"], "waiting")

    def test_completed_todo_clears_previous_task(self) -> None:
        result = self.collect([
            {"message": {"role": "toolResult", "toolName": "todo", "content": [{
                "type": "text",
                "text": "Remaining items (1):\n  - Publish plugin [in_progress] (Implementation)",
            }]}},
            {"message": {"role": "toolResult", "toolName": "todo", "content": [{
                "type": "text", "text": "Remaining items: none.",
            }]}},
        ])

        self.assertIsNone(result["task"])
        self.assertEqual(result["attention"], "active")
        self.assertFalse(result["todo_active"])

    def test_duration_and_idle_derived_from_journal_timestamps(self) -> None:
        first = datetime.datetime.fromtimestamp(
            self.now - 10, datetime.timezone.utc
        ).isoformat().replace("+00:00", "Z")
        last = datetime.datetime.fromtimestamp(
            self.now - 5, datetime.timezone.utc
        ).isoformat()
        result = self.collect([
            {"timestamp": first, "type": "message", "message": {
                "role": "toolResult", "toolName": "todo",
                "content": [{"type": "text", "text": "Remaining items: none."}],
            }},
            {"timestamp": last, "type": "message", "message": {
                "role": "toolResult", "toolName": "todo",
                "content": [{"type": "text", "text": "Remaining items: none."}],
            }},
        ])

        self.assertEqual(result["duration"], 10)
        self.assertEqual(result["idle"], 3)
        self.assertNotIn("elapsed", result)

    def test_assistant_choices_are_exposed_with_copy_values(self) -> None:
        result = self.collect([
            {"data": {"intent": "Waiting for user input"}},
            {"message": {"role": "assistant", "content": [{
                "type": "text",
                "text": "Choose an approach:\n1. Keep the current layout\n2. Use a compact layout",
            }]}},
        ])

        self.assertEqual(result["attention"], "waiting")
        self.assertEqual(result["propositions"], [
            {"value": "1", "label": "Keep the current layout"},
            {"value": "2", "label": "Use a compact layout"},
        ])

    def test_user_reply_clears_previous_choices(self) -> None:
        result = self.collect([
            {"message": {"role": "assistant", "content": [{
                "type": "text",
                "text": "Which option do you prefer?\n1. First\n2. Second",
            }]}},
            {"message": {"role": "user", "content": [{"type": "text", "text": "1"}]}},
        ])

        self.assertIsNone(result["propositions"])

    def test_structured_choices_preserve_explicit_response_values(self) -> None:
        result = self.collect([{
            "data": {"options": [
                {"value": "keep", "label": "Keep the current layout"},
                {"value": "compact", "label": "Use a compact layout"},
            ]},
        }])

        self.assertEqual(result["propositions"], [
            {"value": "keep", "label": "Keep the current layout"},
            {"value": "compact", "label": "Use a compact layout"},
        ])

    def test_numbered_plan_without_choice_prompt_is_ignored(self) -> None:
        result = self.collect([{"message": {"role": "assistant", "content": [{
            "type": "text",
            "text": "Implementation plan:\n1. Update the collector\n2. Update the panel",
        }]}}])

        self.assertIsNone(result["propositions"])

    def test_non_contiguous_numbered_choices_are_ignored(self) -> None:
        result = self.collect([{"message": {"role": "assistant", "content": [{
            "type": "text",
            "text": "Choose one:\n1. First option\nMore detail\n2. Second option",
        }]}}])

        self.assertIsNone(result["propositions"])

    def test_agent_name_and_model_derived_from_journal(self) -> None:
        result = self.collect([
            {"type": "session", "title": "Initial title"},
            {"type": "model_change", "model": "openai-codex/gpt-5.6-terra"},
            {"type": "title_change", "title": "Optimize wallpaper on battery"},
            {"type": "model_change", "model": "anthropic/claude-sonnet-4.5"},
        ])

        self.assertEqual(result["agent"], "Optimize wallpaper on battery")
        self.assertEqual(result["model"], "anthropic/claude-sonnet-4.5")

    def test_agent_falls_back_to_session_title(self) -> None:
        result = self.collect([{"type": "session", "title": "Initial title"}])

        self.assertEqual(result["agent"], "Initial title")
        self.assertIsNone(result["model"])

    def test_every_visual_activity_state_is_classified(self) -> None:
        cases = {
            "Working on response": "working",
            "Reading source": "searching",
            "Verifying behavior": "solving",
            "Waiting for user input": "listening",
            "Fetching documentation": "connecting",
            "Merging repository changes": "weaving",
            "Writing implementation": "composing",
            "Finishing task": "breathing",
            "Planning settings surface": "shaping",
        }

        self.assertEqual(
            {activity: omp_sessions.activity_state(activity) for activity in cases},
            cases,
        )

    def test_live_turn_lifecycle_states_are_preserved(self) -> None:
        waiting = self.collect([{
            "message": {"role": "assistant", "stopReason": "stop", "content": []},
        }], live=True)
        failed = self.collect([{
            "message": {"role": "assistant", "stopReason": "error", "content": []},
        }], live=True)
        cancelled = self.collect([{
            "message": {"role": "assistant", "stopReason": "aborted", "content": []},
        }], live=True)

        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["attention"], "waiting")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["state"], "done")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["state"], "done")

    def test_closed_session_uses_recorded_termination(self) -> None:
        failed = self.collect([{
            "type": "custom",
            "data": {"kind": "fatal", "reason": "unhandled_rejection"},
        }], live=False)
        completed = self.collect([{
            "type": "custom",
            "data": {"kind": "normal", "reason": "dispose"},
        }], live=False)

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["exited"])


    def test_active_hermes_process_is_collected_from_local_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE sessions (
                    id TEXT, title TEXT, model TEXT, cwd TEXT, started_at REAL,
                    last_activity_at REAL, last_activity_description TEXT,
                    ended_at REAL, archived INTEGER
                )
                """
            )
            connection.execute(
                """
                INSERT INTO sessions VALUES (
                    'hermes-live', 'Improve collector', 'ollama/test', '/work/agentik',
                    990, 999, 'Writing session monitor', NULL, 0
                )
                """
            )
            connection.commit()
            connection.close()
            original_connect = sqlite3.connect
            connections: list[sqlite3.Connection] = []

            def track_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
                opened = original_connect(*args, **kwargs)
                connections.append(opened)
                return opened

            with mock.patch.object(omp_sessions, "HERMES_DB", database), mock.patch.object(
                omp_sessions, "running_hermes_processes", return_value=[(42, "/work/fallback")]
            ), mock.patch.object(omp_sessions.sqlite3, "connect", side_effect=track_connect):
                sessions = omp_sessions.active_hermes_sessions(self.now)

            self.assertEqual(len(connections), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                connections[0].execute("SELECT 1")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "hermes:hermes-live")
        self.assertEqual(sessions[0]["agent"], "Hermes Agent")
        self.assertEqual(sessions[0]["project"], "agentik")
        self.assertEqual(sessions[0]["task"], "Improve collector")
        self.assertEqual(sessions[0]["activity"], "Writing session monitor")
        self.assertEqual(sessions[0]["model"], "ollama/test")
        self.assertEqual(sessions[0]["duration"], 10)

    def test_active_hermes_process_without_database_session_is_still_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            omp_sessions, "HERMES_DB", Path(directory) / "missing.db"
        ), mock.patch.object(
            omp_sessions, "running_hermes_processes", return_value=[(42, "/work/fallback")]
        ):
            sessions = omp_sessions.active_hermes_sessions(self.now)

        self.assertEqual(sessions[0]["id"], "hermes:pid:42")
        self.assertEqual(sessions[0]["project"], "fallback")
        self.assertEqual(sessions[0]["activity"], "Running Hermes Agent")
    def test_recently_exited_session_is_listed_with_exit_age(self) -> None:
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "2026-01-01_exited.jsonl"
            journal.write_text(json.dumps({"type": "session", "title": "Finished task"}))
            os.utime(journal, (now - 300, now - 300))
            result = omp_sessions.session(journal, now)
        self.assertIsNotNone(result)
        self.assertEqual(result["exited"], 300)
        self.assertEqual(result["state"], "done")

    def test_long_idle_journal_is_excluded(self) -> None:
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "2026-01-01_gone.jsonl"
            journal.write_text("{}")
            os.utime(journal, (now - 3600, now - 3600))
            result = omp_sessions.session(journal, now)
        self.assertIsNone(result)

    def test_live_journal_remains_active_after_quiet_threshold(self) -> None:
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as directory:
            original_journals = omp_sessions.JOURNALS
            omp_sessions.JOURNALS = Path(directory)
            try:
                journal = Path(directory) / "2026-01-01_quiet.jsonl"
                journal.write_text(json.dumps({"type": "session", "title": "Quiet task"}))
                os.utime(journal, (now - 31, now - 31))
                result = omp_sessions.session(journal, now)
                self.assertIsNotNone(result)
                self.assertTrue(result["quiet"])
                with mock.patch.object(omp_sessions.time, "time", return_value=now), mock.patch.object(
                    omp_sessions, "running_hermes_processes", return_value=[]
                ), mock.patch.object(
                    omp_sessions, "running_omp_journals", return_value={str(journal.resolve())}
                ):
                    import contextlib
                    import io

                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        omp_sessions.main()
                    data = json.loads(buffer.getvalue())
            finally:
                omp_sessions.JOURNALS = original_journals
        self.assertEqual(data["active"], 1)
        self.assertEqual(data["sessions"][0]["id"], "quiet")
        self.assertFalse(data["sessions"][0]["quiet"])

    def test_quiet_journal_reactivates_after_write(self) -> None:
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "2026-01-01_resume.jsonl"
            journal.write_text(json.dumps({"type": "session", "title": "Resumed task"}))
            os.utime(journal, (now - 31, now - 31))
            quiet = omp_sessions.session(journal, now)
            self.assertIsNotNone(quiet)
            self.assertTrue(quiet["quiet"])
            journal.write_text(json.dumps({"type": "session", "title": "Resumed task"}) + "\n{}")
            os.utime(journal, (now - 3, now - 3))
            active = omp_sessions.session(journal, now)
        self.assertIsNotNone(active)
        self.assertFalse(active["quiet"])
        self.assertIsNone(active["exited"])

    def test_main_lists_active_before_exited_within_cap(self) -> None:
        import contextlib
        import io

        now = time.time()
        with tempfile.TemporaryDirectory() as directory:
            original_journals = omp_sessions.JOURNALS
            original_cache_path = omp_sessions.CACHE_PATH
            omp_sessions.JOURNALS = Path(directory)
            omp_sessions.CACHE_PATH = Path(directory) / "journal-index.json"
            try:
                entries = [
                    ("active-a", now - 10, 10),
                    ("active-b", now - 20, 20),
                    ("exited-c", now - 300, 300),
                    ("exited-d", now - 500, 500),
                ]
                for name, mtime, exit_age in entries:
                    first_ts = datetime.datetime.fromtimestamp(
                        now - exit_age, tz=datetime.timezone.utc
                    ).isoformat()
                    journal = Path(directory) / f"2026-01-01_{name}.jsonl"
                    journal.write_text(json.dumps({
                        "type": "session",
                        "title": name,
                        "timestamp": first_ts,
                    }))
                    os.utime(journal, (mtime, mtime))
                with mock.patch.object(omp_sessions, "running_hermes_processes", return_value=[]), mock.patch.object(
                    omp_sessions,
                    "running_omp_journals",
                    return_value={
                        str((Path(directory) / "2026-01-01_active-a.jsonl").resolve()),
                        str((Path(directory) / "2026-01-01_active-b.jsonl").resolve()),
                    },
                ):
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        omp_sessions.main()
                    data = json.loads(buffer.getvalue())
            finally:
                omp_sessions.JOURNALS = original_journals
                omp_sessions.CACHE_PATH = original_cache_path
        self.assertEqual(data["active"], 2)
        self.assertEqual(
            [s["id"] for s in data["sessions"]],
            ["active-a", "active-b", "exited-c", "exited-d"],
        )

    def test_main_never_hides_active_sessions_behind_history_cap(self) -> None:
        import contextlib
        import io

        now = time.time()
        with tempfile.TemporaryDirectory() as directory:
            original_journals = omp_sessions.JOURNALS
            original_cache_path = omp_sessions.CACHE_PATH
            omp_sessions.JOURNALS = Path(directory)
            omp_sessions.CACHE_PATH = Path(directory) / "journal-index.json"
            try:
                live = set()
                for index in range(9):
                    journal = Path(directory) / f"2026-01-01_active-{index}.jsonl"
                    journal.write_text(json.dumps({"type": "session", "title": str(index)}))
                    live.add(str(journal.resolve()))
                with mock.patch.object(
                    omp_sessions, "running_hermes_processes", return_value=[]
                ), mock.patch.object(
                    omp_sessions, "running_omp_journals", return_value=live
                ):
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        omp_sessions.main()
                    data = json.loads(buffer.getvalue())
            finally:
                omp_sessions.JOURNALS = original_journals
                omp_sessions.CACHE_PATH = original_cache_path

        self.assertEqual(data["active"], 9)
        self.assertEqual(len(data["sessions"]), 9)



if __name__ == "__main__":
    unittest.main()
