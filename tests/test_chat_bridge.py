import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "chat_bridge.py"
SPEC = importlib.util.spec_from_file_location("chat_bridge", MODULE_PATH)
chat_bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(chat_bridge)


def write_session(
    path: Path,
    session_id: str = "session-1",
    cwd: str = "/work/project",
    *,
    exited: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "session", "version": 3, "id": session_id, "cwd": cwd},
        {"type": "title_change", "id": "title", "parentId": None, "title": "Fix project"},
        {
            "type": "message",
            "id": "user",
            "parentId": "title",
            "message": {"role": "user", "content": [{"type": "text", "text": "Existing question"}]},
        },
        {
            "type": "message",
            "id": "assistant",
            "parentId": "user",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Existing answer"}]},
        },
    ]
    if exited:
        records.append({
            "type": "custom",
            "customType": "session_exit",
            "id": "exit",
            "parentId": "assistant",
            "data": {"kind": "normal"},
        })
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def write_fake_omp(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["OMP_CALLS"], "a") as calls:
    calls.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\\n")
if "--resume" in args:
    journal = Path(args[args.index("--resume") + 1])
    session_id = journal.stem.rsplit("_", 1)[-1]
elif "--fork" in args:
    source = Path(args[args.index("--fork") + 1])
    session_id = "fork-session"
    journal = Path(os.environ["AGENTIK_SESSIONS_DIR"]) / "fork" / ("probe_" + session_id + ".jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in source.read_text().splitlines()]
    records[0]["id"] = session_id
    journal.write_text("\\n".join(json.dumps(record) for record in records) + "\\n")
else:
    session_id = "new-session"
    journal = Path(os.environ["AGENTIK_SESSIONS_DIR"]) / "new" / ("probe_" + session_id + ".jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    cwd = args[args.index("--cwd") + 1]
    journal.write_text(json.dumps({"type": "session", "version": 3, "id": session_id, "cwd": cwd}) + "\\n")
records = [json.loads(line) for line in journal.read_text().splitlines()]
parent = next((record.get("id") for record in reversed(records) if record.get("id")), None)
suffix = str(len(records))
prompt = args[-1]
added = [
    {"type": "message", "id": "u" + suffix, "parentId": parent,
     "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
    {"type": "message", "id": "a" + suffix, "parentId": "u" + suffix,
     "message": {"role": "assistant", "content": [{"type": "text", "text": "reply: " + prompt}]}},
    {"type": "custom", "customType": "session_exit", "id": "x" + suffix,
     "parentId": "a" + suffix, "data": {"kind": "normal"}},
]
with journal.open("a") as output:
    for record in added:
        output.write(json.dumps(record) + "\\n")
print(json.dumps({"type": "session", "id": session_id}))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def write_slow_omp(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
session_id = "slow-session"
journal = Path(os.environ["AGENTIK_SESSIONS_DIR"]) / "slow" / ("probe_" + session_id + ".jsonl")
journal.parent.mkdir(parents=True, exist_ok=True)
cwd = args[args.index("--cwd") + 1]
prompt = args[-1]

def emit(event):
    print(json.dumps(event), flush=True)
emit({"type": "session", "version": 3, "id": session_id, "cwd": cwd})
with journal.open("w") as out:
    out.write(json.dumps({"type": "session", "version": 3, "id": session_id, "cwd": cwd}) + "\\n")
emit({"type": "message_start",
      "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})
time.sleep(0.4)
emit({"type": "message_update", "assistantMessageEvent": {"type": "text_start", "contentIndex": 1}})
emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 1, "delta": "Hel"}})
time.sleep(0.5)
emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 1, "delta": "lo"}})
time.sleep(0.45)
emit({"type": "message_update", "assistantMessageEvent": {"type": "text_end", "contentIndex": 1, "content": "Hello"}})
emit({"type": "message_end",
      "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}})
records = [
    {"type": "message", "id": "u1", "parentId": None,
     "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
    {"type": "message", "id": "a1", "parentId": "u1",
     "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}},
    {"type": "custom", "customType": "session_exit", "id": "x1", "parentId": "a1",
     "data": {"kind": "normal"}},
]
with journal.open("a") as out:
    for record in records:
        out.write(json.dumps(record) + "\\n")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)

def write_fake_hermes(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json, os, sqlite3, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["HERMES_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if "--resume" not in args:
    database = Path(os.environ["HERMES_HOME"]) / "state.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO sessions VALUES (?, 'cli', ?, ?, NULL, ?)",
        ("hermes-session", os.getcwd(), args[args.index("--model") + 1], time.time()),
    )
    connection.commit()
    connection.close()
print("hermes reply: " + args[args.index("--oneshot") + 1])
""",
        encoding="utf-8",
    )
    path.chmod(0o755)

TEST_CATALOG = json.dumps([
    {
        "id": "omp",
        "name": "Oh My Pi",
        "models": ["openai/gpt-test", "openai/gpt-other"],
        "default_model": "openai/gpt-test",
    },
    {
        "id": "hermes",
        "name": "Hermes Agent",
        "models": ["ollama-cloud/test-model", "ollama-cloud/other-model"],
        "default_model": "ollama-cloud/test-model",
    },
])


def new_args(cwd: Path, harness: str = "omp", model: str = "openai/gpt-test") -> tuple[str, str, str]:
    return str(cwd).encode().hex(), harness.encode().hex(), model.encode().hex()


def feed_texts(result: dict) -> list[str]:
    feed = result.get("feed") or {}
    return [
        event["text"] for event in feed.get("events", [])
        if event.get("kind") in ("user", "assistant")
    ]


def wait_for_idle(timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = chat_bridge.dispatch("status")
        if not result["busy"]:
            return result
        time.sleep(0.05)
    raise AssertionError("agent run did not become idle")

class ChatBridgeTests(unittest.TestCase):
    def test_parse_session_id_uses_session_event(self) -> None:
        output = "\n".join([
            json.dumps({"type": "session", "id": "session-1"}),
            json.dumps({"type": "message_end", "message": {"role": "assistant"}}),
        ])
        self.assertEqual(chat_bridge.parse_session_id(output), "session-1")

    def test_journal_events_cover_terminal_semantics(self) -> None:
        assistant = {
            "type": "message",
            "id": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "Plan"},
                {"type": "toolCall", "name": "todo", "intent": "Update tasks"},
                {"type": "toolCall", "name": "read", "intent": "Read source"},
                {"type": "toolCall", "name": "ask", "intent": "Pick an approach", "arguments": {
                    "questions": [{"question": "Which design?", "options": [
                        {"value": "a", "label": "Compact"},
                        {"label": "Detailed"},
                    ]}],
                }},
            ]},
        }
        output = {
            "type": "message",
            "id": "output",
            "message": {
                "role": "toolResult",
                "toolName": "read",
                "isError": True,
                "content": [{"type": "text", "text": "permission denied"}],
            },
        }
        todo_output = {
            "type": "message",
            "id": "todo-output",
            "message": {
                "role": "toolResult",
                "toolName": "todo",
                "content": [{"type": "text", "text":
                    "Remaining items (2):\n  - Render terminal completion [in_progress]\nOverall: 1/3 done"}],
            },
        }
        exit_record = {"type": "custom", "customType": "session_exit", "id": "exit", "data": {"kind": "normal"}}
        events = [
            *chat_bridge.journal_events(assistant),
            *chat_bridge.journal_events(output),
            *chat_bridge.journal_events(todo_output),
            *chat_bridge.journal_events(exit_record),
        ]
        self.assertEqual(
            [event["kind"] for event in events],
            ["thinking", "todo", "tool_call", "choice", "tool_output", "todo_update", "session_exit"],
        )
        self.assertEqual(events[3]["text"], "Which design?")
        self.assertEqual(events[3]["choices"], [
            {"value": "a", "label": "Compact"},
            {"value": "Detailed", "label": "Detailed"},
        ])
        self.assertTrue(events[4]["error"])
        self.assertEqual(events[5], {
            "id": "todo-output",
            "timestamp": None,
            "kind": "todo_update",
            "text": "Render terminal completion",
            "completed": 1,
            "total": 3,
            "complete": False,
        })

    def test_decode_message_validates_content(self) -> None:
        self.assertEqual(chat_bridge.decode_message("68656c6c6f"), "hello")
        with self.assertRaisesRegex(ValueError, "empty"):
            chat_bridge.decode_message("")
        with self.assertRaisesRegex(ValueError, "encoding"):
            chat_bridge.decode_message("xyz")

    def test_cli_returns_json_for_application_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {
                **os.environ,
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(root / "sessions"),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), "send", "6869"],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "select or start a session first")

    def test_descriptor_requires_exit_marker_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ended = root / "ended.jsonl"
            active = root / "active.jsonl"
            write_session(ended)
            write_session(active, "session-2", exited=False)

            ended_result = chat_bridge.session_descriptor(ended)
            active_result = chat_bridge.session_descriptor(active)
            transcript = chat_bridge.session_transcript(ended)
            owned_result = chat_bridge.session_descriptor(ended, {str(ended.resolve())})

        self.assertTrue(ended_result["resumable"])
        self.assertFalse(active_result["resumable"])
        self.assertFalse(owned_result["resumable"])
        self.assertEqual(ended_result["title"], "Fix project")
        self.assertEqual(
            [message["text"] for message in transcript],
            ["Existing question", "Existing answer"],
        )

    def test_harness_commands_preserve_native_capabilities(self) -> None:
        new = chat_bridge.omp_command(
            {"kind": "new", "cwd": "/work/project", "model": "openai/gpt-test"},
            "hello",
        )
        resumed = chat_bridge.omp_command(
            {"kind": "existing", "path": "/sessions/one.jsonl", "mode": "resume"},
            "again",
        )
        forked = chat_bridge.omp_command(
            {"kind": "existing", "path": "/sessions/live.jsonl", "mode": "fork"},
            "parallel",
        )
        hermes = chat_bridge.hermes_command(
            {"kind": "new", "cwd": "/work/project", "model": "ollama-cloud/test-model"},
            "hello",
        )
        self.assertEqual(new[new.index("--cwd") + 1], "/work/project")
        self.assertEqual(new[new.index("--model") + 1], "openai/gpt-test")
        self.assertEqual(resumed[resumed.index("--resume") + 1], "/sessions/one.jsonl")
        self.assertEqual(forked[forked.index("--fork") + 1], "/sessions/live.jsonl")
        self.assertEqual(hermes[hermes.index("--provider") + 1], "ollama-cloud")
        self.assertEqual(hermes[hermes.index("--model") + 1], "test-model")
        for command in (new, resumed, forked, hermes):
            self.assertNotIn("--no-tools", command)
            self.assertNotIn("--no-skills", command)
            self.assertNotIn("--no-rules", command)
            self.assertNotIn("--no-extensions", command)
            self.assertNotIn("--system-prompt", command)

    def test_new_session_then_resume_uses_real_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir()
            fake = root / "fake-omp"
            write_fake_omp(fake)
            calls = root / "calls.jsonl"
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "OMP_BIN": str(fake),
                "OMP_CALLS": str(calls),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            project = root / "project"
            project.mkdir()
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("new", *new_args(project))
                first = chat_bridge.dispatch("send", "hello".encode().hex())
                first_final = wait_for_idle()
                second = chat_bridge.dispatch("send", "again".encode().hex())
                second_final = wait_for_idle()
                loaded = chat_bridge.dispatch("load")

            self.assertTrue(selected["selected"])
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertFalse(first_final["busy"])
            self.assertFalse(second_final["busy"])
            self.assertEqual(loaded["session_id"], "new-session")
            self.assertEqual(
                feed_texts(loaded),
                ["hello", "reply: hello", "again", "reply: again"],
            )
            invocations = [json.loads(line)["args"] for line in calls.read_text().splitlines()]
            self.assertIn("--cwd", invocations[0])
            self.assertIn("--resume", invocations[1])

    def test_terminal_turn_refreshes_panel_and_hands_back_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            journal = sessions / "shared.jsonl"
            write_session(journal, cwd=str(project))
            fake = root / "fake-omp"
            write_fake_omp(fake)
            calls = root / "calls.jsonl"
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "OMP_BIN": str(fake),
                "OMP_CALLS": str(calls),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            terminal_turn = [
                {"type": "message", "id": "terminal-user", "parentId": "exit",
                 "message": {"role": "user", "content": [{"type": "text", "text": "From terminal"}]}},
                {"type": "message", "id": "terminal-assistant", "parentId": "terminal-user",
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "Terminal reply"}]}},
                {"type": "custom", "customType": "session_exit", "id": "terminal-exit",
                 "parentId": "terminal-assistant", "data": {"kind": "normal"}},
            ]
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("select", str(journal).encode().hex())
                with journal.open("a", encoding="utf-8") as output:
                    for record in terminal_turn:
                        output.write(json.dumps(record) + "\n")
                refreshed = chat_bridge.dispatch("status", selected["feed"]["revision"].encode().hex())
                replied = chat_bridge.dispatch("send", "From panel".encode().hex())
                replied = wait_for_idle()

            self.assertTrue(selected["ok"])
            self.assertTrue(refreshed["ok"])
            self.assertFalse(refreshed["active"])
            self.assertEqual(refreshed["mode"], "resume")
            self.assertEqual(
                feed_texts(refreshed)[-2:],
                ["From terminal", "Terminal reply"],
            )
            self.assertTrue(replied["ok"])
            invocation = json.loads(calls.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(invocation["args"][invocation["args"].index("--resume") + 1], str(journal))
            self.assertEqual(
                feed_texts(replied)[-2:],
                ["From panel", "reply: From panel"],
            )

    def test_status_replays_only_completed_appended_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            journal = sessions / "feed.jsonl"
            write_session(journal, cwd=str(project))
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            appended = {
                "type": "message",
                "id": "later",
                "parentId": "exit",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Incremental"}]},
            }
            with mock.patch.dict(os.environ, environment):
                initial = chat_bridge.dispatch("select", str(journal).encode().hex())
                revision = initial["feed"]["revision"]
                unchanged = chat_bridge.dispatch("status", revision.encode().hex())
                with journal.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(appended))
                partial = chat_bridge.dispatch("status", revision.encode().hex())
                with journal.open("a", encoding="utf-8") as output:
                    output.write("\n")
                delta = chat_bridge.dispatch("status", revision.encode().hex())

            self.assertTrue(unchanged["feed"]["unchanged"])
            self.assertEqual(partial["feed"], {"revision": revision, "unchanged": True})
            self.assertEqual([event["text"] for event in delta["feed"]["events"]], ["Incremental"])
            self.assertNotIn("reset", delta["feed"])

    def test_monitored_omp_session_is_selected_as_safe_fork(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            active = sessions / "active_session-1.jsonl"
            write_session(active, exited=False)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "active_terminal_session_paths", return_value={str(active.resolve())}
            ):
                result = chat_bridge.dispatch("select-id", "session-1".encode().hex())
                state = chat_bridge.read_state(root / "state/state.json")
            self.assertTrue(result["ok"])
            self.assertTrue(result["selected"])
            self.assertEqual(state["selection"]["path"], str(active.resolve()))
            self.assertEqual(state["selection"]["mode"], "fork")

    def test_monitored_hermes_session_is_selected_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "AGENTIK_STATE_DIR": str(Path(directory) / "state"),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            rows = {
                "session-1": {
                    "cwd": "/work/project",
                    "model": "ollama-cloud/test-model",
                    "title": "Fix Hermes project",
                    "modified": 0,
                },
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "hermes_session_rows", return_value=rows
            ):
                result = chat_bridge.dispatch("select-id", "hermes:session-1".encode().hex())
                state = chat_bridge.read_state(Path(directory) / "state/state.json")
            self.assertTrue(result["ok"])
            self.assertTrue(result["selected"])
            self.assertEqual(state["selection"]["kind"], "managed")
            self.assertEqual(state["selection"]["session_id"], "session-1")
            self.assertEqual(result["title"], "Fix Hermes project")

    def test_status_resets_when_an_append_changes_the_parent_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            journal = sessions / "branch.jsonl"
            write_session(journal)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            branch = {
                "type": "message",
                "id": "branch",
                "parentId": "user",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Branched answer"}]},
            }
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("select", str(journal).encode().hex())
                with journal.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(branch) + "\n")
                reset = chat_bridge.dispatch("status", selected["feed"]["revision"].encode().hex())

            self.assertTrue(reset["feed"]["reset"])
            self.assertEqual(feed_texts(reset), ["Existing question", "Branched answer"])

    def test_interrupted_session_is_selected_as_safe_fork(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            interrupted = sessions / "interrupted.jsonl"
            write_session(interrupted, exited=False)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "active_terminal_session_paths", return_value=set()
            ):
                targets = chat_bridge.list_targets()
                result = chat_bridge.dispatch("select", str(interrupted).encode().hex())
                state = chat_bridge.read_state(root / "state/state.json")
            self.assertTrue(targets[0]["forkable"])
            self.assertFalse(targets[0]["resumable"])
            self.assertTrue(result["ok"])
            self.assertEqual(state["selection"]["mode"], "fork")

    def test_custom_model_name_is_accepted_for_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            environment = {
                "AGENTIK_STATE_DIR": str(Path(directory) / "state"),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment):
                result = chat_bridge.dispatch("new", *new_args(project, "omp", "local/custom-model"))
            self.assertTrue(result["ok"])
            self.assertEqual(result["model"], "local/custom-model")

    def test_active_session_send_forks_without_writing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            active = sessions / "active.jsonl"
            write_session(active, cwd=str(project), exited=False)
            original = active.read_bytes()
            fake = root / "fake-omp"
            write_fake_omp(fake)
            calls = root / "calls.jsonl"
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
                "OMP_BIN": str(fake),
                "OMP_CALLS": str(calls),
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "active_terminal_session_paths", return_value={str(active.resolve())}
            ):
                selected = chat_bridge.dispatch("select", str(active).encode().hex())
                sent = chat_bridge.dispatch("send", "parallel".encode().hex())
                sent = wait_for_idle()
            invocation = json.loads(calls.read_text().splitlines()[0])
            self.assertTrue(selected["ok"])
            self.assertTrue(sent["ok"])
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual(invocation["args"][invocation["args"].index("--fork") + 1], str(active))
            self.assertEqual(invocation["cwd"], str(project))
            self.assertEqual(sent["session_id"], "fork-session")

    def test_hermes_new_session_persists_harness_model_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            hermes = root / "fake-hermes"
            write_fake_hermes(hermes)
            home = root / "hermes-home"
            home.mkdir()
            connection = chat_bridge.sqlite3.connect(home / "state.db")
            connection.execute(
                "CREATE TABLE sessions (id TEXT, source TEXT, cwd TEXT, model TEXT, title TEXT, last_activity_at REAL)"
            )
            connection.commit()
            connection.close()
            calls = root / "hermes-calls.jsonl"
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(root / "omp-sessions"),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
                "HERMES_BIN": str(hermes),
                "HERMES_HOME": str(home),
                "HERMES_CALLS": str(calls),
            }
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch(
                    "new", *new_args(project, "hermes", "ollama-cloud/other-model")
                )
                first = chat_bridge.dispatch("send", "hello".encode().hex())
                first = wait_for_idle()
                second = chat_bridge.dispatch("send", "again".encode().hex())
                second = wait_for_idle()
                loaded = chat_bridge.dispatch("load")
            invocations = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertTrue(selected["ok"])
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(loaded["harness"], "hermes")
            self.assertEqual(loaded["model"], "ollama-cloud/other-model")
            self.assertEqual(loaded["session_id"], "hermes-session")
            self.assertEqual(
                [message["text"] for message in loaded["messages"]],
                ["hello", "hermes reply: hello", "again", "hermes reply: again"],
            )
            self.assertNotIn("--resume", invocations[0])
            self.assertEqual(invocations[1][invocations[1].index("--resume") + 1], "hermes-session")
            self.assertEqual(invocations[0][invocations[0].index("--model") + 1], "other-model")

    def test_reset_forgets_selection_without_deleting_real_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            ended = sessions / "ended.jsonl"
            write_session(ended)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
            }):
                selected = chat_bridge.dispatch("select", str(ended).encode().hex())
                result = chat_bridge.dispatch("reset")
                loaded = chat_bridge.dispatch("load")

            self.assertTrue(selected["selected"])
            self.assertTrue(result["ok"])
            self.assertFalse(loaded["selected"])
            self.assertTrue(ended.exists())

    def test_open_in_terminal_resumes_finished_omp_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            ended = sessions / "ended.jsonl"
            write_session(ended)
            environment = {
                **os.environ,
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
                "AGENTIK_TERMINAL": "fake-term",
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "active_terminal_session_paths", return_value=set()
            ):
                selected = chat_bridge.dispatch("select", str(ended).encode().hex())
                with mock.patch.object(chat_bridge.subprocess, "Popen") as popen:
                    result = chat_bridge.dispatch("open")
            argv = popen.call_args.args[0]
            self.assertTrue(selected["ok"])
            self.assertTrue(result["ok"])
            self.assertEqual(result["terminal"], "fake-term")
            self.assertEqual(argv[0], "fake-term")
            self.assertEqual(argv[1], "-e")
            self.assertIn("--resume", argv)
            self.assertEqual(argv[argv.index("--resume") + 1], str(ended.resolve()))
            self.assertEqual(popen.call_args.kwargs["cwd"], "/work/project")
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_open_in_terminal_forks_active_omp_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            active = sessions / "active.jsonl"
            write_session(active, exited=False)
            environment = {
                **os.environ,
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
                "AGENTIK_TERMINAL": "fake-term",
            }
            with mock.patch.dict(os.environ, environment), mock.patch.object(
                chat_bridge, "active_terminal_session_paths", return_value={str(active.resolve())}
            ):
                selected = chat_bridge.dispatch("select", str(active).encode().hex())
                with mock.patch.object(chat_bridge.subprocess, "Popen") as popen:
                    result = chat_bridge.dispatch("open")
            argv = popen.call_args.args[0]
            self.assertTrue(selected["ok"])
            self.assertTrue(result["ok"])
            self.assertIn("--fork", argv)
            self.assertEqual(argv[argv.index("--fork") + 1], str(active.resolve()))

    def test_open_in_terminal_resumes_managed_hermes_session(self) -> None:
        state = chat_bridge.empty_state()
        state["selection"] = {
            "kind": "managed",
            "harness": "hermes",
            "session_id": "abc-123",
            "cwd": "/work/project",
            "model": "ollama/test-model",
        }
        with mock.patch.dict(os.environ, {"AGENTIK_TERMINAL": "fake-term"}), mock.patch.object(
            chat_bridge.subprocess, "Popen"
        ) as popen:
            result = chat_bridge.open_in_terminal(state)
        argv = popen.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "abc-123")
        self.assertEqual(popen.call_args.kwargs["cwd"], "/work/project")

    def test_open_in_terminal_starts_new_session_with_model(self) -> None:
        state = chat_bridge.empty_state()
        state["selection"] = {
            "kind": "new",
            "harness": "omp",
            "cwd": "/work/new",
            "model": "openai/gpt-test",
        }
        with mock.patch.dict(os.environ, {"AGENTIK_TERMINAL": "fake-term"}), mock.patch.object(
            chat_bridge.subprocess, "Popen"
        ) as popen:
            result = chat_bridge.open_in_terminal(state)
        argv = popen.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "openai/gpt-test")

    def test_open_in_terminal_requires_selection(self) -> None:
        with mock.patch.object(chat_bridge.subprocess, "Popen") as popen:
            result = chat_bridge.open_in_terminal(chat_bridge.empty_state())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "select or start a session first")
        popen.assert_not_called()

    def test_open_in_terminal_reports_missing_terminal(self) -> None:
        state = chat_bridge.empty_state()
        state["selection"] = {"kind": "new", "harness": "omp", "cwd": "/work", "model": None}
        with mock.patch.object(chat_bridge.shutil, "which", return_value=None), mock.patch.object(
            chat_bridge.subprocess, "Popen"
        ) as popen:
            result = chat_bridge.open_in_terminal(state)
        self.assertFalse(result["ok"])
        self.assertIn("no terminal emulator found", result["error"])
        popen.assert_not_called()
    def test_status_idle_without_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(state_dir),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("status")
        self.assertTrue(result["ok"])
        self.assertFalse(result["busy"])
        self.assertEqual(result["messages"], [])

    def test_send_streams_partial_messages_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            fake = root / "slow-omp"
            write_slow_omp(fake)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "OMP_BIN": str(fake),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("new", *new_args(project, "omp", "openai/gpt-test"))
                self.assertTrue(selected["ok"])
                started = chat_bridge.dispatch("send", "hello".encode().hex())
                self.assertTrue(started["busy"])
                time.sleep(0.6)
                snapshot = chat_bridge.read_state(root / "state/state.json")
                stream = snapshot.get("stream")
                self.assertIsNotNone(stream, "a busy stream is written while the harness runs")
                self.assertTrue(stream["busy"])
                texts = [message["text"] for message in stream["messages"]]
                self.assertEqual(texts[0], "hello")
                self.assertEqual(len(texts), 2, "an in-progress assistant message is visible")
                time.sleep(0.6)
                snapshot = chat_bridge.read_state(root / "state/state.json")
                texts = [message["text"] for message in snapshot["stream"]["messages"]]
                self.assertIn("Hello", texts, "the text grows before the harness exits")
                final = wait_for_idle()
                self.assertTrue(final["ok"])
                self.assertEqual(final["session_id"], "slow-session")
                self.assertEqual(feed_texts(final), ["hello", "Hello"])

    def test_open_in_terminal_during_panel_stream_preserves_process_and_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            fake = root / "slow-omp"
            write_slow_omp(fake)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "OMP_BIN": str(fake),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
                "AGENTIK_TERMINAL": "fake-term",
            }
            completed: list[dict] = []
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("new", *new_args(project, "omp", "openai/gpt-test"))
                self.assertTrue(selected["ok"])
                completed.append(chat_bridge.dispatch("send", "hello".encode().hex()))
                time.sleep(0.6)
                with mock.patch.object(chat_bridge.subprocess, "Popen") as terminal_popen:
                    opened = chat_bridge.dispatch("open")
                self.assertFalse(opened["ok"])
                self.assertIn("panel coding session is running", opened["error"])
                terminal_popen.assert_not_called()
                self.assertTrue(chat_bridge.dispatch("status")["busy"],
                                "terminal rejection does not signal or replace the running process")
                time.sleep(0.6)
                streamed = chat_bridge.dispatch("status")
                self.assertIn("Hello", [message["text"] for message in streamed["messages"]],
                              "the panel retains streaming assistant text after rejected terminal launch")
                final = wait_for_idle()
                self.assertTrue(completed[0]["ok"])
                self.assertFalse(final["busy"])
                self.assertEqual(feed_texts(final), ["hello", "Hello"])

    def test_cancel_terminates_live_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            fake = root / "slow-omp"
            write_slow_omp(fake)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(root / "sessions"),
                "OMP_BIN": str(fake),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment):
                chat_bridge.dispatch("new", *new_args(project, "omp", "openai/gpt-test"))
                started = chat_bridge.dispatch("send", "hello".encode().hex())
                self.assertTrue(started["busy"])
                time.sleep(0.2)
                cancelled = chat_bridge.dispatch("cancel")
                self.assertTrue(cancelled["ok"])
                self.assertFalse(cancelled["busy"])
                self.assertEqual(cancelled["run"]["state"], "cancelled")
                self.assertFalse(chat_bridge.dispatch("status")["busy"])

    def test_builtin_harness_capabilities_are_explicit(self) -> None:
        omp = chat_bridge.omp_catalog("missing-omp")
        hermes = chat_bridge.hermes_catalog("missing-hermes")
        self.assertTrue(omp["capabilities"]["fork"])
        self.assertFalse(hermes["capabilities"]["fork"])
        self.assertTrue(omp["capabilities"]["stream"])
    def test_status_reports_live_stream_and_blocks_concurrent_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            project = root / "project"
            project.mkdir()
            fake = root / "slow-omp"
            write_slow_omp(fake)
            environment = {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(sessions),
                "OMP_BIN": str(fake),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }
            with mock.patch.dict(os.environ, environment):
                selected = chat_bridge.dispatch("new", *new_args(project, "omp", "openai/gpt-test"))
                self.assertTrue(selected["ok"])
                started = chat_bridge.dispatch("send", "hello".encode().hex())
                self.assertTrue(started["busy"])
                time.sleep(0.6)
                status = chat_bridge.dispatch("status")
                self.assertTrue(status["ok"])
                self.assertTrue(status["busy"])
                self.assertEqual(len(status["messages"]), 2,
                                 "status exposes the partial transcript while the harness runs")
                time.sleep(0.6)
                status = chat_bridge.dispatch("status")
                self.assertTrue(status["busy"])
                texts = [message["text"] for message in status["messages"]]
                self.assertIn("Hello", texts, "status text grows before completion")
                blocked = chat_bridge.dispatch("send", "again".encode().hex())
                self.assertFalse(blocked["ok"])
                self.assertEqual(blocked["error"], "a coding session is already running")
                idle = wait_for_idle()
                self.assertFalse(idle["busy"], "status turns idle once the stream finishes")
                self.assertEqual(
                    feed_texts(idle),
                    ["hello", "Hello"],
                    "terminal status returns semantic events rather than a rebuilt transcript",
                )

    def test_load_reports_live_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            state = chat_bridge.empty_state()
            state["selection"] = {"kind": "new", "harness": "omp", "cwd": "/work",
                                  "model": "m", "messages": []}
            state["stream"] = {
                "run_id": "live-run",
                "state": "running",
                "busy": True,
                "started": time.time(),
                "updated": time.time(),
                "pid": os.getpid(),
                "process_group": os.getpgrp(),
                "process_start_time": chat_bridge.process_start_time(os.getpid()),
                "sequence": 0,
                "events": [],
                "messages": [{"role": "assistant", "text": "growing"}],
            }
            chat_bridge.write_state(state_dir / "state.json", state)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(state_dir),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("load")
        self.assertTrue(result["ok"])
        self.assertTrue(result["busy"])
        self.assertEqual([message["text"] for message in result["messages"]], ["growing"])

    def test_stale_stream_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            state = chat_bridge.empty_state()
            state["stream"] = {"busy": True, "started": time.time() - 200,
                               "messages": [{"role": "assistant", "text": "ghost"}]}
            chat_bridge.write_state(state_dir / "state.json", state)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(state_dir),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("status")
        self.assertTrue(result["ok"])
        self.assertFalse(result["busy"], "a stream left by a killed bridge is not busy")
        self.assertEqual(result["messages"], [])

    def test_run_ids_are_unique_and_stale_writer_cannot_replace_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            selection = {"kind": "new", "harness": "omp", "cwd": "/work", "messages": []}
            stale_state = chat_bridge.empty_state()
            stale_stream = chat_bridge.begin_stream(stale_state, selection, "first")
            current_state = chat_bridge.empty_state()
            current_stream = chat_bridge.begin_stream(current_state, selection, "second")
            self.assertNotEqual(stale_stream["run_id"], current_stream["run_id"])
            chat_bridge.write_state(state_path, current_state)
            self.assertFalse(chat_bridge.persist_stream(state_path, stale_state, stale_stream))
            persisted = chat_bridge.read_state(state_path)["stream"]
            self.assertEqual(persisted["run_id"], current_stream["run_id"])
            self.assertEqual(persisted["messages"][-1]["text"], "second")

    def test_long_running_stream_is_not_recovered_by_elapsed_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            state = chat_bridge.empty_state()
            state["stream"] = {
                "run_id": "long-run",
                "state": "running",
                "busy": True,
                "started": time.time() - 600,
                "updated": time.time() - 300,
                "pid": os.getpid(),
                "process_group": os.getpgrp(),
                "process_start_time": chat_bridge.process_start_time(os.getpid()),
                "sequence": 0,
                "events": [],
                "messages": [],
            }
            chat_bridge.write_state(state_dir / "state.json", state)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(state_dir),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("status")
            self.assertTrue(result["busy"])
            self.assertEqual(result["run"]["run_id"], "long-run")

    def test_dead_worker_is_recovered_as_orphaned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            state = chat_bridge.empty_state()
            state["stream"] = {
                "run_id": "dead-run",
                "state": "running",
                "busy": True,
                "started": time.time() - 10,
                "updated": time.time() - 10,
                "pid": 999_999_999,
                "process_group": 999_999_999,
                "process_start_time": "1",
                "sequence": 0,
                "events": [],
                "messages": [],
            }
            chat_bridge.write_state(state_dir / "state.json", state)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(state_dir),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("status")
            self.assertFalse(result["busy"])
            self.assertEqual(result["run"]["state"], "orphaned")
            self.assertIn("before reporting", result["run"]["error"])

    def test_state_storage_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "agentik/chat/state.json"
            chat_bridge.write_state(state_path, chat_bridge.empty_state())
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state_path.parent.stat().st_mode & 0o777, 0o700)

    def test_select_rejects_path_outside_sessions_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.jsonl"
            write_session(outside, "outside", "/work/outside", exited=True)
            with mock.patch.dict(os.environ, {
                "AGENTIK_STATE_DIR": str(root / "state"),
                "AGENTIK_SESSIONS_DIR": str(root / "sessions"),
                "AGENTIK_CATALOG_JSON": TEST_CATALOG,
            }):
                result = chat_bridge.dispatch("select", str(outside).encode().hex())
            self.assertFalse(result["ok"])
            self.assertIn("outside", result["error"])


if __name__ == "__main__":
    unittest.main()
