"""Regression checks for the public feed and calendar identities."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import sixaside


class SixAsideTests(unittest.TestCase):
    def setUp(self):
        self.draw = {
            "divs": ["U12", "U14"], "labels": {"U12": "Under 12s", "U14": "Under 14s"},
            "teams": {
                "U12": [{"name": "The Academy", "colour": "Black & White"}, {"name": "The Ballers"}, {"name": "Cottesloe Comets"}],
                "U14": [{"name": "The Army", "colour": "Blue & White"}, {"name": "Piara Waters Senior Boys"}, {"name": "Tekky Ballers"}],
            },
            "games": [
                {"id": "r02-u14-630pm-p4", "round": 2, "date": "19/10/2026", "time": "6:30 pm", "pitch": 4,
                 "div": "U14", "home": "Piara Waters Senior Boys", "away": "The Army"},
                {"id": "r03-u14-630pm-p4", "round": 3, "date": "26/10/2026", "time": "6:30 pm", "pitch": 4,
                 "div": "U14", "home": "The Army", "away": "Tekky Ballers"},
                {"id": "r01-u12-630pm-p3", "round": 1, "date": "12/10/2026", "time": "6:30 pm", "pitch": 3,
                 "div": "U12", "home": "The Academy", "away": "The Ballers"},
                {"id": "r02-u12-630pm-p1", "round": 2, "date": "19/10/2026", "time": "6:30 pm", "pitch": 1,
                 "div": "U12", "home": "Cottesloe Comets", "away": "The Ballers"},
            ],
            "byes": [{"round": 1, "div": "U14", "team": "The Army"}],
            "dates": [{"round": 1, "date": "12/10/2026"}, {"round": 2, "date": "19/10/2026"}, {"round": 3, "date": "26/10/2026"}],
            "changes": [], "generated": "09 Oct 2026 21:02",
        }
        self.snapshot = sixaside.prepare_snapshot(self.draw, None)

    def test_existing_uid_survives_changed_time_pitch_home_order_and_source_id(self):
        old = next(f for f in self.snapshot["calendar_fixtures"] if f["source_id"] == "r02-u14-630pm-p4")
        old["uid"] = "existing-subscription-event@family-soccer-calendar"
        changed = copy.deepcopy(self.draw)
        changed["games"][0].update(id="r02-u14-715pm-p2", date="20/10/2026", time="7:15 pm", pitch=2,
                                   home="The Army", away="Piara Waters Senior Boys")
        snapshot = sixaside.prepare_snapshot(changed, {}, self.snapshot)
        fixture = next(f for f in snapshot["calendar_fixtures"] if f["source_id"] == "r02-u14-715pm-p2")
        self.assertEqual(fixture["uid"], old["uid"])
        self.assertEqual(fixture["start"], "2026-10-20T19:15:00+08:00")
        self.assertEqual(fixture["field"], "Pitch 2")
        self.assertFalse(any(f["status"] == "CANCELLED" for f in snapshot["calendar_fixtures"]))

    def test_ladder_matches_win_draw_and_goal_difference_rules_including_zero_scores(self):
        scores = {"r02-u14-630pm-p4": {"h": 2, "a": 5}, "r03-u14-630pm-p4": {"h": 0, "a": 0}}
        snapshot = sixaside.prepare_snapshot(self.draw, scores, self.snapshot)
        ladder = next(l for l in snapshot["ladders"] if l["division"] == "U14")
        army = ladder["rows"][0]
        self.assertEqual(army["team"], "The Army")
        self.assertEqual((army["played"], army["won"], army["drawn"], army["lost"], army["points"]), (2, 1, 1, 0, 4))
        self.assertEqual((army["for"], army["against"], army["difference"]), (5, 2, 3))
        fixture = next(f for f in snapshot["calendar_fixtures"] if f["source_id"] == "r03-u14-630pm-p4")
        self.assertEqual((fixture["home_score"], fixture["away_score"]), ("0", "0"))

    def test_full_division_results_include_other_teams_without_adding_their_calendar_events(self):
        snapshot = sixaside.prepare_snapshot(self.draw, {"r02-u12-630pm-p1": {"h": 3, "a": 1}})
        self.assertIn("r02-u12-630pm-p1", snapshot["results"])
        self.assertFalse(any(f["source_id"] == "r02-u12-630pm-p1" for f in snapshot["calendar_fixtures"]))

    def test_finals_draw_replaces_placeholder_with_same_uid(self):
        old = next(f for f in self.snapshot["calendar_fixtures"] if f["label"] == "Finn" and f["status"] == "TENTATIVE")
        released = copy.deepcopy(self.draw)
        released["games"].append({"id": "r10-u14-final", "round": 10, "date": "14/12/2026", "time": "7:15 pm",
                                  "pitch": 2, "div": "U14", "home": "The Army", "away": "Tekky Ballers"})
        snapshot = sixaside.prepare_snapshot(released, {}, self.snapshot)
        finals = [f for f in snapshot["calendar_fixtures"] if f["label"] == "Finn" and sixaside.fixture_round(f) == "10"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["uid"], old["uid"])
        self.assertEqual(finals[0]["status"], "CONFIRMED")
        self.assertNotIn("time_window", finals[0])

    def test_removed_fixture_is_cancelled_with_original_uid(self):
        old = next(f for f in self.snapshot["calendar_fixtures"] if f["source_id"] == "r02-u14-630pm-p4")
        reduced = copy.deepcopy(self.draw)
        reduced["games"].pop(0)
        snapshot = sixaside.prepare_snapshot(reduced, {}, self.snapshot)
        cancelled = next(f for f in snapshot["calendar_fixtures"] if f["uid"] == old["uid"])
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertTrue(cancelled["removed"])
        again = sixaside.prepare_snapshot(reduced, {}, snapshot)
        self.assertEqual(again["calendar_fixtures"], snapshot["calendar_fixtures"])

    def test_byes_stay_out_of_calendar_and_missing_time_stays_tentative(self):
        self.assertFalse(any(f["start"].startswith("2026-10-12") and f["label"] == "Finn" for f in self.snapshot["calendar_fixtures"]))
        changed = copy.deepcopy(self.draw)
        changed["games"][0]["time"] = "TBC"
        snapshot = sixaside.prepare_snapshot(changed, {}, self.snapshot)
        fixture = next(f for f in snapshot["calendar_fixtures"] if f["source_id"] == "r02-u14-630pm-p4")
        self.assertEqual((fixture["all_day"], fixture["status"], fixture["reminder_minutes"]), (True, "TENTATIVE", 0))

    def test_feed_outage_keeps_cache_and_unchanged_refresh_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "sixaside.json"
            cache.write_text(json.dumps(self.snapshot))
            def public(url):
                return "window.LEAGUE = " + json.dumps(self.draw) + ";" if url == sixaside.DRAW_URL else "null"
            with patch.object(sixaside, "CACHE", cache), patch.object(sixaside, "read_public", side_effect=public):
                fixtures, debug = sixaside.refresh_sixaside_fixtures(ZoneInfo("Australia/Perth"))
                first = cache.read_bytes()
                sixaside.refresh_sixaside_fixtures(ZoneInfo("Australia/Perth"))
                self.assertEqual(cache.read_bytes(), first)
                self.assertFalse(debug["used_cache"])
            with patch.object(sixaside, "CACHE", cache), patch.object(sixaside, "read_public", side_effect=OSError("offline")):
                cached, debug = sixaside.refresh_sixaside_fixtures(ZoneInfo("Australia/Perth"))
                self.assertTrue(debug["used_cache"])
                self.assertEqual(cached, fixtures)
                self.assertEqual(json.loads(cache.read_text())["results_status"], "cached")

    def test_broken_draw_keeps_valid_score_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "sixaside.json"
            cache.write_text(json.dumps(self.snapshot))
            def public(url):
                if url == sixaside.DRAW_URL:
                    return "window.LEAGUE = {};"
                return json.dumps({"r03-u14-630pm-p4": {"h": 0, "a": 0}})
            with patch.object(sixaside, "CACHE", cache), patch.object(sixaside, "read_public", side_effect=public):
                fixtures, debug = sixaside.refresh_sixaside_fixtures(ZoneInfo("Australia/Perth"))
                self.assertTrue(debug["used_cache"])
                result = next(f for f in fixtures if f["source_id"] == "r03-u14-630pm-p4")
                self.assertEqual((result["home_score"], result["away_score"]), ("0", "0"))

    def test_score_failure_keeps_draw_changes(self):
        changed = copy.deepcopy(self.draw)
        changed["games"][0]["pitch"] = 2
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "sixaside.json"
            cache.write_text(json.dumps(self.snapshot))
            def public(url):
                if url == sixaside.RESULTS_URL:
                    raise OSError("offline")
                return "window.LEAGUE = " + json.dumps(changed) + ";"
            with patch.object(sixaside, "CACHE", cache), patch.object(sixaside, "read_public", side_effect=public):
                fixtures, debug = sixaside.refresh_sixaside_fixtures(ZoneInfo("Australia/Perth"))
                self.assertTrue(debug["used_cache"])
                self.assertEqual(next(f for f in fixtures if f["source_id"] == "r02-u14-630pm-p4")["field"], "Pitch 2")

    def test_only_json_is_read_and_invalid_scores_are_rejected(self):
        with self.assertRaises(ValueError):
            sixaside.decode_draw('window.LEAGUE = {}; fetch("https://example.com");')
        with self.assertRaises(ValueError):
            sixaside.prepare_snapshot(self.draw, {"r03-u14-630pm-p4": {"h": -1, "a": 0}})


if __name__ == "__main__":
    unittest.main()
