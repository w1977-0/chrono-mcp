# chrono-mcp

**A zero-dependency date & time MCP server.** One file, pure Python standard library — no `mcp` package, no `pip install`, no virtualenv. AI agents are notoriously bad at knowing today's date, doing timezone math, and remembering DST rules; this server gives them seven precise, tested tools for exactly that.

```json
{"mcpServers": {"chrono": {"command": "python3", "args": ["/absolute/path/to/chrono_mcp.py"]}}}
```

## Why

- **AI models don't know what time it is.** Training data ends months before you ask; "today" is a guess. This server gives the real clock.
- **Timezone math is where agents hallucinate.** "Is Shanghai 12 or 13 hours ahead of New York right now?" depends on *when* "now" is, because of DST. All conversions here are DST-aware via the IANA database.
- **Zero dependencies, by design.** No supply chain, no version conflicts, nothing to audit. If you have Python 3.9+ you already have everything. The MCP protocol layer (JSON-RPC 2.0 over stdio) is implemented in the same file.

## Tools

| Tool | What it does | Example |
|---|---|---|
| `get_current_time` | Real current date/time in any IANA zone (or city alias) | `{"timezone": "tokyo"}` |
| `convert_time` | Wall-clock conversion across zones with day-rollover detection | `09:00` Shanghai → `21:00` New York *(previous day)* |
| `time_offset` | Live UTC-offset difference between two zones (DST-aware) | Shanghai → New York = `-12h00m` in September |
| `parse_natural_time` | Free-form phrase → precise ISO timestamp | `"next tuesday 3pm"`, `"3 days ago"`, `"sep 10 3pm"` |
| `add_duration` | Signed duration arithmetic, incl. business days | `"+3 hours"`, `"-2h30m"`, `"3 business days"` |
| `meeting_windows` | Common meeting slots across timezones within local business hours | Shanghai + London → `16:00 / 09:00` |
| `format_time` | strftime formatting with optional zone conversion | `%A, %B %d %Y %I:%M %p` |

City aliases work anywhere a timezone is accepted: `tokyo`, `beijing`, `new york`, `san francisco`, `london`, `dubai`, `utc`, and ~40 more.

## Install

### Any MCP client (Claude Desktop, Cursor, Windsurf, …)

Clone and point your client at the file:

```json
{
  "mcpServers": {
    "chrono": {
      "command": "python3",
      "args": ["/absolute/path/to/chrono-mcp/chrono_mcp.py"]
    }
  }
}
```

Claude Desktop: `claude mcp add chrono -- python3 /absolute/path/to/chrono-mcp/chrono_mcp.py`

### Requirements

- Python **3.9+** with the `zoneinfo` module (standard on 3.9+; on Windows also install `tzdata` from PyPI if zone lookups fail).

## Example phrases `parse_natural_time` understands

| Phrase | Result (Asia/Shanghai) |
|---|---|
| `next tuesday 3pm` | the coming Tuesday, 15:00 local |
| `tomorrow 09:00` | tomorrow, 09:00 local |
| `tonight` | today, 20:00 local |
| `in 2 hours` / `3 days ago` | relative to real current time |
| `friday 9:00` | the coming Friday |
| `last friday` | the most recent Friday |
| `2026-09-10 14:30` | exact datetime |
| `sep 10 3pm` / `september 10, 2026 2pm` | month-name dates |

## Example: `meeting_windows`

```
meeting_windows(timezones=["Asia/Shanghai", "Europe/London"], date="2026-09-02")
→ windows: [{ start_utc: 08:00, local_start: {Shanghai: 16:00, London: 09:00} }, …]
```

For a genuinely impossible pair (Shanghai + New York within 9–18 local), the server returns a clear `No common window` message with suggestions instead of guessing.

## Run the tests

```
python3 -m unittest discover -s tests
```

47 tests, covering every tool plus end-to-end JSON-RPC over a real subprocess (initialize → tools/list → tools/call, error recovery, notification handling).

## Protocol notes

Implements the stdio transport of the Model Context Protocol: newline-delimited JSON-RPC 2.0 with `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. Tool errors are returned as `isError: true` results (the server never crashes on bad input); unknown methods return `-32601`.

## License

MIT
