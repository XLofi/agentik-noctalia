#!/usr/bin/env python3
"""Luau script harness for Agentik (I1).

Runs each plugin Luau script through the standalone `luau` CLI with stubbed
noctalia/ui/barWidget/desktopWidget/panel globals, then asserts script
behavior (rendering, notification aggregation, i18n resolution). Catches the
syntax/runtime-error class of bugs that `noctalia plugins lint` cannot see.

Requires the `luau` binary (luau-lang/luau release) on PATH or in $LUAU.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every config key the scripts read, with the manifest default, so stubbed
# getConfig never returns nil for a declared setting.
DEFAULTS = {
    "show_task": "true",
    "show_attention": "true",
    "display_label": '"project"',
    "sort_mode": '"duration"',
    "filter_attention": "false",
    "excluded_projects": '""',
    "show_count": "true",
    "show_intent": "true",
    "notify_attention": "false",
    "notification_cooldown_seconds": "300",
    "notification_privacy": "false",
    "chat_enabled": "true",
    "reduce_motion": "false",
    "high_contrast": "false",
}

STUBS = """\
-- Agentik Luau test harness: stubbed runtime globals.
local T = {
    config = {},
    state = {},
    watch = {},
    notifies = {},
    trees = {},
    tooltips = {},
    runAsyncCalls = {},
    runAsyncTimeouts = {},
    pendingAsyncCallbacks = {},
    flags = {},
    files = { @@FILES@@ },
    settingsOpened = 0,
    panelRenderCount = 0,
    updateIntervalMs = nil,
}
T.translations = {
@@TRANSLATIONS@@
}
for k, v in pairs({ @@DEFAULTS@@ }) do
    T.config[k] = v
end

noctalia = {
    state = {
        get = function(k) return T.state[k] end,
        set = function(k, v) T.state[k] = v end,
        watch = function(k, cb) T.watch[k] = cb end,
    },
    getConfig = function(k)
        local v = T.config[k]
        if v == nil then
            error("test: getConfig('" .. k .. "') called without a stub value")
        end
        return v
    end,
    nowMs = function() return T.nowMs or 0 end,
    tr = function(key, subst)
        local tmpl = T.translations[key]
        if tmpl == nil then error("test: missing translation key '" .. key .. "'") end
        if subst then
            for k, v in pairs(subst) do
                tmpl = string.gsub(tmpl, "{" .. k .. "}", tostring(v))
            end
        end
        return tmpl
    end,
    trp = function(key, count)
        local variant = key .. (count == 1 and ".one" or ".other")
        return noctalia.tr(variant, { count = count })
    end,
    setUpdateInterval = function(ms) T.updateIntervalMs = ms end,
    pluginDir = function() return "/plugin" end,
    fileExists = function(path) return T.files[tostring(path)] == true end,
    notify = function(title, body)
        T.notifies[#T.notifies + 1] = { title = tostring(title), body = tostring(body) }
    end,
    runAsync = function(cmd, cb, timeoutMs)
        T.runAsyncCalls[#T.runAsyncCalls + 1] = tostring(cmd)
        T.runAsyncTimeouts[#T.runAsyncTimeouts + 1] = timeoutMs
        if cb and T.deferAsync then
            T.pendingAsyncCallbacks[#T.pendingAsyncCallbacks + 1] = cb
        elseif cb then
            cb(T.runAsyncResult or { stdout = "{}" })
        end
    end,
    json = { decode = function() return T.jsonValue or {} end },
    togglePanel = function() end,
    openSettings = function() T.settingsOpened = T.settingsOpened + 1 end,
}

local function node(kind, props, children)
    return { kind = kind, props = props, children = children }
end
ui = {
    row = function(props, children) return node("row", props, children) end,
    column = function(props, children) return node("column", props, children) end,
    ["label"] = function(props) return node("label", props) end,
    image = function(props) return node("image", props) end,
    scroll = function(props, children) return node("scroll", props, children) end,
    glyph = function(props) return node("glyph", props) end,
    button = function(props) return node("button", props) end,
    input = function(props) return node("input", props) end,
    select = function(props) return node("select", props) end,
}
barWidget = {
    setTooltip = function(text) T.tooltips.widget = tostring(text) end,
    isVertical = function() return T.vertical == true end,
    render = function(tree) T.trees.widget = tree end,
}
desktopWidget = {
    render = function(tree) T.trees.desktop = tree end,
    setWantsSecondTicks = function() end,
    setNeedsFrameTick = function(enabled) T.flags.desktopNeedsFrameTick = enabled end,
}
panel = {
    render = function(tree)
        T.panelRenderCount = T.panelRenderCount + 1
        T.trees.panel = tree
    end,
    close = function() T.flags.panelClosed = true end,
    setNeedsFrameTick = function(enabled) T.flags.panelNeedsFrameTick = enabled end,
    setWantsSecondTicks = function() end,
}

local function collect_label_texts(node, out)
    if node == nil then return out end
    if node.kind == "label" then out[#out + 1] = tostring(node.props.text) end
    for _, child in ipairs(node.children or {}) do
        collect_label_texts(child, out)
    end
    return out
end
T.labelTexts = function(tree)
    local out = {}
    collect_label_texts(tree, out)
    return out
end

local function collect_image_paths(node, out)
    if node == nil then return out end
    if node.kind == "image" then out[#out + 1] = tostring(node.props.path) end
    for _, child in ipairs(node.children or {}) do
        collect_image_paths(child, out)
    end
    return out
end
T.imagePaths = function(tree)
    return collect_image_paths(tree, {})
end

local function collect_buttons(node, text, out)
    if node == nil then return out end
    if node.kind == "button" and node.props.text == text then
        out[#out + 1] = node
    end
    for _, child in ipairs(node.children or {}) do
        collect_buttons(child, text, out)
    end
    return out
end
T.buttonsWithText = function(tree, text)
    return collect_buttons(tree, text, {})
end

local function collect_labels_with_text(node, text, out)
    if node == nil then return out end
    if node.kind == "label" and node.props.text == text then out[#out + 1] = node end
    for _, child in ipairs(node.children or {}) do
        collect_labels_with_text(child, text, out)
    end
    return out
end
T.labelsWithText = function(tree, text)
    return collect_labels_with_text(tree, text, {})
end

local function collect_nodes_of_kind(node, kind, out)
    if node == nil then return out end
    if node.kind == kind then out[#out + 1] = node end
    for _, child in ipairs(node.children or {}) do
        collect_nodes_of_kind(child, kind, out)
    end
    return out
end
T.nodesOfKind = function(tree, kind)
    return collect_nodes_of_kind(tree, kind, {})
end

local function assert_equals(actual, expected, message)
    if actual ~= expected then
        error(("assert failed: %s (expected %s, got %s)"):format(
            message, tostring(expected), tostring(actual)))
    end
end
local function assert_true(value, message)
    if not value then error("assert failed: " .. message) end
end
"""


def flatten_translations(value: object, prefix: str = "") -> dict[str, str]:
    if isinstance(value, str):
        return {prefix: value}
    if not isinstance(value, dict):
        raise ValueError(f"invalid translation value at {prefix or '<root>'}")
    flattened: dict[str, str] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        flattened.update(flatten_translations(child, path))
    return flattened


def translations_literal(path: Path) -> str:
    data = flatten_translations(json.loads(path.read_text(encoding="utf-8")))
    return "\n".join(
        f'    ["{key}"] = {json.dumps(data[key], ensure_ascii=False)},'
        for key in sorted(data)
    )


# (name, script, test body). Each case runs in its own luau process.
CASES: list[tuple[str, str, str]] = [
    (
        "widget-load",
        "widget.luau",
        """
assert_true(T.trees.widget ~= nil, "widget renders at load")
assert_equals(#T.notifies, 0, "no toast on load")
""",
    ),
    (
        "widget-agentik-60",
        "widget.luau",
        """
T.state.sessions = { active = 1, sessions = {
    { id = "a", project = "proj-a", attention = "active", state = "working" },
} }
T.nowMs = 750
T.watch.sessions(T.state.sessions)
local paths = table.concat(T.imagePaths(T.trees.widget), "|")
assert_true(paths:find("/orbs-agentik-60/working-20-45.svg", 1, true) ~= nil,
    "local Agentik pack selects its 60 FPS frame and asset directory")
""",
    ),
    (
        "widget-single-blocked",
        "widget.luau",
        """
T.config.notify_attention = true
local active = { active = 1, sessions = { { id = "a", project = "proj-a", task = "task a", attention = "active", state = "working" } } }
local blocked = { active = 1, sessions = { { id = "a", project = "proj-a", task = "task a", attention = "blocked", state = "working" } } }
T.state.sessions = active
T.watch.sessions(active)
T.state.sessions = blocked
T.watch.sessions(blocked)
assert_equals(#T.notifies, 1, "one toast for one transition")
assert_equals(T.notifies[1].title, "Agentik: blocked", "single-blocked title")
assert_equals(T.notifies[1].body, "proj-a: task a", "single-blocked body")
""",
    ),
    (
        "widget-aggregated",
        "widget.luau",
        """
T.config.notify_attention = true
local active = { active = 2, sessions = {
    { id = "a", project = "proj-a", task = "task a", attention = "active", state = "working" },
    { id = "b", project = "proj-b", task = "task b", attention = "active", state = "working" },
} }
local blocked = { active = 2, sessions = {
    { id = "a", project = "proj-a", task = "task a", attention = "blocked", state = "working" },
    { id = "b", project = "proj-b", task = "task b", attention = "waiting", state = "listening" },
} }
T.state.sessions = active
T.watch.sessions(active)
T.state.sessions = blocked
T.watch.sessions(blocked)
assert_equals(#T.notifies, 1, "one aggregated toast")
assert_equals(T.notifies[1].title, "Agentik: 2 agents need attention", "aggregated title")
assert_equals(T.notifies[1].body, "proj-a: task a, proj-b: task b", "aggregated body")
""",
    ),
    (
        "widget-privacy",
        "widget.luau",
        """
T.config.notify_attention = true
T.config.notification_privacy = true
local active = { active = 2, sessions = {
    { id = "a", project = "proj-a", task = "task a", attention = "active", state = "working" },
    { id = "b", project = "proj-b", task = "task b", attention = "active", state = "working" },
} }
local blocked = { active = 2, sessions = {
    { id = "a", project = "proj-a", task = "task a", attention = "blocked", state = "working" },
    { id = "b", project = "proj-b", task = "task b", attention = "blocked", state = "working" },
} }
T.state.sessions = active
T.watch.sessions(active)
T.state.sessions = blocked
T.watch.sessions(blocked)
assert_equals(#T.notifies, 1, "one toast")
assert_equals(T.notifies[1].title, "Agentik: 2 agents need attention", "privacy title")
assert_equals(T.notifies[1].body, "2 blocked", "privacy body hides names")
""",
    ),
    (
        "widget-tooltip",
        "widget.luau",
        """
T.state.sessions = { active = 0, sessions = {} }
T.watch.sessions(T.state.sessions)
assert_equals(T.tooltips.widget, "0 active agents", "plural tooltip")
""",
    ),
    (
        "widget-mixed-states",
        "widget.luau",
        """
T.state.sessions = { active = 3, sessions = {
    { id = "a", attention = "active", state = "working" },
    { id = "b", attention = "active", state = "searching" },
    { id = "c", attention = "active", state = "working" },
} }
T.nowMs = 0
T.watch.sessions(T.state.sessions)
local initial = T.labelTexts(T.trees.widget)
assert_equals(#initial, 2, "only the count and one state label render")
assert_equals(initial[1], "1", "first active agent uses ordinal one")
assert_equals(initial[2], "Working", "first state renders")
T.nowMs = 2125
update()
assert_equals(T.trees.widget.children[3].props.opacity, 0.5, "outgoing state fades")
T.nowMs = 2250
update()
local switched = T.labelTexts(T.trees.widget)
assert_equals(#switched, 2, "only one state label remains during transition")
assert_equals(switched[1], "2", "second active agent uses ordinal two")
assert_equals(switched[2], "Searching", "next state replaces the faded-out state")
assert_equals(T.trees.widget.children[3].props.opacity, 0, "next state starts transparent")
T.nowMs = 2375
update()
assert_equals(T.trees.widget.children[3].props.opacity, 0.5, "incoming state fades in")
T.nowMs = 4750
update()
local third = T.labelTexts(T.trees.widget)
assert_equals(third[1], "3", "third active agent retains its distinct ordinal")
assert_equals(third[2], "Working", "agents with the same state still rotate separately")
""",
    ),
    (
        "widget-agent-stops",
        "widget.luau",
        """
local pair = { active = 2, sessions = {
    { id = "a", attention = "active", state = "working" },
    { id = "b", attention = "active", state = "searching" },
} }
T.nowMs = 2250
T.state.sessions = pair
T.watch.sessions(pair)
local before_stop = T.labelTexts(T.trees.widget)
assert_equals(before_stop[1], "2", "second agent is displayed before stop")
assert_equals(before_stop[2], "Searching", "second state is displayed before stop")
local remaining = { active = 1, sessions = {
    { id = "a", attention = "active", state = "working" },
} }
T.state.sessions = remaining
T.watch.sessions(remaining)
local after_stop = T.labelTexts(T.trees.widget)
assert_equals(after_stop[1], "1", "remaining agent is renumbered immediately")
assert_equals(after_stop[2], "Working", "remaining agent state replaces stopped agent")
assert_equals(T.trees.widget.children[3].props.opacity, 1, "remaining agent is fully visible")
T.nowMs = 10000
update()
local stable = T.labelTexts(T.trees.widget)
assert_equals(stable[1], "1", "one remaining agent never cycles away")
assert_equals(stable[2], "Working", "one remaining state stays stable")
""",
    ),
    (
        "widget-quiet",
        "widget.luau",
        """
local quiet = { active = 0, sessions = {
    { id = "q", attention = "active", state = "working", quiet = true, idle = 31 },
} }
T.state.sessions = quiet
T.watch.sessions(quiet)
local texts = T.labelTexts(T.trees.widget)
assert_equals(#texts, 2, "quiet session renders a distinct idle hint")
assert_equals(texts[1], "0", "quiet session is excluded from active count")
assert_equals(texts[2], "idle 31s", "quiet session reports its idle duration")
assert_true(T.trees.widget.children[1].props.path:find("/working-20-0.svg", 1, true) ~= nil,
    "quiet session starts on its current animation frame")
assert_equals(T.updateIntervalMs, 16, "quiet session remains animated")
T.nowMs = 750
update()
assert_true(T.trees.widget.children[1].props.path:find("/working-20-22.svg", 1, true) ~= nil,
    "quiet session orb advances")
quiet.sessions[1].idle = 3661
T.watch.sessions(quiet)
texts = T.labelTexts(T.trees.widget)
assert_equals(texts[2], "idle 1h 1m", "idle duration promotes minutes into hours")
""",
    ),
    (
        "widget-attention-progress",
        "widget.luau",
        """
T.nowMs = 0
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "blocked", state = "working", todo_completed = 3, todo_total = 7, todo_active = true },
} }
T.watch.sessions(T.state.sessions)
assert_true(T.trees.widget.children[1].props.path:find("/working-blocked-20-0.svg", 1, true) ~= nil,
    "blocked agent uses the urgency-ring orb")
assert_true(T.trees.widget.children[4].props.path:find("/progress-transition-90.svg", 1, true) ~= nil,
    "progress ring starts at its determinate step")
assert_equals(T.trees.widget.children[4].props.width, 20, "progress ring matches the orb size")
assert_equals(T.trees.widget.children[4].props.opacity, 0, "progress ring fades in when spawned")
assert_equals(T.tooltips.widget, "1 active agent · 3 of 7 tasks complete", "progress tooltip")
T.nowMs = 100
update()
assert_true(T.trees.widget.children[4].props.opacity > 0 and T.trees.widget.children[4].props.opacity < 1,
    "progress ring fades in over time")
T.nowMs = 500
update()
assert_true(T.trees.widget.children[1].props.path:find("/working-blocked-20-15.svg", 1, true) ~= nil,
    "urgency ring animates with the state orb")
T.nowMs = 500
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "blocked", state = "working", todo_completed = 4, todo_total = 7, todo_active = true },
} }
T.watch.sessions(T.state.sessions)
assert_true(T.trees.widget.children[4].props.path:find("/progress-transition-90.svg", 1, true) ~= nil,
    "progress transition starts from the previous step")
T.nowMs = 650
update()
assert_true(T.trees.widget.children[4].props.path:find("/progress-transition-120.svg", 1, true) ~= nil,
    "progress transitions through intermediate frames")
T.nowMs = 1000
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "blocked", state = "working", todo_completed = 7, todo_total = 7, todo_active = false },
} }
T.watch.sessions(T.state.sessions)
T.nowMs = 1100
update()
assert_true(T.trees.widget.children[4].props.opacity > 0 and T.trees.widget.children[4].props.opacity < 1,
    "completed progress ring fades out")
T.nowMs = 1200
update()
assert_equals(#T.imagePaths(T.trees.widget), 1, "completed progress ring disappears after fading out")
""",
    ),
    (
        "widget-choice-prompt",
        "widget.luau",
        """
T.nowMs = 0
T.state.sessions = { active = 2, sessions = {
    { id = "ordinary", attention = "active", state = "working" },
    { id = "choice", attention = "waiting", state = "listening", propositions = {
        { value = "1", label = "Continue" },
        { value = "2", label = "Stop" },
    } },
} }
T.watch.sessions(T.state.sessions)
local texts = T.labelTexts(T.trees.widget)
assert_equals(texts[1], "2", "choice session keeps its original ordinal")
assert_equals(texts[2], "Awaiting input", "choice session takes bar priority")
assert_equals(texts[3], "Choice needed", "choice prompt is visible in the bar")
assert_true(T.trees.widget.children[1].props.path:find("/listening-waiting-20-0.svg", 1, true) ~= nil,
    "choice prompt retains the waiting urgency ring")
assert_equals(T.tooltips.widget, "2 active agents · Choice needed", "choice prompt is in tooltip")
assert_equals(#T.runAsyncCalls, 0, "bar prompt does not copy or inject a response")
""",
    ),
    (
        "widget-no-active-todo-progress",
        "widget.luau",
        """
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "active", state = "working", todo_completed = 7, todo_total = 7, todo_active = false },
} }
T.watch.sessions(T.state.sessions)
assert_equals(#T.imagePaths(T.trees.widget), 1, "completed todo does not retain a progress ring")
assert_equals(T.tooltips.widget, "1 active agent", "completed todo does not retain progress text")
""",
    ),
    (
        "widget-vertical-compact",
        "widget.luau",
        """
T.vertical = true
T.nowMs = 0
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "waiting", state = "working", todo_completed = 4, todo_total = 8, todo_active = true },
} }
T.watch.sessions(T.state.sessions)
assert_equals(T.trees.widget.kind, "column", "vertical bar uses compact column layout")
assert_equals(#T.labelTexts(T.trees.widget), 0, "compact layout hides ordinal and state text")
assert_equals(#T.trees.widget.children, 2, "compact layout retains orb and progress")
assert_true(T.trees.widget.children[2].props.path:find("/progress-transition-120.svg", 1, true) ~= nil,
    "compact layout retains progress ring")
""",
    ),
    (
        "widget-done",
        "widget.luau",
        """
T.nowMs = 500
T.state.sessions = { active = 0, sessions = {
    { id = "d", attention = "active", state = "done", exited = 300 },
} }
T.watch.sessions(T.state.sessions)
assert_equals(T.trees.widget.children[1].kind, "image", "done session replaces the sparkles glyph")
assert_true(T.trees.widget.children[1].props.path:find("/done-20-15.svg", 1, true) ~= nil,
    "done session uses the animated completion orb")
assert_equals(T.labelTexts(T.trees.widget)[1], "0", "done session remains outside the active count")
assert_equals(T.updateIntervalMs, 16, "done orb animates at frame cadence")
T.nowMs = 750
update()
assert_true(T.trees.widget.children[1].props.path:find("/done-20-22.svg", 1, true) ~= nil,
    "done orb advances")
""",
    ),
    (
        "widget-reduced-motion",
        "widget.luau",
        """
T.config.reduce_motion = true
T.nowMs = 0
T.state.sessions = { active = 1, sessions = {
    { id = "a", attention = "active", state = "working" },
} }
T.watch.sessions(T.state.sessions)
assert_true(T.trees.widget.children[1].props.path:find("/working-20-0.svg", 1, true) ~= nil,
    "reduced motion starts at the static orb frame")
assert_equals(T.updateIntervalMs, 1000, "reduced motion disables frame-rate updates")
T.nowMs = 750
update()
assert_true(T.trees.widget.children[1].props.path:find("/working-20-0.svg", 1, true) ~= nil,
    "reduced motion keeps the static orb frame")
""",
    ),
    (
        "panel-load-empty",
        "panel.luau",
        """
onOpen()
assert_true(T.trees.panel ~= nil, "panel renders on open")
local texts = T.labelTexts(T.trees.panel)
local found = false
for _, t in ipairs(texts) do if t == "No active agents" then found = true end end
assert_true(found, "empty state label shown")
""",
    ),
    (
        "panel-rows",
        "panel.luau",
        """
T.state.sessions = { active = 2, sessions = {
    { id = "a", project = "proj-a", task = "task a", attention = "blocked", state = "working", duration = 60, idle = 5, started_at = 1, last_activity_at = 56 },
    { id = "b", project = "proj-b", task = "task b", attention = "active", state = "composing", duration = 30, idle = 5 },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local texts = T.labelTexts(T.trees.panel)
local joined = table.concat(texts, "|")
assert_true(joined:find("proj-a", 1, true) ~= nil and joined:find("proj-b", 1, true) ~= nil, "both projects listed")
assert_true(joined:find("Blocked") ~= nil and joined:find("Running") ~= nil, "lifecycle labels translated")
assert_true(joined:find("task a") ~= nil, "task shown")
assert_true(joined:find("started 1m ago · last activity 5s ago", 1, true) ~= nil, "timeline shown")
local styled_rows = 0
local blocked_tint = false
for _, row in ipairs(T.nodesOfKind(T.trees.panel, "row")) do
    if row.props.radius == 10 and row.props.paddingH == 8 then
        styled_rows = styled_rows + 1
        if row.props.fill == "error/0.10" then blocked_tint = true end
    end
end
assert_equals(styled_rows, 2, "session rows use the polished card treatment")
assert_true(blocked_tint, "blocked session uses an attention tint")
local header = T.trees.panel.children[1]
assert_equals(header.props.fill, "surface_variant/0.30", "header uses a compact surface")
assert_equals(header.props.radius, 12, "header has a compact rounded treatment")
""",
    ),
    (
        "panel-session-chat",
        "panel.luau",
        """
T.state.sessions = { active = 1, sessions = {
    { id = "session-1", project = "project", cwd = "/work/project", attention = "active", state = "working" },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local chat_buttons = {}
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then table.insert(chat_buttons, button) end
    assert_true(button.props.glyph ~= "copy", "session rows no longer copy ids")
end
assert_equals(#chat_buttons, 2, "header and session row expose chat actions")
T.jsonValue = { ok = true, selected = true, title = "Project session", cwd = "/work/project",
    harness = "omp", model = "openai/gpt-test", targets = {}, messages = {} }
chat_buttons[2].props.onClick()
assert_equals(T.flags.panelNeedsFrameTick, false,
    "idle terminal chat avoids continuous full-panel renders")
local renders_before_frame = T.panelRenderCount

local sessions_button = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.key == "panel-tab-sessions" then sessions_button = button end
end
assert_true(sessions_button ~= nil, "panel retains the session tab after chat opens")
sessions_button.props.onClick()
T.nowMs = 750
onFrameTick(50)
local paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/working-64-22.svg", 1, true) ~= nil,
    "session panel orb remains smooth at its capped redraw cadence")
""",
    ),
    (
        "panel-quiet",
        "panel.luau",
        """
T.state.sessions = { active = 0, sessions = {
    { id = "q", project = "proj-q", attention = "active", state = "working", quiet = true, idle = 31 },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("proj-q", 1, true) ~= nil, "quiet session remains visible")
assert_true(joined:find("idle 31s", 1, true) ~= nil, "quiet session shows idle grace")
local paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/working-20-0.svg", 1, true) ~= nil, "quiet panel row starts animated")
T.nowMs = 750
onFrameTick(100)
paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/working-20-22.svg", 1, true) ~= nil, "quiet panel row advances")
T.state.sessions.sessions[1].idle = 3661
T.watch.sessions(T.state.sessions)
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("idle 1h 1m", 1, true) ~= nil, "panel promotes idle minutes into hours")
""",
    ),
    (
        "panel-done",
        "panel.luau",
        """
T.nowMs = 500
T.state.sessions = { active = 0, sessions = {
    { id = "d", project = "completed", attention = "active", state = "done", exited = 300 },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Completed", 1, true) ~= nil and joined:find("exited 5m ago", 1, true) ~= nil,
    "completed status and exit age shown")
local paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/done-20-15.svg", 1, true) ~= nil, "done row orb animates")
assert_true(paths:find("/done-64-15.svg", 1, true) ~= nil,
    "done header uses the matching animated 64px orb")
T.nowMs = 750
onFrameTick(100)
paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/done-20-22.svg", 1, true) ~= nil
    and paths:find("/done-64-22.svg", 1, true) ~= nil,
    "finished panel orbs advance together")
""",
    ),
    (
        "panel-close",
        "panel.luau",
        """
onOpen()
onClose()
assert_true(T.flags.panelClosed == nil, "onClose does not close")
onCloseClicked()
assert_true(T.flags.panelClosed == true, "close button closes")
""",
    ),
    (
        "panel-chat",
        "panel.luau",
        """
onOpen()
local header_buttons = {}
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if type(button.props.key) == "string" then header_buttons[button.props.key] = button end
end
assert_true(header_buttons["panel-tab-sessions"] ~= nil
    and header_buttons["panel-tab-chat"] ~= nil
    and header_buttons["panel-attention-inbox"] ~= nil
    and header_buttons["panel-settings"] ~= nil,
    "panel header controls retain stable identities during animation")
onSettingsClicked()
assert_equals(T.settingsOpened, 1, "panel settings control opens Noctalia settings")
local chat = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then chat = button end
end
assert_true(chat ~= nil, "panel header exposes OMP sessions")
T.jsonValue = { ok = true, selected = false, messages = {}, harnesses = {
    { id = "omp", name = "Oh My Pi", default_model = "openai/gpt-test",
      models = { "openai/gpt-test", "openai/gpt-other" } },
    { id = "hermes", name = "Hermes Agent", default_model = "ollama/test",
      models = { "ollama/test", "ollama/other" } },
}, targets = {
    { id = "ended", title = "Fix project", path = "/sessions/ended.jsonl",
      cwd = "/work/project", project = "project", model = "openai/gpt-test", resumable = true },
    { id = "active", title = "Active terminal", path = "/sessions/active.jsonl",
      cwd = "/work/live", project = "live", active = true, resumable = false, forkable = true },
    { id = "interrupted", title = "Interrupted work", path = "/sessions/interrupted.jsonl",
      cwd = "/work/interrupted", project = "interrupted", resumable = false, forkable = true },
} }
chat.props.onClick()
assert_equals(T.flags.panelNeedsFrameTick, false,
    "chat mode disables continuous frame renders")
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "panel load outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find("chat_bridge.py", 1, true) ~= nil
    and T.runAsyncCalls[#T.runAsyncCalls]:find(" load", 1, true) ~= nil,
    "panel loads real OMP session targets")
local selectors = T.nodesOfKind(T.trees.panel, "select")
assert_equals(#selectors, 1, "panel keeps the model picker as one combined control")
assert_equals(selectors[1].props.options[1], "Oh My Pi", "panel harness options are populated")
selectors[1].props.onChange(1, "Hermes Agent")
local model_dropdown = T.buttonsWithText(T.trees.panel, "⌄")[1]
assert_true(model_dropdown ~= nil, "model picker exposes one dropdown trigger")
model_dropdown.props.onClick()
local suggested = T.buttonsWithText(T.trees.panel, "ollama/test")[1]
assert_true(suggested ~= nil, "model dropdown exposes harness suggestions")
suggested.props.onClick()
local picker_inputs = T.nodesOfKind(T.trees.panel, "input")
assert_equals(#picker_inputs, 3, "panel exposes model, project, and fuzzy finder inputs")
picker_inputs[1].props.onChange("tes")
assert_true(T.buttonsWithText(T.trees.panel, "ollama/test")[1] ~= nil,
    "model finder matches non-contiguous catalog characters")
assert_true(T.buttonsWithText(T.trees.panel, "ollama/other")[1] == nil,
    "model finder hides nonmatching catalog entries")
picker_inputs = T.nodesOfKind(T.trees.panel, "input")
picker_inputs[1].props.onChange("openai/custom-model")
picker_inputs = T.nodesOfKind(T.trees.panel, "input")
assert_equals(picker_inputs[1].props.value, "openai/custom-model", "typed model name is retained")
picker_inputs[3].props.onChange("irw")
assert_true(T.buttonsWithText(T.trees.panel, "Interrupted work")[1] ~= nil,
    "fuzzy finder matches non-contiguous title characters")
assert_true(T.buttonsWithText(T.trees.panel, "Fix project")[1] == nil,
    "fuzzy finder hides nonmatching sessions")
picker_inputs = T.nodesOfKind(T.trees.panel, "input")
picker_inputs[3].props.onChange("")
local continue_button = T.buttonsWithText(T.trees.panel, "Fix project")[1]
local active_button = T.buttonsWithText(T.trees.panel, "Active terminal")[1]
assert_true(continue_button ~= nil and continue_button.props.enabled == true,
    "finished OMP session can be continued")
assert_true(active_button ~= nil and active_button.props.enabled == true,
    "session active in another client can be selected for a safe fork")
local interrupted_button = T.buttonsWithText(T.trees.panel, "Interrupted work")[1]
assert_true(interrupted_button ~= nil and interrupted_button.props.enabled == true,
    "interrupted recent session can be safely forked")
T.jsonValue = { ok = true, selected = true, title = "Fix project",
    cwd = "/work/project", model = "openai/gpt-test", targets = {}, messages = {
        { role = "user", text = "Existing question" },
        { role = "assistant", text = "Existing answer" },
    } }
continue_button.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "panel select outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" select 2f73657373696f6e732f656e6465642e6a736f6e6c", 1, true) ~= nil,
    "panel selects the real session journal with hex transport")
local inputs = T.nodesOfKind(T.trees.panel, "input")
assert_equals(#inputs, 1, "selected session renders one native message input")
inputs[1].props.onChange("Hello panel")
local send = T.buttonsWithText(T.trees.panel, "Send")[1]
assert_true(send ~= nil and send.props.enabled == true, "typing enables real session send")
T.jsonValue = { ok = true, selected = true, title = "Fix project",
    cwd = "/work/project", model = "openai/gpt-test", targets = {}, messages = {
        { role = "user", text = "Hello panel" },
        { role = "assistant", text = "Hello from OMP" },
    } }
send.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "panel send outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" send 48656c6c6f2070616e656c", 1, true) ~= nil,
    "panel message uses shell-safe hex transport")
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Hello from OMP", 1, true) ~= nil,
    "real OMP response appears inside the panel")
assert_true(T.labelsWithText(T.trees.panel, "Hello panel")[1] ~= nil,
    "panel user message body renders as a feed label")
assert_true(T.labelsWithText(T.trees.panel, "Hello from OMP")[1] ~= nil,
    "panel assistant response body renders as a feed label")
local open_terminal = T.buttonsWithText(T.trees.panel, "Open in terminal")[1]
assert_true(open_terminal ~= nil and open_terminal.props.enabled == true,
    "selected chat exposes an open-in-terminal action")
T.jsonValue = { ok = true, launched = true, terminal = "ghostty" }
open_terminal.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000,
    "terminal launch outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" open", 1, true) ~= nil,
    "open-in-terminal invokes the bridge open command")
local sessions_button = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "list" then sessions_button = button end
end
sessions_button.props.onClick()
assert_equals(#T.nodesOfKind(T.trees.panel, "input"), 0, "sessions mode replaces chat input")
""",
    ),
    (
        "panel-chat-loading",
        "panel.luau",
        """
T.deferAsync = true
onOpen()
local chat = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then chat = button end
end
assert_true(chat ~= nil, "panel header exposes the chat tab")
chat.props.onClick()
assert_true(T.labelsWithText(T.trees.panel, "Loading conversation...")[1] ~= nil,
    "loading chat replaces the panel content with translated loading state")
local paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/working-64-0.svg", 1, true) ~= nil,
    "loading chat renders the working orb")
assert_equals(T.flags.panelNeedsFrameTick, true, "loading chat keeps the orb animated")
T.nowMs = 500
onFrameTick(100)
paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/working-64-15.svg", 1, true) ~= nil,
    "loading orb advances through its animation frames")
T.deferAsync = false
T.jsonValue = { ok = true, selected = false, messages = {}, targets = {} }
T.pendingAsyncCallbacks[1]({ stdout = "{}" })
assert_true(T.labelsWithText(T.trees.panel, "Loading conversation...")[1] == nil,
    "conversation content replaces the loading state after bridge completion")
assert_equals(T.flags.panelNeedsFrameTick, false, "completed load stops the dedicated loading animation")
""",
    ),
    (
        "panel-chat-streaming",
        "panel.luau",
        """
onOpen()
local chat = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then chat = button end
end
assert_true(chat ~= nil, "panel header exposes the chat tab")
T.jsonValue = { ok = true, selected = true, title = "Streaming", cwd = "/work",
    targets = {}, messages = {
        { role = "user", text = "Earlier question" },
        { role = "assistant", text = "Earlier answer" },
    } }
chat.props.onClick()
local transcript_scroller = T.nodesOfKind(T.trees.panel, "scroll")[1]
assert_equals(transcript_scroller.props.stickToBottom, true,
    "chat transcript follows new output while it remains at the bottom")
local opening_scroll_revision = transcript_scroller.props.scrollToBottomRev
assert_true(type(opening_scroll_revision) == "number",
    "opening chat requests the bottom of the complete conversation")
local inputs = T.nodesOfKind(T.trees.panel, "input")
inputs[1].props.onChange("Make a plan")
local send = T.buttonsWithText(T.trees.panel, "Send")[1]
assert_true(send ~= nil and send.props.enabled == true, "typing enables streaming send")
T.jsonValue = { ok = true, selected = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Make a plan" },
    { role = "assistant", text = "Partial" },
} }
send.props.onClick()
transcript_scroller = T.nodesOfKind(T.trees.panel, "scroll")[1]
assert_true(transcript_scroller.props.scrollToBottomRev > opening_scroll_revision,
    "sending jumps the complete conversation to the new user message")
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "streaming send outlives the default async timeout")
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("P", 1, true) ~= nil and joined:find("Partial", 1, true) == nil,
    "streamed assistant text begins with one animated character")
onFrameTick(100)
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Par", 1, true) ~= nil and joined:find("Partial", 1, true) == nil,
    "streamed assistant text advances smoothly without a burst")
onFrameTick(50)
onFrameTick(50)
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Partial", 1, true) ~= nil, "streamed partial text reaches the target over regular frames")
T.nowMs = 1000
T.jsonValue = { ok = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Make a plan" },
    { role = "assistant", text = "Partial growing" },
} }
T.watch.agentik_chat_status({ stdout = "{}" })
assert_true(type(T.watch.agentik_chat_status) == "function",
    "panel consumes the monitor's shared bridge status")
T.jsonValue = { ok = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Make a plan" },
    { role = "assistant", text = "Final answer" },
} }
T.nowMs = 2000
T.watch.agentik_chat_status({ stdout = "{}" })
onFrameTick(1000)
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Final answer", 1, true) == nil,
    "a stalled frame does not dump the pending response")
for _ = 1, 6 do onFrameTick(50) end
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Final answer", 1, true) ~= nil,
    "regular frames finish the latest busy snapshot")
T.jsonValue = { ok = true, busy = false, targets = {}, messages = {
    { role = "user", text = "Make a plan" },
    { role = "assistant", text = "Completed final answer" },
} }
T.nowMs = 3000
T.watch.agentik_chat_status({ stdout = "{}" })
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Completed final answer", 1, true) ~= nil,
    "idle status refreshes the terminal assistant output")
T.jsonValue = { ok = true, busy = false, active = true, mode = "resume", targets = {}, messages = {
    { role = "user", text = "Make a plan" },
    { role = "assistant", text = "Terminal continuation" },
} }
T.watch.agentik_chat_status({ stdout = "{}" })
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Terminal continuation", 1, true) ~= nil,
    "terminal turns refresh in the panel transcript")
assert_true(joined:find("Terminal owns this session", 1, true) ~= nil,
    "panel makes the single-writer terminal handoff explicit")
inputs = T.nodesOfKind(T.trees.panel, "input")
send = T.buttonsWithText(T.trees.panel, "Send")[1]
assert_true(inputs[1].props.enabled == false and send.props.enabled == false,
    "terminal ownership prevents concurrent panel writes")
""",
    ),
    (
        "panel-chat-event-feed",
        "panel.luau",
        """
onOpen()
local chat = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then chat = button end
end
local output_text = table.concat({ "line one", "line two", "line three", "line four", "line five", "line six" }, string.char(10))
T.jsonValue = { ok = true, selected = true, title = "Terminal", cwd = "/work", targets = {},
    messages = {}, feed = { reset = true, revision = "1:5", events = {
        { sequence = 1, kind = "user", text = "Inspect the journal" },
        { sequence = 2, kind = "thinking", text = "Planning the cache" },
        { sequence = 3, kind = "tool_start", tool = "read", text = "Reading journal" },
        { sequence = 4, kind = "tool_output", tool = "read", text = output_text },
        { sequence = 5, kind = "todo_update", text = "Render terminal completion", completed = 1, total = 3 },
        { sequence = 6, kind = "session_exit", text = "normal" },
        { sequence = 7, kind = "choice", text = "Which design?", choices = {
            { value = "a", label = "Compact" }, { value = "Detailed", label = "Detailed" },
        } },
    } } }
chat.props.onClick()
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Inspect the journal", 1, true) ~= nil, "panel renders feed user events")
assert_true(joined:find("Thinking", 1, true) ~= nil and joined:find("Planning the cache", 1, true) ~= nil,
    "panel translates thinking events")
assert_true(joined:find("Tool started · read", 1, true) ~= nil, "panel translates tool lifecycle events")
assert_true(joined:find("line one", 1, true) ~= nil, "panel renders tool output events")
assert_true(joined:find("Todo update", 1, true) ~= nil
    and joined:find("1 of 3 tasks complete", 1, true) ~= nil, "panel renders todo snapshots")
assert_true(joined:find("Done", 1, true) ~= nil and joined:find("Session ended", 1, true) ~= nil,
    "panel renders a terminal completion marker")
assert_true(joined:find("Choice needed", 1, true) ~= nil and joined:find("Which design?", 1, true) ~= nil,
    "panel renders a terminal-owned choice prompt")
local output_copy = nil
local output_toggle = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "copy" then output_copy = button end
    if button.props.glyph == "chevron-down" then output_toggle = button end
end
assert_true(output_copy ~= nil and output_toggle ~= nil, "panel renders output copy and expand controls")
output_copy.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], "wl-copy " .. string.format("%q", output_text),
    "panel copies complete tool output without terminal input")
output_toggle.props.onClick()
local expanded_output = T.labelsWithText(T.trees.panel, output_text)[1]
assert_equals(expanded_output.props.maxLines, 6, "panel expands output without refetching")
local choice = T.buttonsWithText(T.trees.panel, "a")[1]
assert_true(choice ~= nil, "panel renders choice copy controls")
choice.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], 'wl-copy "a"', "panel choice does not submit to the terminal")
T.nowMs = 1000
T.jsonValue = { ok = true, busy = false, feed = { revision = "1:6", events = {
    { sequence = 6, kind = "assistant", text = "Incremental final" },
} } }
T.watch.agentik_chat_status({ stdout = "{}" })
joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("Incremental final", 1, true) ~= nil, "panel appends shared revisioned feed deltas")
""",
    ),
    (
        "panel-chat-formatting",
        "panel.luau",
        """
onOpen()
local chat = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "message-circle" then chat = button end
end
assert_true(chat ~= nil, "panel header exposes the chat tab")
T.jsonValue = { ok = true, selected = true, title = "Formatting", cwd = "/work",
    harness = "omp", model = "m", targets = {}, messages = {
        { role = "assistant", text = "# Plan\\n**bold** text `code` [link](https://x)\\n- bullet one\\n2. second item\\n```\\nline one\\nline two\\n```\\nplain line" },
    } }
chat.props.onClick()
local heading = T.labelsWithText(T.trees.panel, "Plan")[1]
assert_true(heading ~= nil and heading.props.fontWeight == "bold",
    "markdown heading renders as a bold label")
local joined = table.concat(T.labelTexts(T.trees.panel), "|")
assert_true(joined:find("bold text code link", 1, true) ~= nil,
    "inline emphasis, code, and links are cleaned into readable text")
assert_true(T.labelsWithText(T.trees.panel, "• bullet one")[1] ~= nil,
    "bullet items keep their marker")
assert_true(T.labelsWithText(T.trees.panel, "2. second item")[1] ~= nil,
    "ordered items keep their number")
local code = T.labelsWithText(T.trees.panel, "line one")[1]
assert_true(code ~= nil and code.props.color == "on_surface_variant",
    "code fence lines render as code")
assert_true(T.labelsWithText(T.trees.panel, "line two")[1] ~= nil,
    "code fence keeps every line")
assert_true(T.labelsWithText(T.trees.panel, "sh")[1] == nil,
    "fenced code language is not rendered as source")
assert_true(T.labelsWithText(T.trees.panel, "plain line")[1] ~= nil,
    "plain paragraph renders as text")
local message_cards = 0
for _, column in ipairs(T.nodesOfKind(T.trees.panel, "column")) do
    if column.props.radius == 10 and column.props.fill == "surface_variant/0.24" then
        message_cards = message_cards + 1
    end
end
assert_equals(message_cards, 1, "assistant response uses a distinct transcript card")
local context_labels = T.labelsWithText(T.trees.panel, "omp · m")
assert_equals(#context_labels, 1, "only the command bar retains harness context")
local function contains_label(node, text)
    if node.kind == "label" and node.props.text == text then return true end
    for _, child in ipairs(node.children or {}) do
        if contains_label(child, text) then return true end
    end
    return false
end
local transcript_scroller = T.nodesOfKind(T.trees.panel, "scroll")[1]
assert_true(contains_label(transcript_scroller, "line one"),
    "latest assistant message remains in the chronological scrollable conversation")
assert_equals(transcript_scroller.props.stickToBottom, true,
    "complete transcript follows output while the reader remains at its bottom")
local copy_code = nil
for _, button in ipairs(T.nodesOfKind(T.trees.panel, "button")) do
    if button.props.glyph == "copy" then copy_code = button end
end
assert_true(copy_code ~= nil, "code inset exposes a copy action")
copy_code.props.onClick()
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find("wl-copy", 1, true) ~= nil,
    "code copy uses the existing clipboard path")
""",
    ),
    (
        "monitor-load",
        "monitor.luau",
        """
assert_true(#T.runAsyncCalls >= 1, "monitor refreshes at load")
assert_true(T.runAsyncCalls[1]:find("omp_sessions.py") ~= nil, "refresh runs the collector")
local first = #T.runAsyncCalls
update()
assert_true(#T.runAsyncCalls == first + 2, "update() refreshes sessions and shared chat status")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find("chat_bridge.py") ~= nil, "monitor centralizes chat polling")
assert_equals(T.updateIntervalMs, 5000, "idle monitor backs off to a five-second cadence")
""",
    ),
    (
        "desktop-load-empty",
        "desktop_widget.luau",
        """
assert_true(T.trees.desktop ~= nil, "desktop widget renders at load")
update()
local texts = T.labelTexts(T.trees.desktop)
local found = false
for _, t in ipairs(texts) do if t == "No active agents" then found = true end end
assert_true(found, "empty state label shown")
assert_equals(T.updateIntervalMs, 5000, "idle refresh interval")
""",
    ),
    (
        "desktop-rows",
        "desktop_widget.luau",
        """
local sessions = { active = 6, sessions = {} }
for i = 1, 6 do
    sessions.sessions[i] = { id = "s" .. i, project = "proj-" .. i, task = "task " .. i,
        attention = "active", state = "working" }
end
T.state.sessions = sessions
T.watch.sessions(sessions)
local texts = T.labelTexts(T.trees.desktop)
local joined = table.concat(texts, "|")
assert_true(joined:find("6 active agents") ~= nil, "header count (plural)")
assert_true(joined:find("proj-1", 1, true) ~= nil and joined:find("proj-5", 1, true) ~= nil, "first five rows shown")
assert_true(joined:find("proj-6", 1, true) ~= nil, "sixth row shown")
assert_equals(T.updateIntervalMs, 1000, "active refresh interval")
""",
    ),
    (
        "desktop-attention",
        "desktop_widget.luau",
        """
local sessions = { active = 1, sessions = {
    { id = "s1", project = "proj-x", task = "task x", attention = "blocked", state = "working" },
} }
T.state.sessions = sessions
T.watch.sessions(sessions)
local texts = T.labelTexts(T.trees.desktop)
local joined = table.concat(texts, "|")
assert_true(joined:find("Blocked") ~= nil, "attention label translated")
assert_true(joined:find("task x") ~= nil, "task shown")
""",
    ),
    (
        "desktop-quiet",
        "desktop_widget.luau",
        """
T.state.sessions = { active = 0, sessions = {
    { id = "q", project = "proj-q", attention = "active", state = "working", quiet = true, idle = 31 },
} }
T.watch.sessions(T.state.sessions)
local joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("0 active agents", 1, true) ~= nil, "quiet session leaves active count at zero")
assert_true(joined:find("proj-q", 1, true) ~= nil and joined:find("idle 31s", 1, true) ~= nil,
    "desktop retains quiet session with idle status")
assert_true(T.flags.desktopNeedsFrameTick == true, "quiet desktop orb requests frame ticks")
local paths = table.concat(T.imagePaths(T.trees.desktop), "|")
assert_true(paths:find("/working-20-0.svg", 1, true) ~= nil, "quiet desktop orb starts animated")
T.nowMs = 750
onFrameTick(16)
paths = table.concat(T.imagePaths(T.trees.desktop), "|")
assert_true(paths:find("/working-20-22.svg", 1, true) ~= nil, "quiet desktop orb advances")
T.state.sessions.sessions[1].idle = 3661
T.watch.sessions(T.state.sessions)
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("idle 1h 1m", 1, true) ~= nil, "desktop promotes idle minutes into hours")
""",
    ),
    (
        "desktop-done",
        "desktop_widget.luau",
        """
T.nowMs = 500
T.state.sessions = { active = 0, sessions = {
    { id = "d", project = "completed", attention = "active", state = "done", exited = 300 },
} }
T.watch.sessions(T.state.sessions)
local joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Completed", 1, true) ~= nil, "desktop shows completed status")
assert_true(T.flags.desktopNeedsFrameTick == true, "finished orb requests frame ticks")
local paths = table.concat(T.imagePaths(T.trees.desktop), "|")
assert_true(paths:find("/done-20-15.svg", 1, true) ~= nil, "desktop uses the animated done orb")
T.nowMs = 750
onFrameTick(16)
paths = table.concat(T.imagePaths(T.trees.desktop), "|")
assert_true(paths:find("/done-20-22.svg", 1, true) ~= nil, "desktop done orb advances")
""",
    ),
    (
        "desktop-resize",
        "desktop_widget.luau",
        """
local sessions_6 = { active = 6, sessions = { } }
for i = 1, 6 do
    sessions_6.sessions[i] = { id = "s" .. i, project = "proj-" .. i, task = "task " .. i,
        attention = "active", state = "working" }
end
T.state.sessions = sessions_6
T.watch.sessions(sessions_6)
local texts_6 = T.labelTexts(T.trees.desktop)
assert_true(#texts_6 > 10, "many rows shown for 6 agents")

local sessions_1 = { active = 1, sessions = {
    { id = "s1", project = "proj-1", task = "task 1", attention = "active", state = "working" },
} }
T.state.sessions = sessions_1
T.watch.sessions(sessions_1)
local texts_1 = T.labelTexts(T.trees.desktop)
local joined_1 = table.concat(texts_1, "|")
assert_true(#texts_1 < #texts_6, "desktop tree shrinks from 6 agents to 1")
assert_true(joined_1:find("1 active agent") ~= nil, "header updates to one agent")
assert_true(joined_1:find("proj-1", 1, true) ~= nil, "single agent still shown")
assert_true(joined_1:find("proj-2", 1, true) == nil and joined_1:find("proj-6", 1, true) == nil, "removed rows are absent")
""",
    ),
    (
        "desktop-chat",
        "desktop_widget.luau",
        """
local chat = T.buttonsWithText(T.trees.desktop, "Chat")[1]
assert_true(chat ~= nil, "desktop header exposes OMP sessions")
T.jsonValue = { ok = true, selected = false, messages = {}, harnesses = {
    { id = "omp", name = "Oh My Pi", default_model = "openai/gpt-test",
      models = { "openai/gpt-test", "openai/gpt-other" } },
    { id = "hermes", name = "Hermes Agent", default_model = "ollama/test",
      models = { "ollama/test", "ollama/other" } },
}, targets = {
    { id = "old", title = "Recent work", path = "/sessions/old.jsonl",
      cwd = "/work/old", project = "old", resumable = true },
} }
chat.props.onClick()
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find("chat_bridge.py", 1, true) ~= nil
    and T.runAsyncCalls[#T.runAsyncCalls]:find(" load", 1, true) ~= nil,
    "opening chat loads real OMP session targets")
local result_scroller = T.nodesOfKind(T.trees.desktop, "scroll")[1]
assert_equals(result_scroller.props.height, 360, "desktop result panel is extended for recent sessions")
local selectors = T.nodesOfKind(T.trees.desktop, "select")
assert_equals(#selectors, 1, "desktop keeps the model picker as one combined control")
selectors[1].props.onChange("1", "Hermes Agent")
local harness_inputs = T.nodesOfKind(T.trees.desktop, "input")
assert_equals(harness_inputs[1].props.value, "ollama/test",
    "changing harness resets the model query to its default")
local model_dropdown = T.buttonsWithText(T.trees.desktop, "⌄")[1]
assert_true(model_dropdown ~= nil, "desktop model picker exposes one dropdown trigger")
model_dropdown.props.onClick()
local suggested = T.buttonsWithText(T.trees.desktop, "ollama/other")[1]
assert_true(suggested ~= nil, "desktop model dropdown exposes harness suggestions")
suggested.props.onClick()
local inputs = T.nodesOfKind(T.trees.desktop, "input")
assert_equals(#inputs, 3, "session picker renders model, project, and fuzzy finder inputs")
inputs[1].props.onChange("tes")
assert_true(T.buttonsWithText(T.trees.desktop, "ollama/test")[1] ~= nil,
    "desktop model finder matches catalog characters")
assert_true(T.buttonsWithText(T.trees.desktop, "ollama/other")[1] == nil,
    "desktop model finder hides nonmatching catalog entries")
inputs = T.nodesOfKind(T.trees.desktop, "input")
inputs[1].props.onChange("ollama/custom-model")
inputs = T.nodesOfKind(T.trees.desktop, "input")
inputs[2].props.onChange("/work/new")
local start = T.buttonsWithText(T.trees.desktop, "Start")[1]
assert_true(start ~= nil and start.props.enabled == true, "project path enables new session")
T.jsonValue = { ok = true, selected = true, title = "New Hermes Agent session",
    harness = "hermes", model = "ollama/custom-model", cwd = "/work/new", targets = {}, messages = {} }
start.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "desktop start outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(
    " new 2f776f726b2f6e6577 6865726d6573 6f6c6c616d612f637573746f6d2d6d6f64656c", 1, true) ~= nil,
    "desktop starts a typed model name in the selected project")
inputs = T.nodesOfKind(T.trees.desktop, "input")
inputs[1].props.onChange("Hello")
local send = T.buttonsWithText(T.trees.desktop, "Send")[1]
assert_true(send ~= nil and send.props.enabled == true, "typing enables real session send")
T.jsonValue = { ok = true, selected = true, title = "New OMP session",
    cwd = "/work/new", targets = {}, messages = {
        { role = "user", text = "Hello" },
        { role = "assistant", text = "Hello from OMP" },
    } }
send.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "desktop send outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" send 48656c6c6f", 1, true) ~= nil,
    "message is hex encoded before crossing the shell")
local joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Hello from OMP", 1, true) ~= nil,
    "real OMP response appears in the transcript")
assert_true(T.labelsWithText(T.trees.desktop, "Hello")[1] ~= nil,
    "desktop user message body renders as a feed label")
assert_true(T.labelsWithText(T.trees.desktop, "Hello from OMP")[1] ~= nil,
    "desktop assistant response body renders as a feed label")
local open_terminal = T.buttonsWithText(T.trees.desktop, "Open in terminal")[1]
assert_true(open_terminal ~= nil and open_terminal.props.enabled == true,
    "desktop chat exposes an open-in-terminal action")
T.jsonValue = { ok = true, launched = true, terminal = "ghostty" }
open_terminal.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000,
    "desktop terminal launch outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" open", 1, true) ~= nil,
    "desktop open-in-terminal invokes the bridge open command")
T.jsonValue = { ok = true, selected = false, messages = {}, targets = {} }
local switch = T.buttonsWithText(T.trees.desktop, "Switch session")[1]
switch.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], 60000, "desktop reset outlives the default async timeout")
assert_true(T.runAsyncCalls[#T.runAsyncCalls]:find(" reset", 1, true) ~= nil,
    "switch session returns to the picker without deleting journal history")
""",
    ),
    (
        "desktop-chat-streaming",
        "desktop_widget.luau",
        """
local chat = T.buttonsWithText(T.trees.desktop, "Chat")[1]
assert_true(chat ~= nil, "desktop header exposes OMP sessions")
T.jsonValue = { ok = true, selected = true, title = "Streaming", cwd = "/work",
    targets = {}, messages = {
        { role = "user", text = "Earlier question" },
    } }
chat.props.onClick()
local inputs = T.nodesOfKind(T.trees.desktop, "input")
inputs[1].props.onChange("Build it")
local send = T.buttonsWithText(T.trees.desktop, "Send")[1]
assert_true(send ~= nil and send.props.enabled == true, "typing enables desktop streaming send")
T.jsonValue = { ok = true, selected = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Build it" },
    { role = "assistant", text = "Step one" },
} }
send.props.onClick()
assert_equals(T.updateIntervalMs, 1000, "busy widget updates at the fast polling cadence")
local joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("S", 1, true) ~= nil and joined:find("Step one", 1, true) == nil,
    "desktop streamed text begins with one animated character")
onFrameTick(100)
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Ste", 1, true) ~= nil and joined:find("Step one", 1, true) == nil,
    "desktop text advances smoothly without a burst")
onFrameTick(50)
onFrameTick(50)
onFrameTick(50)
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Step one", 1, true) ~= nil, "desktop stream reaches the target over regular frames")
T.nowMs = 1000
T.jsonValue = { ok = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Build it" },
    { role = "assistant", text = "Step one and two" },
} }
T.watch.agentik_chat_status({ stdout = "{}" })
assert_true(type(T.watch.agentik_chat_status) == "function",
    "desktop consumes the monitor's shared bridge status")
onFrameTick(1000)
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Step one and two", 1, true) == nil,
    "a stalled desktop frame does not dump the pending response")
for _ = 1, 5 do onFrameTick(50) end
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Step one and two", 1, true) ~= nil,
    "regular desktop frames finish the latest busy snapshot")
T.jsonValue = { ok = true, busy = true, targets = {}, messages = {
    { role = "user", text = "Build it" },
    { role = "assistant", text = "Done" },
} }
T.nowMs = 2000
T.watch.agentik_chat_status({ stdout = "{}" })
onFrameTick(1000)
for _ = 1, 2 do onFrameTick(50) end
assert_true(T.labelsWithText(T.trees.desktop, "Done")[1] ~= nil,
    "last desktop poll carries the final transcript text")
T.jsonValue = { ok = true, busy = false, targets = {}, messages = {} }
T.nowMs = 3000
T.watch.agentik_chat_status({ stdout = "{}" })
T.jsonValue = { ok = true, busy = false, active = true, mode = "resume", targets = {}, messages = {
    { role = "user", text = "From terminal" },
    { role = "assistant", text = "Terminal reply" },
} }
T.watch.agentik_chat_status({ stdout = "{}" })
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Terminal reply", 1, true) ~= nil,
    "terminal turns refresh in the desktop transcript")
assert_true(joined:find("Terminal owns this session", 1, true) ~= nil,
    "desktop makes the single-writer terminal handoff explicit")
inputs = T.nodesOfKind(T.trees.desktop, "input")
send = T.buttonsWithText(T.trees.desktop, "Send")[1]
assert_true(inputs[1].props.enabled == false and send.props.enabled == false,
    "terminal ownership prevents concurrent desktop writes")
""",
    ),
    (
        "desktop-chat-event-feed",
        "desktop_widget.luau",
        """
local chat = T.buttonsWithText(T.trees.desktop, "Chat")[1]
local output_text = table.concat({ "line one", "line two", "line three", "line four", "line five", "line six" }, string.char(10))
T.jsonValue = { ok = true, selected = true, title = "Terminal", cwd = "/work", targets = {},
    messages = {}, feed = { reset = true, revision = "1:7", events = {
        { sequence = 1, kind = "user", text = "Inspect the journal" },
        { sequence = 2, kind = "tool_start", tool = "read", text = "Reading journal" },
        { sequence = 3, kind = "tool_output", tool = "read", text = output_text },
        { sequence = 4, kind = "todo_update", text = "Render terminal completion", completed = 1, total = 3 },
        { sequence = 5, kind = "session_exit", text = "normal" },
        { sequence = 6, kind = "choice", text = "Which design?", choices = {
            { value = "a", label = "Compact" }, { value = "Detailed", label = "Detailed" },
        } },
    } } }
chat.props.onClick()
local transcript_scroller = T.nodesOfKind(T.trees.desktop, "scroll")[1]
assert_equals(transcript_scroller.props.stickToBottom, true,
    "desktop follows feed output only while the reader remains at bottom")
assert_true(type(transcript_scroller.props.scrollToBottomRev) == "number",
    "opening desktop chat intentionally scrolls its complete transcript to bottom")
local joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Inspect the journal", 1, true) ~= nil, "desktop renders feed user events")
assert_true(joined:find("Tool started · read", 1, true) ~= nil, "desktop translates tool lifecycle events")
assert_true(joined:find("line one", 1, true) ~= nil, "desktop renders tool output events")
assert_true(joined:find("Todo update", 1, true)
    and joined:find("1 of 3 tasks complete", 1, true) ~= nil, "desktop renders todo snapshots")
assert_true(joined:find("Done", 1, true) ~= nil and joined:find("Session ended", 1, true) ~= nil,
    "desktop renders a terminal completion marker")
assert_true(joined:find("Choice needed", 1, true) ~= nil and joined:find("Which design?", 1, true) ~= nil,
    "desktop renders a terminal-owned choice prompt")
local output_copy = nil
local output_toggle = nil
for _, button in ipairs(T.nodesOfKind(T.trees.desktop, "button")) do
    if button.props.glyph == "copy" then output_copy = button end
    if button.props.glyph == "chevron-down" then output_toggle = button end
end
assert_true(output_copy ~= nil and output_toggle ~= nil, "desktop renders output copy and expand controls")
output_copy.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], "wl-copy " .. string.format("%q", output_text),
    "desktop copies complete tool output without terminal input")
output_toggle.props.onClick()
local expanded_output = T.labelsWithText(T.trees.desktop, output_text)[1]
assert_equals(expanded_output.props.maxLines, 6, "desktop expands output without refetching")
local choice = T.buttonsWithText(T.trees.desktop, "a")[1]
assert_true(choice ~= nil, "desktop renders choice copy controls")
choice.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], 'wl-copy "a"', "desktop choice does not submit to the terminal")
T.nowMs = 1000
T.jsonValue = { ok = true, busy = false, feed = { revision = "1:8", events = {
    { sequence = 7, kind = "assistant", text = "Incremental final" },
} } }
T.watch.agentik_chat_status({ stdout = "{}" })
joined = table.concat(T.labelTexts(T.trees.desktop), "|")
assert_true(joined:find("Incremental final", 1, true) ~= nil, "desktop appends shared revisioned feed deltas")
""",
    ),
    (
        "panel-proposals",
        "panel.luau",
        """
T.state.sessions = { active = 1, sessions = {
    { id = "s1", project = "proj-x", task = "choose", attention = "waiting", state = "listening",
      propositions = {
        { value = "1", label = "Keep the current layout" },
        { value = "2", label = "Use a compact layout" },
      } },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local texts = table.concat(T.labelTexts(T.trees.panel), "|")
local first = T.buttonsWithText(T.trees.panel, "1")[1]
local custom = T.buttonsWithText(T.trees.panel, "Custom")[1]
assert_true(texts:find("Keep the current layout", 1, true) ~= nil
    and texts:find("Use a compact layout", 1, true) ~= nil, "full choice labels rendered")
assert_true(first ~= nil and custom ~= nil, "choice and custom copy buttons rendered")
first.props.onClick()
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], nil, "choice copy stays fire-and-forget")
custom.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls - 1], 'wl-copy "1"', "choice is copied")
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], 'wl-copy "Custom: "', "custom response prefix is copied")
assert_equals(T.runAsyncTimeouts[#T.runAsyncTimeouts], nil, "desktop choice copy stays fire-and-forget")
""",
    ),
    (
        "desktop-proposals",
        "desktop_widget.luau",
        """
local sessions = { active = 1, sessions = {
    { id = "s1", project = "proj-x", task = "choose", attention = "blocked", state = "working",
      propositions = {
        { value = "1", label = "Keep the current layout" },
        { value = "2", label = "Use a compact layout" },
      } },
} }
T.state.sessions = sessions
T.watch.sessions(sessions)
local first = T.buttonsWithText(T.trees.desktop, "1")[1]
local custom = T.buttonsWithText(T.trees.desktop, "Custom")[1]
assert_true(first ~= nil and custom ~= nil, "compact choice and custom buttons rendered")
first.props.onClick()
custom.props.onClick()
assert_equals(T.runAsyncCalls[#T.runAsyncCalls - 1], 'wl-copy "1"', "choice is copied")
assert_equals(T.runAsyncCalls[#T.runAsyncCalls], 'wl-copy "Custom: "', "custom response prefix is copied")
""",
    ),
    (
        "panel-agentik-60",
        "panel.luau",
        """
T.nowMs = 750
T.state.sessions = { active = 1, sessions = {
    { id = "a", project = "proj-a", attention = "active", state = "working" },
} }
onOpen()
T.watch.sessions(T.state.sessions)
local paths = table.concat(T.imagePaths(T.trees.panel), "|")
assert_true(paths:find("/orbs-agentik-60/working-64-45.svg", 1, true) ~= nil,
    "local Agentik pack drives the panel at 60 FPS")
""",
    ),
    (
        "desktop-agentik-60",
        "desktop_widget.luau",
        """
T.nowMs = 750
T.state.sessions = { active = 1, sessions = {
    { id = "a", project = "proj-a", attention = "active", state = "working" },
} }
T.watch.sessions(T.state.sessions)
local paths = table.concat(T.imagePaths(T.trees.desktop), "|")
assert_true(paths:find("/orbs-agentik-60/working-20-45.svg", 1, true) ~= nil,
    "local Agentik pack drives the desktop widget at 60 FPS")
""",
    ),
]


def build_case(translations: str, script: str, test_body: str, defaults: str, files: str) -> str:
    script_source = (ROOT / script).read_text(encoding="utf-8")
    return (
        STUBS.replace("@@TRANSLATIONS@@", translations)
        .replace("@@DEFAULTS@@", defaults)
        .replace("@@FILES@@", files)
        + "\n" + script_source + "\n" + test_body
    )


def main() -> int:
    luau = shutil.which("luau")
    if luau is None:
        print("error: luau CLI not found on PATH (install from luau-lang/luau releases)", file=sys.stderr)
        return 1
    translations = translations_literal(ROOT / "translations" / "en.json")
    defaults = ", ".join(f'["{k}"] = {v}' for k, v in DEFAULTS.items())
    failures = 0
    with tempfile.TemporaryDirectory(prefix="agentik-luau-") as tmp:
        for name, script, body in CASES:
            files = (
                '["/plugin/orbs-agentik-60/manifest.json"] = true'
                if name.endswith("-agentik-60")
                else ""
            )
            source = build_case(translations, script, body, defaults, files)
            path = Path(tmp) / f"{name}.luau"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run([luau, str(path)], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"ok {name}")
            else:
                failures += 1
                print(f"FAIL {name}")
                print(result.stderr.strip())
    if failures:
        print(f"error: {failures} luau case(s) failed", file=sys.stderr)
        return 1
    print(f"luau harness: ok ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
