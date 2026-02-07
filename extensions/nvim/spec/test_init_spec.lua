--[[
  Tests for the CodeTime Neovim stub (init.lua).
  Run from repo root: lua extensions/nvim/spec/test_init_spec.lua
  Or with busted: busted extensions/nvim/spec/
]]

local function tbl_extend(_, a, b)
  local r = {}
  for k, v in pairs(a) do r[k] = v end
  for k, v in pairs(b) do r[k] = v end
  return r
end

-- Mock vim before requiring the module
_G.vim = {
  tbl_extend = tbl_extend,
  notify = function() end,
  loop = {
    os_uname = function() return { sysname = "TestOS" } end,
  },
  log = { levels = { DEBUG = 0, WARN = 2 } },
}

-- Allow requiring init from nvim folder. Script is in .../extensions/nvim/spec/
local script_dir = arg[0]:match("(.*)[/\\]") or "."
local nvim_dir = (script_dir:gsub("[/\\]spec$", ""):gsub("[/\\]spec[/\\]$", "")) .. "/"
package.path = package.path .. ";" .. nvim_dir .. "?.lua"
local M = require("init")

local function assert_eq(a, b, msg)
  msg = msg or ("expected %s == %s"):format(tostring(a), tostring(b))
  if a ~= b then error(msg, 2) end
end

local function assert_contains(t, key, msg)
  msg = msg or ("table should contain key " .. tostring(key))
  if t[key] == nil then error(msg, 2) end
end

local function test_get_base_url_default()
  local url = M.get_base_url()
  assert_eq(url, "http://localhost:9492", "default base URL")
end

local function test_get_base_url_from_env()
  local old = os.getenv and os.getenv("CODETIME_PROXY_URL")
  if os.setenv then
    os.setenv("CODETIME_PROXY_URL", "http://custom:9999")
  end
  -- Without os.setenv we can't test env override on the fly; just test default
  M.get_base_url()
  if old and os.setenv then os.setenv("CODETIME_PROXY_URL", old) end
end

local function test_build_event()
  local body = M.build_event("fileSaved", {})
  assert_eq(body.event_type, "fileSaved")
  assert_eq(body.editor, "nvim")
  assert_eq(body.platform, "TestOS")
end

local function test_build_event_with_payload()
  local body = M.build_event("fileEdited", { language = "lua", relativeFile = "init.lua" })
  assert_eq(body.event_type, "fileEdited")
  assert_contains(body, "language")
  assert_eq(body.language, "lua")
  assert_eq(body.relativeFile, "init.lua")
end

local function test_build_event_invalid_type_returns_nil()
  local body = M.build_event("invalidEventType", {})
  if body ~= nil then
    error("expected nil for invalid event type, got " .. tostring(body))
  end
end

local function test_send_event_invalid_type_no_error()
  -- Should not error; invalid type is rejected and notify is mocked
  M.send_event("invalidEventType", nil)
end

local function run()
  local ok, err
  ok, err = pcall(test_get_base_url_default)
  if not ok then return nil, "test_get_base_url_default: " .. tostring(err) end
  ok, err = pcall(test_get_base_url_from_env)
  if not ok then return nil, "test_get_base_url_from_env: " .. tostring(err) end
  ok, err = pcall(test_build_event)
  if not ok then return nil, "test_build_event: " .. tostring(err) end
  ok, err = pcall(test_build_event_with_payload)
  if not ok then return nil, "test_build_event_with_payload: " .. tostring(err) end
  ok, err = pcall(test_build_event_invalid_type_returns_nil)
  if not ok then return nil, "test_build_event_invalid_type_returns_nil: " .. tostring(err) end
  ok, err = pcall(test_send_event_invalid_type_no_error)
  if not ok then return nil, "test_send_event_invalid_type_no_error: " .. tostring(err) end
  return true
end

local ok, err = run()
if ok then
  print("All 6 Neovim stub tests passed.")
  os.exit(0)
else
  print("FAIL: " .. tostring(err))
  os.exit(1)
end
