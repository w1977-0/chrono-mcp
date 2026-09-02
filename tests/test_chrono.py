"""chrono-mcp test suite — pure unittest, no third-party dependencies.

Facts used below are pinned to the civil calendar (no DST transitions in
the referenced windows), so the tests are deterministic.

Reference instant: 2026-09-02 (a Wednesday), noon UTC.
"""

import datetime as dt
import json
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

import chrono_mcp as c

REF = "2026-09-02T12:00:00+00:00"  # Wednesday, noon UTC
SH = "Asia/Shanghai"


class ZoneTests(unittest.TestCase):
    def test_iana_names_resolve(self):
        self.assertEqual(c.resolve_zone("Asia/Shanghai").key, "Asia/Shanghai")
        self.assertEqual(c.resolve_zone(" America/New_York ").key, "America/New_York")

    def test_city_aliases(self):
        for alias, iana in [
            ("tokyo", "Asia/Tokyo"),
            ("Beijing", "Asia/Shanghai"),
            ("new york", "America/New_York"),
            ("UTC", "UTC"),
        ]:
            self.assertEqual(c.resolve_zone(alias).key, iana)

    def test_unknown_zone_raises(self):
        with self.assertRaises(ValueError):
            c.resolve_zone("Mars/Olympus_Mons")


class CurrentTimeTests(unittest.TestCase):
    def test_current_time_fields(self):
        r = c.get_current_time("Asia/Shanghai")
        self.assertEqual(r["timezone"], "Asia/Shanghai")
        self.assertEqual(r["utc_offset"], "+08:00")
        self.assertIn(r["weekday"], ["Monday", "Tuesday", "Wednesday",
                                     "Thursday", "Friday", "Saturday", "Sunday"])
        # ISO string must round-trip
        parsed = dt.datetime.fromisoformat(r["iso"])
        self.assertEqual(parsed.utcoffset().total_seconds(), 8 * 3600)

    def test_dst_flag(self):
        # Shanghai has no DST; America/New_York in September is EDT (DST on).
        self.assertFalse(c.get_current_time("Asia/Shanghai")["is_dst"])
        r = c.get_current_time("America/New_York")
        self.assertTrue(r["is_dst"])  # September = EDT


class ConvertTests(unittest.TestCase):
    def test_shanghai_to_new_york_rollover(self):
        # 09:00 Shanghai on 2026-09-02 = 21:00 New York on 2026-09-01 (EDT, -12h with DST)
        r = c.convert_time("09:00", "Asia/Shanghai", "America/New_York", date="2026-09-02")
        self.assertEqual(r["result"]["time"], "21:00")
        self.assertEqual(r["result"]["date"], "2026-09-01")
        self.assertEqual(r["day_shift"], "previous day")

    def test_london_to_sydney_next_day(self):
        # 09:00 London (BST, +1) on 2026-09-02 = 18:00 Sydney (AEST, +10) same day
        r = c.convert_time("09:00", "Europe/London", "Australia/Sydney", date="2026-09-02")
        self.assertEqual(r["result"]["time"], "18:00")
        self.assertEqual(r["day_shift"], "same day")

    def test_utc_to_kathmandu_odd_offset(self):
        # UTC+05:45 — the offset math must keep the quarter-hour
        r = c.convert_time("12:00", "UTC", "Asia/Kathmandu", date="2026-09-02")
        self.assertEqual(r["result"]["time"], "17:45")

    def test_12h_clock_input(self):
        r = c.convert_time("3:30pm", "UTC", "Asia/Tokyo", date="2026-09-02")
        self.assertEqual(r["result"]["time"], "00:30")
        self.assertEqual(r["result"]["date"], "2026-09-03")


class OffsetTests(unittest.TestCase):
    def test_shanghai_new_york(self):
        r = c.time_offset("Asia/Shanghai", "America/New_York")
        self.assertEqual(r["difference_minutes"], -720)  # -12h in September (EDT)
        self.assertEqual(r["difference_human"], "-12h00m")

    def test_utc_dubai(self):
        self.assertEqual(c.time_offset("UTC", "Asia/Dubai")["difference_human"], "+04h00m")

    def test_alias_zones(self):
        r = c.time_offset("beijing", "new york")
        self.assertEqual(r["from"]["timezone"], "Asia/Shanghai")
        self.assertEqual(r["to"]["timezone"], "America/New_York")


class NaturalParseTests(unittest.TestCase):
    def assertParses(self, phrase, want_date, want_time, tz=SH, now=REF):
        r = c.parse_natural_time(phrase, timezone=tz, now=now)
        self.assertEqual(r["date"], want_date, f"{phrase!r}: date {r['date']} != {want_date}")
        self.assertEqual(r["time"], want_time, f"{phrase!r}: time {r['time']} != {want_time}")
        return r

    def test_weekdays(self):
        # 2026-09-02 is a Wednesday
        self.assertParses("friday", "2026-09-04", "00:00:00")
        self.assertParses("next tuesday", "2026-09-08", "00:00:00")
        self.assertParses("next wednesday", "2026-09-09", "00:00:00")
        self.assertParses("last friday", "2026-08-28", "00:00:00")
        self.assertParses("next friday 9am", "2026-09-04", "09:00:00")
        self.assertParses("friday 9:00", "2026-09-04", "09:00:00")

    def test_relative_days(self):
        self.assertParses("today", "2026-09-02", "00:00:00")
        self.assertParses("tomorrow 3pm", "2026-09-03", "15:00:00")
        self.assertParses("yesterday", "2026-09-01", "00:00:00")
        self.assertParses("tonight", "2026-09-02", "20:00:00")

    def test_relative_durations(self):
        self.assertParses("in 2 hours", "2026-09-02", "14:00:00")
        self.assertParses("in 30 minutes", "2026-09-02", "12:30:00")
        self.assertParses("3 days ago", "2026-08-30", "12:00:00")
        self.assertParses("half an hour ago", "2026-09-02", "11:30:00")

    def test_explicit_dates(self):
        self.assertParses("2026-09-10 14:30", "2026-09-10", "14:30:00")
        self.assertParses("sep 10 3pm", "2026-09-10", "15:00:00")
        self.assertParses("10 september", "2026-09-10", "00:00:00")
        self.assertParses("september 10, 2026 2pm", "2026-09-10", "14:00:00")

    def test_time_only(self):
        self.assertParses("9am", "2026-09-02", "09:00:00")
        self.assertParses("14:30", "2026-09-02", "14:30:00")

    def test_timezone_of_result(self):
        r = self.assertParses("tomorrow 9am", "2026-09-03", "09:00:00")
        self.assertEqual(r["timezone"], "Asia/Shanghai")
        self.assertEqual(r["iso"], "2026-09-03T09:00:00+08:00")

    def test_date_only_flags_midnight(self):
        r = c.parse_natural_time("friday", timezone=SH, now=REF)
        self.assertFalse(r["time_provided"])
        self.assertIsNotNone(r["note"])

    def test_garbage_raises(self):
        for bad in ["", "banana", "sometime", "2026-13-45"]:
            with self.assertRaises(ValueError):
                c.parse_natural_time(bad, timezone=SH, now=REF)


class DurationTests(unittest.TestCase):
    def test_business_days_skip_weekend(self):
        # Friday 2026-09-04 + 3 business days = Wednesday 2026-09-09
        r = c.add_duration(start="2026-09-04T10:00:00+00:00", duration="3 business days")
        self.assertTrue(r["result_iso"].startswith("2026-09-09"))
        self.assertEqual(r["calendar_days_between"], 5)

    def test_negative_compound(self):
        r = c.add_duration(start="2026-09-02T12:00:00+00:00", duration="-2h30m")
        self.assertEqual(r["result_iso"], "2026-09-02T09:30:00+00:00")

    def test_compound_hours_minutes(self):
        r = c.add_duration(start="2026-09-02T00:00:00+00:00", duration="2h30m")
        self.assertEqual(r["result_iso"], "2026-09-02T02:30:00+00:00")

    def test_plus_hours_word(self):
        r = c.add_duration(start="2026-09-02T12:00:00+00:00", duration="+3 hours")
        self.assertEqual(r["result_iso"], "2026-09-02T15:00:00+00:00")

    def test_bare_number_is_minutes(self):
        r = c.add_duration(start="2026-09-02T12:00:00+00:00", duration="90")
        self.assertEqual(r["result_iso"], "2026-09-02T13:30:00+00:00")

    def test_business_days_backwards(self):
        # Monday 2026-09-07 - 1 business day = Friday 2026-09-04
        r = c.add_duration(start="2026-09-07T09:00:00+00:00", duration="-1 business days")
        self.assertTrue(r["result_iso"].startswith("2026-09-04"))

    def test_now_start(self):
        r = c.add_duration(start="now", duration="0 minutes", timezone="Asia/Tokyo")
        self.assertEqual(r["timezone"], "Asia/Tokyo")
        self.assertTrue(r["result_iso"].startswith("2026-"))

    def test_bad_duration(self):
        for bad in ["", "flurg", "-h30"]:
            with self.assertRaises(ValueError):
                c.add_duration(start="now", duration=bad)


class MeetingWindowsTests(unittest.TestCase):
    def test_shanghai_london_overlap(self):
        # 7h apart: Shanghai 16:00-18:00 = London 9:00-11:00 fits both 9-18 windows.
        r = c.meeting_windows(["Asia/Shanghai", "Europe/London"], date="2026-09-02")
        self.assertTrue(r["windows"], "expected at least one window")
        first = r["windows"][0]
        self.assertEqual(first["local_start"]["Asia/Shanghai"], "16:00")
        self.assertEqual(first["local_start"]["Europe/London"], "09:00")

    def test_shanghai_new_york_no_overlap(self):
        # 12h apart with 9-hour business windows: genuinely impossible; must
        # return the helpful empty result, not a crash.
        r = c.meeting_windows(["Asia/Shanghai", "America/New_York"], date="2026-09-02")
        self.assertEqual(r["windows"], [])
        self.assertIn("No common window", r["message"])

    def test_widened_hours_find_overlap(self):
        # Same pair, NY willing to start at 8am: Shanghai 20:00-21:00 = NY 8:00-9:00.
        r = c.meeting_windows(["Asia/Shanghai", "America/New_York"],
                              start_hour=8, end_hour=22, date="2026-09-02")
        self.assertTrue(r["windows"])

    def test_single_zone_full_business_day(self):
        r = c.meeting_windows(["Asia/Tokyo"], date="2026-09-02")
        self.assertEqual(r["windows"][0]["local_start"]["Asia/Tokyo"], "09:00")
        # 30-min grid: last slot that still ends by 18:00 starts at 17:00
        self.assertEqual(r["windows"][-1]["local_end"]["Asia/Tokyo"], "18:00")

    def test_bad_hours_rejected(self):
        with self.assertRaises(ValueError):
            c.meeting_windows(["UTC"], start_hour=18, end_hour=9)


class FormatTests(unittest.TestCase):
    def test_strftime_with_zone_convert(self):
        r = c.format_time("2026-09-02T12:00:00+00:00",
                          "%A, %B %d %Y %I:%M %p", "America/New_York")
        self.assertEqual(r["result"], "Wednesday, September 02 2026 08:00 AM")

    def test_now(self):
        r = c.format_time("now", "%Y", timezone="Asia/Tokyo")
        self.assertEqual(r["result"], "2026")

    def test_z_suffix_normalized(self):
        r = c.format_time("2026-09-02T12:00:00Z", "%H:%M", "Asia/Shanghai")
        self.assertEqual(r["result"], "20:00")

    def test_zone_name_in_result(self):
        r = c.format_time("2026-09-02T12:00:00+00:00", "%H:%M", "Asia/Shanghai")
        self.assertEqual(r["timezone"], "Asia/Shanghai")
        self.assertEqual(r["result"], "20:00")


class ProtocolTests(unittest.TestCase):
    """End-to-end: spawn the real server as a subprocess and speak JSON-RPC."""

    @classmethod
    def setUpClass(cls):
        payload = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": c.PROTOCOL_VERSION}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "get_current_time",
                                   "arguments": {"timezone": "Asia/Shanghai"}}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "parse_natural_time",
                                   "arguments": {"text": "next tuesday 3pm",
                                                  "timezone": "Asia/Shanghai",
                                                  "now": REF}}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "convert_time",
                                   "arguments": {"time": "09:00", "from_tz": "beijing",
                                                  "to_tz": "new york", "date": "2026-09-02"}}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "meeting_windows",
                                   "arguments": {"timezones": ["Asia/Shanghai", "Europe/London"],
                                                  "date": "2026-09-02"}}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "get_current_time",
                                   "arguments": {"timezone": "Not/AZone"}}}) + "\n" +
            json.dumps({"jsonrpc": "2.0", "id": 8, "method": "bogus/method"}) + "\n"
        )
        proc = subprocess.run(
            [sys.executable, "chrono_mcp.py"],
            input=payload, capture_output=True, text=True, timeout=30,
        )
        lines = [json.loads(l) for l in proc.stdout.strip().splitlines() if l.strip()]
        cls.responses = {resp["id"]: resp for resp in lines if "id" in resp}
        cls.raw_lines = lines
        cls.proc = proc

    def test_initialize(self):
        r = self.responses[1]["result"]
        self.assertEqual(r["serverInfo"]["name"], "chrono-mcp")
        self.assertEqual(r["protocolVersion"], c.PROTOCOL_VERSION)

    def test_tools_list_has_seven(self):
        tools = self.responses[2]["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"get_current_time", "convert_time", "time_offset",
                                 "parse_natural_time", "add_duration",
                                 "meeting_windows", "format_time"})
        for t in tools:
            self.assertIn("inputSchema", t)
            self.assertIn("description", t)

    def test_call_current_time(self):
        text = self.responses[3]["result"]["content"][0]["text"]
        data = json.loads(text)
        self.assertEqual(data["timezone"], "Asia/Shanghai")

    def test_call_parse_natural(self):
        data = json.loads(self.responses[4]["result"]["content"][0]["text"])
        self.assertEqual(data["date"], "2026-09-08")
        self.assertEqual(data["time"], "15:00:00")

    def test_call_convert_with_aliases(self):
        data = json.loads(self.responses[5]["result"]["content"][0]["text"])
        self.assertEqual(data["result"]["time"], "21:00")
        self.assertEqual(data["result"]["timezone"], "America/New_York")

    def test_call_meeting_windows(self):
        data = json.loads(self.responses[6]["result"]["content"][0]["text"])
        self.assertTrue(data["windows"])

    def test_error_is_isError_not_crash(self):
        # Bad timezone must come back as a tool error payload, and the server
        # must keep answering afterwards.
        r = self.responses[7]["result"]
        self.assertTrue(r["isError"])
        self.assertIn("Unknown timezone", r["content"][0]["text"])

    def test_unknown_method(self):
        self.assertEqual(self.responses[8]["error"]["code"], -32601)

    def test_notification_produces_no_response(self):
        # 8 requests with ids + 1 notification => exactly 8 id responses
        self.assertEqual(len(self.responses), 8)

    def test_no_stderr_noise(self):
        self.assertEqual(self.proc.stderr.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
