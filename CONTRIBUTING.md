# Contributing to chrono-mcp

chrono-mcp is one file, `chrono_mcp.py`, plus one test file. That shape is the point: an MCP server for date and time that you can read end to end and install without pulling anything else in. Changes that make it bigger without making it more correct are usually the wrong trade.

## Before you start

Read the [README](README.md) and the [security policy](SECURITY.md). By contributing code, documentation, or tests you agree that your work can be distributed under the MIT License.

## Development setup

There is nothing to install. That is deliberate, and it is the constraint to protect.

```bash
git clone https://github.com/w1977-0/chrono-mcp.git
cd chrono-mcp
python3 -m unittest discover -s tests
```

Expected result: 47 tests pass. If you cannot run them on your machine, say so in the pull request and name your Python version — the suite needs 3.9 or later for `zoneinfo`.

## The two rules

**No runtime dependencies.** The standard library is the whole budget. If a change wants a third-party package, it needs a separate conversation first, because the value of this server is that it works anywhere Python does.

**Never hand-compute an offset.** Every timezone answer comes from `zoneinfo`, and every comparison happens on real `datetime` objects rather than on offsets or epoch subtraction. DST transitions, half-hour zones, and negative offsets are where hand-rolled arithmetic quietly breaks — if you find yourself adding hours, stop and look for the `zoneinfo` call that does it properly.

## Adding a tool

A new tool touches four places, and a pull request that touches fewer than four is missing something:

1. the handler function in `chrono_mcp.py`
2. its registration in the tool list, including the JSON schema for its arguments
3. tests in `tests/test_chrono.py`, including at least one case that crosses a DST boundary where the tool is timezone-sensitive
4. the tools table and an example phrase in the README

Tool errors are returned as `isError: true` results. A tool that raises and kills the server is a bug, not an error report — the server is expected to survive bad input.

## Tests

The suite is pure `unittest` on purpose, so it runs with no install step and no plugin. It covers each tool, plus an end-to-end pass that starts the real process and speaks JSON-RPC to it over a pipe: `initialize` → `tools/list` → `tools/call`, then error recovery and notification handling.

Pin new facts to the civil calendar — choose reference instants away from DST transitions unless the transition is what you are testing. A test that passes in one half of the year and fails in the other is a test that was never deterministic.

## Commit messages

Short imperative subject with a type prefix, then a blank line and the reasoning:

```
fix: reject unknown zones instead of falling back silently
feat: add meeting_windows across three zones
```

The body is where the "why" goes. A one-line subject with no body is fine when the change is obvious.

## What this project does not do

No network calls, no filesystem writes, no configuration files, no credentials, and no dependencies. It answers questions about dates and times and nothing else.
