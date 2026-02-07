# Neovim stub tests

Run the tests from the **repository root** (code-time/). Requires Lua 5.1+ (e.g. `lua`, `luajit`, or `lua5.4`):

```bash
lua extensions/nvim/spec/test_init_spec.lua
```

Or with LuaJIT:

```bash
luajit extensions/nvim/spec/test_init_spec.lua
```

The tests mock `vim` and exercise `get_base_url()` and `build_event()`.
