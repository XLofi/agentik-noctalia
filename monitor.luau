-- Read local OMP journals and supported-harness process state only.
local collector = noctalia.pluginDir() .. "/omp_sessions.py"
local chat_bridge = noctalia.pluginDir() .. "/chat_bridge.py"
-- Journals grow over time; give the collector the full window so a slow
-- refresh is not killed by runAsync's 5 s default timeout with empty stdout.
local collector_timeout_ms = 60000
local refreshing = false
local chat_refreshing = false
local chat_feed_revision = nil
local active_sessions = 0
local chat_busy = false

local function update_cadence()
    noctalia.setUpdateInterval((active_sessions > 0 or chat_busy) and 1000 or 5000)
end

local function hex_encode(value)
    local encoded = {}
    for index = 1, #value do
        encoded[#encoded + 1] = string.format("%02x", string.byte(value, index))
    end
    return table.concat(encoded)
end

local function refresh()
    if refreshing then return end
    refreshing = true
    local excluded = tostring(noctalia.getConfig("excluded_projects") or "")
    noctalia.runAsync(
        "AGENTIK_EXCLUDED_PROJECTS=" .. string.format("%q", excluded)
            .. " python3 " .. string.format("%q", collector),
        function(result)
        refreshing = false
        local sessions = noctalia.json.decode(result.stdout)
        if type(sessions) == "table" then
            active_sessions = tonumber(sessions.active) or 0
            noctalia.state.set("sessions", sessions)
            update_cadence()
        end
    end, collector_timeout_ms)
end

local function refresh_chat()
    if chat_refreshing then return end
    chat_refreshing = true
    local command = "python3 " .. string.format("%q", chat_bridge) .. " status"
    if type(chat_feed_revision) == "string" then
        command = command .. " " .. hex_encode(chat_feed_revision)
    end
    noctalia.runAsync(command, function(result)
        chat_refreshing = false
        local payload = noctalia.json.decode(result.stdout or "")
        chat_busy = type(payload) == "table" and payload.busy == true
        update_cadence()
        if type(payload) == "table" and type(payload.feed) == "table"
            and type(payload.feed.revision) == "string" then
            chat_feed_revision = payload.feed.revision
        end
        noctalia.state.set("agentik_chat_status", result)
    end, collector_timeout_ms)
end


function update()
    update_cadence()
    refresh()
    refresh_chat()
end

refresh()
refresh_chat()
update_cadence()
