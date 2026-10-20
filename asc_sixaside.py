"""Finn's 6 Shooters fixtures from the public ASC Tournify live site."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# The public live app reads these Firestore documents without authentication.
TOURNAMENT_ID = "VjYTtXxa2GoInl1lNlAF"
TEAM_ID = "XMDfpXDCfngJL2gmRPgR"
LIVE_LINK = "asc-6-a-side"
SOURCE_URL = f"https://tournifyapp.com/live/{LIVE_LINK}/team/{TEAM_ID}"
API_ROOT = (
    "https://firestore.googleapis.com/v1/projects/tournamentsoftware-a1b3d"
    f"/databases/(default)/documents/tournaments/{TOURNAMENT_ID}"
)
COLLECTIONS = ("teams", "matches", "days", "divisions", "poules", "sportParks")
CACHE = Path(__file__).resolve().parent / "docs" / "asc_sixaside.json"


def firestore_value(value: dict[str, Any]) -> Any:
    if "mapValue" in value:
        return {k: firestore_value(v) for k, v in value["mapValue"].get("fields", {}).items()}
    if "arrayValue" in value:
        return [firestore_value(v) for v in value["arrayValue"].get("values", [])]
    if "integerValue" in value:
        return int(value["integerValue"])
    for kind in ("stringValue", "doubleValue", "booleanValue", "timestampValue"):
        if kind in value:
            return value[kind]
    if "nullValue" in value:
        return None
    raise ValueError("Unexpected Tournify field type")


def firestore_document(document: dict[str, Any]) -> dict[str, Any]:
    name = str(document.get("name") or "")
    if not name or not isinstance(document.get("fields"), dict):
        raise ValueError("Invalid Tournify document")
    return {**{k: firestore_value(v) for k, v in document["fields"].items()}, "id": name.rsplit("/", 1)[-1]}


def read_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Finn-Tate-Sports-Calendar/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def read_collection(collection: str) -> list[dict[str, Any]]:
    documents = []
    seen_tokens = set()
    token = ""
    while True:
        params = {"pageSize": "1000"}
        if token:
            params["pageToken"] = token
        payload = read_json(API_ROOT + "/" + collection + "?" + urlencode(params))
        if not isinstance(payload, dict) or not isinstance(payload.get("documents", []), list):
            raise ValueError(f"Invalid Tournify {collection} response")
        documents.extend(firestore_document(d) for d in payload.get("documents", []))
        token = payload.get("nextPageToken", "")
        if not token:
            return documents
        if token in seen_tokens:
            raise ValueError("Repeated Tournify pagination token")
        seen_tokens.add(token)


def fetch_published_data() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    with ThreadPoolExecutor(max_workers=7) as executor:
        tournament_future = executor.submit(read_json, API_ROOT)
        collections = list(executor.map(read_collection, COLLECTIONS))
        tournament = firestore_document(tournament_future.result())
    return tournament, dict(zip(COLLECTIONS, collections))


def score_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError("Invalid Tournify match score")
    return str(value)


def prepare_snapshot(tournament: dict[str, Any], data: dict[str, list[dict[str, Any]]],
                     previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve Tournify's pool slots to team IDs, then retain only Finn's games."""
    if tournament.get("id") != TOURNAMENT_ID or tournament.get("liveLink") != LIVE_LINK:
        raise ValueError("Unexpected ASC tournament")
    if tournament.get("timezone") != "Australia/Perth" or tournament.get("showSchedule") is not True:
        raise ValueError("The ASC draw is unavailable or has an unexpected timezone")
    timezone = ZoneInfo("Australia/Perth")
    teams = {t["id"]: t for t in data["teams"]}
    target = teams.get(TEAM_ID)
    if not target or not str(target.get("name") or "").strip():
        raise ValueError("6 Shooters' team ID is missing from the published draw")
    division = next((d for d in data["divisions"] if d["id"] == target.get("division")), None)
    if not division:
        raise ValueError("6 Shooters' division is missing")
    pools = {p["id"]: p for p in data["poules"]}
    days = {d["id"]: d for d in data["days"]}
    parks = {p["id"]: p for p in data["sportParks"]}
    slots = {}
    for team in teams.values():
        for key, pool_id in team.items():
            if not key.startswith("poule") or not isinstance(pool_id, str):
                continue
            slot = team.get("numInPoule" + key[len("poule"):])
            if type(slot) is not int:
                continue
            identity = (pool_id, slot)
            if identity in slots and slots[identity]["id"] != team["id"]:
                raise ValueError("Ambiguous team assignment in the ASC draw")
            slots[identity] = team
    fixtures = []
    used_ids = set()
    for match in data["matches"]:
        pool = pools.get(match.get("poule"))
        if not pool or pool.get("division") != target["division"]:
            continue
        home = slots.get((pool["id"], match.get("team1")))
        away = slots.get((pool["id"], match.get("team2")))
        if TEAM_ID not in ((home or {}).get("id"), (away or {}).get("id")):
            continue
        if any(str((t or {}).get("name", "")).strip().casefold() == "bye" for t in (home, away)):
            continue
        match_id = str(match.get("id") or "")
        if not match_id or match_id in used_ids:
            raise ValueError("Duplicate or missing ASC fixture ID")
        used_ids.add(match_id)
        day_id = str(match.get("day", "0"))
        day = tournament if day_id == "0" else days.get(day_id)
        if not day or not isinstance(day.get("date"), (int, float)):
            raise ValueError("An ASC fixture has no published date")
        date = datetime.fromtimestamp(day["date"], timezone).date()
        time = str(match.get("st", match.get("startTime", "")) or "").strip()
        start = datetime.combine(date, datetime.strptime(time, "%H:%M").time() if time else datetime.min.time(), timezone)
        end_time = str(match.get("et", match.get("endTime", "")) or "").strip()
        if time and end_time:
            end = datetime.combine(date, datetime.strptime(end_time, "%H:%M").time(), timezone)
            if end <= start:
                end += timedelta(days=1)
            duration = int((end - start).total_seconds() / 60)
        else:
            custom = tournament.get("customMatchDuration", {})
            duration = int(match.get("duration") or custom.get(pool["id"]) or custom.get(pool["division"]) or tournament["matchDuration"])
        if not 0 < duration <= 180:
            raise ValueError("Unexpected ASC match duration")
        field = (tournament.get("fields") or {}).get(str(match.get("field")), {})
        park = parks.get(str(field.get("sportPark", "0")), {})
        venue = str(park.get("name") or "").strip()
        if not venue:
            raise ValueError("An ASC fixture has no published venue")
        home_name = str((home or {}).get("name") or "Opponent TBC").strip()
        away_name = str((away or {}).get("name") or "Opponent TBC").strip()
        if pool.get("singleMatch"):
            round_name = str(pool.get("name") or "Finals")
        else:
            round_name = str(int(match["round"]) + 1)
        seed = f"tournify-asc|{TOURNAMENT_ID}|{TEAM_ID}|{match_id}"
        uid = hashlib.sha256(seed.encode()).hexdigest()[:24] + "@family-soccer-calendar"
        fixtures.append({
            "label": "Finn", "source_id": match_id, "uid": uid,
            "source_type": "tournify_asc_sixaside", "source_url": SOURCE_URL,
            "start": start.isoformat(), "home": home_name, "away": away_name,
            "venue": venue, "field": str(field.get("name") or "Pitch TBC"),
            "round": round_name, "sport_icon": "⚽", "sport_name": "ASC 6-a-side Soccer",
            "display_title": f"{home_name} vs {away_name} — ASC 6-a-side",
            "time_label": "KO", "all_day": not bool(time),
            "duration_minutes": duration, "reminder_minutes": 90 if time else 0,
            "status": "CONFIRMED" if time and home and away else "TENTATIVE",
            "home_score": score_text(match.get("score1")), "away_score": score_text(match.get("score2")),
            "notes": "",
        })
    if not fixtures:
        raise ValueError("The public ASC draw contains no assigned 6 Shooters fixtures")
    current_ids = {f["uid"] for f in fixtures}
    for old in (previous or {}).get("fixtures", []):
        if old["uid"] not in current_ids:
            fixtures.append(dict(old, status="CANCELLED"))
    # Do not publish sign-up details, contacts, player lists or polling timestamps.
    return {
        "schema_version": 1, "tournament_id": TOURNAMENT_ID, "team_id": TEAM_ID,
        "tournament": str(tournament.get("name") or "Armadale SC Summer 6-a-Side"),
        "team_name": target["name"].strip(), "division": division["name"],
        "timezone": "Australia/Perth", "source_url": SOURCE_URL,
        "fixtures": sorted(fixtures, key=lambda f: (f["start"], f["uid"])),
    }


def parse_asc_fixtures(snapshot: dict[str, Any], timezone: ZoneInfo) -> list[dict[str, Any]]:
    if (snapshot.get("schema_version") != 1 or snapshot.get("team_id") != TEAM_ID
            or snapshot.get("tournament_id") != TOURNAMENT_ID or snapshot.get("timezone") != "Australia/Perth"):
        raise ValueError("Invalid cached ASC draw")
    fixtures = []
    used_uids = set()
    for record in snapshot["fixtures"]:
        fixture = dict(record)
        if not fixture.get("uid") or fixture["uid"] in used_uids:
            raise ValueError("Invalid cached ASC calendar identity")
        used_uids.add(fixture["uid"])
        fixture["start"] = datetime.fromisoformat(record["start"]).astimezone(timezone)
        fixtures.append(fixture)
    return fixtures


def refresh_asc_fixtures(timezone: ZoneInfo) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    previous = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else None
    warning = ""
    try:
        tournament, data = fetch_published_data()
        snapshot = prepare_snapshot(tournament, data, previous)
        fixtures = parse_asc_fixtures(snapshot, timezone)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        if previous is None:
            raise
        warning = str(exc)
        print(f"ASC 6-a-side warning: {warning}; using the published cache.")
        fixtures = parse_asc_fixtures(previous, timezone)
    return fixtures, {"source": SOURCE_URL, "team_id": TEAM_ID, "fixture_count": len(fixtures),
                      "used_cache": bool(warning), "warning": warning}
