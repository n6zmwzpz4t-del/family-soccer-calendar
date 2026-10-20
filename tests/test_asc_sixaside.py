import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import asc_sixaside as asc


class AscSixAsideTests(unittest.TestCase):
    def setUp(self):
        self.tournament = {
            "id": asc.TOURNAMENT_ID, "liveLink": asc.LIVE_LINK,
            "name": "Armadale SC Summer 6-a-Side", "timezone": "Australia/Perth",
            "showSchedule": True, "matchDuration": "35",
            "fields": {"0": {"name": "Pitch 1", "sportPark": "0"}, "1": {"name": "Pitch 2", "sportPark": "0"}},
        }
        self.data = {
            "teams": [
                {"id": asc.TEAM_ID, "name": "6 Shooters", "division": "u14", "poule0": "pool", "numInPoule0": 4},
                {"id": "grey", "name": "Grey Wolves ", "division": "u14", "poule0": "pool", "numInPoule0": 0},
                {"id": "army", "name": "Army", "division": "u14", "poule0": "pool", "numInPoule0": 1},
                {"id": "other", "name": "Another team", "division": "u12", "poule0": "other-pool", "numInPoule0": 4},
            ],
            "days": [{"id": "day", "date": 1792512000}],  # 21 October in Perth; 20 October in UTC.
            "divisions": [{"id": "u14", "name": "Boys - U14"}],
            "poules": [{"id": "pool", "division": "u14", "fase": 0}, {"id": "other-pool", "division": "u12", "fase": 0}],
            "sportParks": [{"id": "0", "name": "Alfred Skeet Reserve, Forrestdale"}],
            "matches": [
                {"id": "m1", "poule": "pool", "team1": 0, "team2": 4, "round": 1,
                 "day": "day", "st": "19:15", "et": "19:50", "field": "1", "score1": None, "score2": None},
                {"id": "m2", "poule": "pool", "team1": 4, "team2": 1, "round": 2,
                 "day": "day", "st": "18:30", "et": "19:05", "field": "0", "score1": None, "score2": None},
                {"id": "other-game", "poule": "other-pool", "team1": 0, "team2": 4, "round": 1},
            ],
        }
        self.snapshot = asc.prepare_snapshot(self.tournament, self.data)

    def test_exact_team_id_pool_mapping_and_perth_dates(self):
        fixtures = self.snapshot["fixtures"]
        self.assertEqual({f["source_id"] for f in fixtures}, {"m1", "m2"})
        first = next(f for f in fixtures if f["source_id"] == "m1")
        self.assertEqual(first["start"], "2026-10-21T19:15:00+08:00")
        self.assertEqual((first["home"], first["away"], first["field"], first["duration_minutes"]),
                         ("Grey Wolves", "6 Shooters", "Pitch 2", 35))
        self.assertEqual(first["reminder_minutes"], 90)
        self.assertEqual(first["notes"], "")

    def test_reschedules_and_opponent_changes_keep_uid(self):
        changed = copy.deepcopy(self.data)
        changed["matches"][0].update(st="18:00", et="18:35", field="0", team1=1)
        new = asc.prepare_snapshot(self.tournament, changed, self.snapshot)
        old = next(f for f in self.snapshot["fixtures"] if f["source_id"] == "m1")
        moved = next(f for f in new["fixtures"] if f["source_id"] == "m1")
        self.assertEqual(moved["uid"], old["uid"])
        self.assertEqual(moved["home"], "Army")

    def test_zero_scores_and_missing_times(self):
        changed = copy.deepcopy(self.data)
        changed["matches"][0].update(score1=0, score2=0, st="", et="")
        fixture = next(f for f in asc.prepare_snapshot(self.tournament, changed)["fixtures"] if f["source_id"] == "m1")
        self.assertEqual((fixture["home_score"], fixture["away_score"]), ("0", "0"))
        self.assertEqual((fixture["status"], fixture["all_day"], fixture["reminder_minutes"]), ("TENTATIVE", True, 0))

    def test_withdrawn_game_is_cancelled(self):
        changed = copy.deepcopy(self.data)
        changed["matches"] = changed["matches"][1:]
        new = asc.prepare_snapshot(self.tournament, changed, self.snapshot)
        removed = next(f for f in new["fixtures"] if f["source_id"] == "m1")
        old = next(f for f in self.snapshot["fixtures"] if f["source_id"] == "m1")
        self.assertEqual(removed["status"], "CANCELLED")
        self.assertEqual(removed["uid"], old["uid"])

    def test_finals_appear_only_when_assigned_to_target_team(self):
        changed = copy.deepcopy(self.data)
        changed["poules"].append({"id": "final", "division": "u14", "fase": 1, "singleMatch": True, "name": "Grand Final"})
        changed["matches"].append(dict(changed["matches"][0], id="final-match", poule="final", team1=0, team2=1))
        self.assertEqual(len(asc.prepare_snapshot(self.tournament, changed)["fixtures"]), 2)
        changed["teams"][0].update(poule1="final", numInPoule1=0)
        changed["teams"][1].update(poule1="final", numInPoule1=1)
        finals = asc.prepare_snapshot(self.tournament, changed)["fixtures"]
        self.assertEqual(len(finals), 3)
        self.assertTrue(any(f["round"] == "Grand Final" for f in finals))

    def test_pagination_and_firestore_types(self):
        def doc(identifier):
            return {"name": "projects/test/documents/teams/" + identifier,
                    "fields": {"name": {"stringValue": identifier}, "slot": {"integerValue": "4"}, "score": {"nullValue": None}}}
        pages = [{"documents": [doc("first")], "nextPageToken": "page-two"}, {"documents": [doc("second")]}]
        with patch.object(asc, "read_json", side_effect=pages) as read:
            docs = asc.read_collection("teams")
            self.assertEqual([d["id"] for d in docs], ["first", "second"])
            self.assertEqual(docs[0]["slot"], 4)
            self.assertIsNone(docs[0]["score"])
            self.assertIn("pageToken=page-two", read.call_args.args[0])

    def test_outage_retains_cached_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "asc.json"
            cache.write_text(json.dumps(self.snapshot))
            before = cache.read_bytes()
            with patch.object(asc, "CACHE", cache), patch.object(asc, "fetch_published_data", side_effect=OSError("offline")):
                fixtures, debug = asc.refresh_asc_fixtures(ZoneInfo("Australia/Perth"))
            self.assertTrue(debug["used_cache"])
            self.assertEqual(len(fixtures), 2)
            self.assertEqual(cache.read_bytes(), before)

    def test_unpublished_or_wrong_tournament_is_rejected(self):
        with self.assertRaises(ValueError):
            asc.prepare_snapshot(dict(self.tournament, showSchedule=False), self.data)
        with self.assertRaises(ValueError):
            asc.prepare_snapshot(dict(self.tournament, id="another-event"), self.data)


if __name__ == "__main__":
    unittest.main()
