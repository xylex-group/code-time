--[[
  CodeTime proxy – Neovim stub
  Send editor events to the code-time proxy (e.g. http://localhost:9492).
  Event types: activateFileChanged, editorChanged, fileSaved, fileAddedLine,
  fileCreated, fileEdited, changeEditorSelection, changeEditorVisibleRanges.
]]

local M = {}

local default_base_url = "http://localhost:9492"
local event_log_path = "/v3/users/event-log"
local user_agent = "CodeTime Client"

local allowed_event_types = {
  "activateFileChanged",
  "editorChanged",
  "fileSaved",
  "fileAddedLine",
  "fileCreated",
  "fileEdited",
  "changeEditorSelection",
  "changeEditorVisibleRanges",
}

local function is_allowed_event_type(event_type)
  if type(event_type) ~= "string" then
    return false
  end
  for _, allowed in ipairs(allowed_event_types) do
    if allowed == event_type then
      return true
    end
  end
  return false
end

--- Get proxy base URL from env or config; normalizes to http(s) and strips trailing slash.
function M.get_base_url()
  local raw = os.getenv("CODETIME_PROXY_URL") or default_base_url
  if type(raw) ~= "string" then
    return default_base_url
  end
  local s = raw:gsub("%s+", ""):gsub("/+$", "")
  if s:match("^https?://") then
    return s
  end
  return default_base_url
end

--- Build event payload for the proxy (stub shape; extend with real editor data).
--- Returns nil if event_type is not allowed.
---@param event_type string One of the allowed event types
---@param payload table|nil Optional extra fields (filepath, language, etc.)
---@return table|nil
function M.build_event(event_type, payload)
  if not is_allowed_event_type(event_type) then
    return nil
  end
  payload = payload or {}
  local platform = "unknown"
  if vim.loop and vim.loop.os_uname and vim.loop.os_uname() then
    platform = vim.loop.os_uname().sysname or platform
  end
  return vim.tbl_extend("force", {
    event_type = event_type,
    editor = "nvim",
    platform = platform,
  }, payload)
end

--- Send event to proxy (stub: no HTTP yet; add vim.fn.jobstart or async HTTP client).
--- Uses pcall; on error notifies user at WARN level.
---@param event_type string
---@param payload table|nil
function M.send_event(event_type, payload)
  local ok, body = pcall(function()
    return M.build_event(event_type, payload)
  end)
  if not ok then
    vim.notify("[codetime] build_event failed: " .. tostring(body), vim.log.levels.WARN)
    return
  end
  if not body then
    vim.notify("[codetime] invalid event type: " .. tostring(event_type), vim.log.levels.WARN)
    return
  end
  local base = M.get_base_url()
  local url = base .. event_log_path
  -- TODO: POST body to url with User-Agent: CodeTime Client and Authorization if set
  vim.notify(
    string.format("[codetime] would send %s to %s", event_type, url),
    vim.log.levels.DEBUG
  )
end

return M
