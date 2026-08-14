from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
OUTPUT = ROOT / "docs" / "fixtures.ics"
DEBUG = ROOT / "docs" / "debug.json"
MANUAL_FIXTURES = ROOT / "manual_fixtures.json"
SOFTBALL_DATA = ROOT / "docs" / "softball.json"
SOCCER_LADDER_DATA = ROOT / "docs" / "soccer_ladders.json"
LADDER_PARSER_VERSION = "2026-08-09-v5-flat-row-regex"

SCHOOL_CALENDAR_PAGE_URL = "https://www.stjohnbosco.wa.edu.au/calendar/"
SCHOOL_TEAMUP_URL = (
    "https://teamup.com/ksmxivsndu1tq6ng17"
    "?view=a"
    "&showAgendaDateRange=year"
    "&showAgendaDetails=1"
    "&showAgendaHeader=1"
    "&showProfileAndInfo=0"
    "&showSidepanel=0"
)
SCHOOL_CALENDAR_URL = SCHOOL_TEAMUP_URL
SCHOOL_SOCCER_MATCH_TEXT = "ACC soccer Y10-12 boys"
SCHOOL_SOCCER_SCRAPER_VERSION = "2026-08-14-v2-flexible-title-match"

SOCCER_LADDERS = [
    {
        "player": "Finn",
        "division": "U14 JDL D2",
        "target_team": "Armadale SC - U14 JDL D2",
        "url": (
            "https://registration.squadi.com/livescorePublicLadder"
            "?organisationKey=f524913b-317c-4011-8f66-e4eb3f101ebe"
            "&yearId=8"
            "&competitionUniqueKey=2929eee2-4f37-46f3-a6d6-123acee5443f"
            "&divisionId=10370"
            "&teamId=-1"
        ),
    },
    {
        "player": "Tate",
        "division": "U13 JCL SD1",
        "target_team": "Armadale SC - U13 JCL SD1",
        # The supplied Squadi URL was the Draws/Fixtures view.  The ladder
        # uses the same competition/division identifiers with the public
        # ladder route.
        "fixture_reference_url": (
            "https://registration.squadi.com/livescoreSeasonFixture"
            "?organisationKey=f524913b-317c-4011-8f66-e4eb3f101ebe"
            "&yearId=8"
            "&competitionUniqueKey=fafe940b-0a16-474a-9ac8-9dbf00035b0c"
            "&divisionId=10761"
            "&teamId=-1"
        ),
        "url": (
            "https://registration.squadi.com/livescorePublicLadder"
            "?organisationKey=f524913b-317c-4011-8f66-e4eb3f101ebe"
            "&yearId=8"
            "&competitionUniqueKey=fafe940b-0a16-474a-9ac8-9dbf00035b0c"
            "&divisionId=10761"
            "&teamId=-1"
        ),
    },
]

DDMSA_RESULTS_URL = "https://ddmsa.com/resframe.htm"
DDMSA_HOME_URL = "https://ddmsa.com/"
DDMSA_TEAM = "Thornlie Hawks (Blue)"
DDMSA_DIVISION = "Under 13's Mixed"

DATE_KEYS = (
    "fixtureDate",
    "matchDate",
    "gameDate",
    "startDate",
    "startDateTime",
    "dateTime",
    "startTime",
    "scheduledDate",
    "date",
)

HOME_KEYS = (
    "homeTeamName",
    "homeTeam",
    "team1Name",
    "homeName",
)

AWAY_KEYS = (
    "awayTeamName",
    "awayTeam",
    "team2Name",
    "awayName",
)

VENUE_KEYS = (
    "venueName",
    "venue",
    "groundName",
    "locationName",
    "ground",
    "venueCourtName",
    "venueCourt",
    "subVenueName",
    "courtVenueName",
)

FIELD_KEYS = (
    "fieldName",
    "courtName",
    "pitchName",
    "field",
    "court",
    "pitch",
    "venueCourtName",
    "subVenueName",
)

ROUND_KEYS = (
    "roundName",
    "round",
    "roundNumber",
    "fixtureRound",
)

ID_KEYS = (
    "matchId",
    "fixtureId",
    "gameId",
    "uniqueKey",
    "id",
)

HOME_SCORE_KEYS = (
    "homeScore",
    "homeTeamScore",
    "homeGoals",
    "homeTeamGoals",
    "homePoints",
    "homeTeamPoints",
    "team1Score",
    "teamOneScore",
    "team1Goals",
    "team1Points",
    "scoreHome",
    "homeResult",
)

AWAY_SCORE_KEYS = (
    "awayScore",
    "awayTeamScore",
    "awayGoals",
    "awayTeamGoals",
    "awayPoints",
    "awayTeamPoints",
    "team2Score",
    "teamTwoScore",
    "team2Goals",
    "team2Points",
    "scoreAway",
    "awayResult",
)

NESTED_SCORE_KEYS = (
    "score",
    "goals",
    "points",
    "result",
    "total",
    "value",
)

LATITUDE_KEYS = (
    "latitude",
    "lat",
    "venueLatitude",
    "venueLat",
    "locationLatitude",
    "locationLat",
    "groundLatitude",
    "groundLat",
    "courtLatitude",
    "courtLat",
    "mapLatitude",
    "geoLatitude",
)

LONGITUDE_KEYS = (
    "longitude",
    "lng",
    "lon",
    "long",
    "venueLongitude",
    "venueLng",
    "venueLon",
    "locationLongitude",
    "locationLng",
    "locationLon",
    "groundLongitude",
    "groundLng",
    "courtLongitude",
    "courtLng",
    "mapLongitude",
    "geoLongitude",
)

COORDINATE_REFERENCE_KEYS = (
    "id",
    "venueId",
    "venueCourtId",
    "courtId",
    "groundId",
    "locationId",
    "facilityId",
    "subVenueId",
    "matchVenueId",
)

VENUE_REFERENCE_KEYS = (
    "venueId",
    "venueCourtId",
    "courtId",
    "groundId",
    "locationId",
    "facilityId",
    "subVenueId",
    "matchVenueId",
)

VENUE_WORDS = re.compile(
    r"\b("
    r"reserve|oval|stadium|park|ground|sports|complex|arena|"
    r"centre|center"
    r")\b",
    re.IGNORECASE,
)

SURFACE_WORDS = re.compile(
    r"\b(pitch|field|court)\b",
    re.IGNORECASE,
)


def clean(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, dict):
        for key in (
            "name",
            "displayName",
            "teamName",
            "title",
            "label",
            "value",
            "venueName",
            "courtName",
        ):
            if key in value and value[key] not in (None, ""):
                return clean(value[key])
        return ""

    if isinstance(value, list):
        return ", ".join(filter(None, (clean(item) for item in value)))

    return re.sub(r"\s+", " ", str(value)).strip()


def first(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lower = {str(key).lower(): value for key, value in obj.items()}

    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]

        value = lower.get(key.lower())
        if value not in (None, ""):
            return value

    return None


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, timezone)

        text = clean(value)
        if not text:
            return None

        # Squadi supplies dates in month/day/year order.
        parsed = dateparser.parse(text, dayfirst=False)
        if not parsed:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)

        return parsed.astimezone(timezone)
    except (TypeError, ValueError, OverflowError):
        return None


def normalise_location(location: str) -> str:
    location = clean(location).replace("\xa0", " ")

    location = re.sub(
        r"\s*[-–—]\s*(Field|Pitch|Court)\s*",
        r" — \1 ",
        location,
        flags=re.IGNORECASE,
    )

    return re.sub(r"\s+", " ", location).strip(" -–—")


def is_invalid_location(candidate: str) -> bool:
    if not candidate:
        return True

    if candidate.lower() == "match centre":
        return True

    if candidate.startswith(("Round ", "Match ID:", "Age Group:")):
        return True

    if candidate in {"-", "Bye", "B"}:
        return True

    if re.fullmatch(r"\d+\s*:\s*\d+", candidate):
        return True

    if re.search(
        r"\b(?:AM|PM|AWST|AEST|ACST)\b",
        candidate,
        re.IGNORECASE,
    ):
        return True

    return False


def locations_from_page_text(body_text: str) -> dict[str, str]:
    """Match each Squadi Match ID to the full venue shown on its card."""

    lines = [
        line.strip().replace("\xa0", " ")
        for line in body_text.splitlines()
        if line.strip()
    ]

    locations: dict[str, str] = {}

    for index, line in enumerate(lines):
        match = re.fullmatch(r"Match ID:\s*(\d+)", line)
        if not match:
            continue

        match_id = match.group(1)
        window = lines[max(0, index - 20) : index]
        full_venue = ""
        surface_only = ""

        for raw_candidate in reversed(window):
            candidate = normalise_location(raw_candidate)
            if is_invalid_location(candidate):
                continue

            if VENUE_WORDS.search(candidate):
                full_venue = candidate
                break

            if not surface_only and SURFACE_WORDS.search(candidate):
                surface_only = candidate

        location = full_venue or surface_only
        if location:
            locations[match_id] = location

    return locations


def to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None

    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def valid_coordinates(
    latitude: float | None,
    longitude: float | None,
) -> tuple[float, float] | None:
    if latitude is None or longitude is None:
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    # A zero/zero point is normally a missing-value placeholder.
    if latitude == 0 and longitude == 0:
        return None

    return latitude, longitude


def coordinates_from_text(text: str) -> tuple[float, float] | None:
    if not text:
        return None

    decoded = unquote(str(text)).replace("+", " ")

    patterns = (
        r"(?:^|[?&])(?:ll|query|destination|daddr)=\s*"
        r"(-?\d{1,3}(?:\.\d+)?)\s*,\s*"
        r"(-?\d{1,3}(?:\.\d+)?)",
        r"@\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*"
        r"(-?\d{1,3}(?:\.\d+)?)",
        r"geo:\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*"
        r"(-?\d{1,3}(?:\.\d+)?)",
        r"(?:lat|latitude)[\"']?\s*[:=]\s*"
        r"(-?\d{1,3}(?:\.\d+)?).*?"
        r"(?:lng|lon|longitude)[\"']?\s*[:=]\s*"
        r"(-?\d{1,3}(?:\.\d+)?)",
        r"(?:lng|lon|longitude)[\"']?\s*[:=]\s*"
        r"(-?\d{1,3}(?:\.\d+)?).*?"
        r"(?:lat|latitude)[\"']?\s*[:=]\s*"
        r"(-?\d{1,3}(?:\.\d+)?)",
    )

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, decoded, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue

        first_value = to_float(match.group(1))
        second_value = to_float(match.group(2))

        # The final pattern is longitude first, latitude second.
        if index == len(patterns) - 1:
            coordinates = valid_coordinates(second_value, first_value)
        else:
            coordinates = valid_coordinates(first_value, second_value)

        if coordinates:
            return coordinates

    return None


def extract_coordinates(value: Any) -> tuple[float, float] | None:
    """Find latitude and longitude in nested Squadi JSON or map URLs."""

    if isinstance(value, str):
        return coordinates_from_text(value)

    if isinstance(value, dict):
        lower = {str(key).lower(): item for key, item in value.items()}

        latitude = None
        longitude = None

        for key in LATITUDE_KEYS:
            if key.lower() in lower:
                latitude = to_float(lower[key.lower()])
                if latitude is not None:
                    break

        for key in LONGITUDE_KEYS:
            if key.lower() in lower:
                longitude = to_float(lower[key.lower()])
                if longitude is not None:
                    break

        coordinates = valid_coordinates(latitude, longitude)
        if coordinates:
            return coordinates

        # Support GeoJSON-like arrays. Perth's longitude is over 90, which
        # lets us safely determine whether the array is [lng, lat] or [lat, lng].
        raw_coordinates = lower.get("coordinates")
        if isinstance(raw_coordinates, (list, tuple)) and len(raw_coordinates) >= 2:
            first_value = to_float(raw_coordinates[0])
            second_value = to_float(raw_coordinates[1])

            if first_value is not None and second_value is not None:
                if abs(first_value) > 90 and abs(second_value) <= 90:
                    coordinates = valid_coordinates(second_value, first_value)
                elif abs(second_value) > 90 and abs(first_value) <= 90:
                    coordinates = valid_coordinates(first_value, second_value)
                else:
                    coordinates = valid_coordinates(first_value, second_value)

                if coordinates:
                    return coordinates

        for child in value.values():
            coordinates = extract_coordinates(child)
            if coordinates:
                return coordinates

    elif isinstance(value, list):
        for child in value:
            coordinates = extract_coordinates(child)
            if coordinates:
                return coordinates

    return None


def identifier_values(
    obj: dict[str, Any],
    keys: tuple[str, ...],
) -> set[str]:
    lower = {str(key).lower(): value for key, value in obj.items()}
    identifiers: set[str] = set()

    for key in keys:
        value = lower.get(key.lower())
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            identifier = clean(value)
            if identifier:
                identifiers.add(identifier)

    return identifiers


def build_coordinate_index(payloads: list[Any]) -> dict[str, tuple[float, float]]:
    """Index coordinate-bearing venue records by their IDs."""

    coordinate_index: dict[str, tuple[float, float]] = {}

    for payload in payloads:
        for obj in walk(payload):
            coordinates = extract_coordinates(obj)
            if not coordinates:
                continue

            for identifier in identifier_values(obj, COORDINATE_REFERENCE_KEYS):
                coordinate_index[identifier] = coordinates

    return coordinate_index


def fixture_reference_ids(obj: dict[str, Any]) -> set[str]:
    """Collect venue/court/location IDs referenced by a match object."""

    references: set[str] = set()

    for nested in walk(obj):
        references.update(identifier_values(nested, VENUE_REFERENCE_KEYS))

        for container_key in ("venue", "court", "ground", "location", "facility"):
            container = nested.get(container_key)
            if isinstance(container, dict):
                references.update(identifier_values(container, COORDINATE_REFERENCE_KEYS))

    return references


async def coordinates_from_page(page) -> dict[str, tuple[float, float]]:
    """Read coordinates from map links/data attributes near each Match ID."""

    raw_result = await page.evaluate(
        r"""
        () => {
          const result = {};

          function valid(lat, lng) {
            return Number.isFinite(lat) && Number.isFinite(lng) &&
              lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180 &&
              !(lat === 0 && lng === 0);
          }

          function parseCoordinates(raw) {
            if (!raw) return null;

            let text = String(raw);
            try {
              text = decodeURIComponent(text.replace(/\+/g, ' '));
            } catch (_) {}

            const patterns = [
              /(?:^|[?&])(?:ll|query|destination|daddr)=\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)/i,
              /@\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)/i,
              /geo:\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)/i,
              /(?:lat|latitude)["']?\s*[:=]\s*(-?\d{1,3}(?:\.\d+)?).*?(?:lng|lon|longitude)["']?\s*[:=]\s*(-?\d{1,3}(?:\.\d+)?)/is,
            ];

            for (const pattern of patterns) {
              const match = text.match(pattern);
              if (!match) continue;

              const lat = Number(match[1]);
              const lng = Number(match[2]);
              if (valid(lat, lng)) return [lat, lng];
            }

            const reverse = text.match(
              /(?:lng|lon|longitude)["']?\s*[:=]\s*(-?\d{1,3}(?:\.\d+)?).*?(?:lat|latitude)["']?\s*[:=]\s*(-?\d{1,3}(?:\.\d+)?)/is
            );

            if (reverse) {
              const lng = Number(reverse[1]);
              const lat = Number(reverse[2]);
              if (valid(lat, lng)) return [lat, lng];
            }

            return null;
          }

          const selector = [
            'a[href]',
            '[onclick]',
            '[data-lat]',
            '[data-lng]',
            '[data-latitude]',
            '[data-longitude]',
            '[data-location]',
            '[data-map]'
          ].join(',');

          for (const node of document.querySelectorAll(selector)) {
            const attributes = Array.from(node.attributes || [])
              .map(attribute => `${attribute.name}=${attribute.value}`)
              .join(' ');

            const coordinates = parseCoordinates(attributes);
            if (!coordinates) continue;

            let ancestor = node;
            for (let level = 0; ancestor && level < 10; level += 1) {
              const text = ancestor.innerText || ancestor.textContent || '';
              const matches = [...text.matchAll(/Match ID:\s*(\d+)/g)];

              if (matches.length === 1) {
                result[matches[0][1]] = coordinates;
                break;
              }

              ancestor = ancestor.parentElement;
            }
          }

          return result;
        }
        """
    )

    result: dict[str, tuple[float, float]] = {}

    if isinstance(raw_result, dict):
        for match_id, values in raw_result.items():
            if not isinstance(values, list) or len(values) < 2:
                continue

            coordinates = valid_coordinates(
                to_float(values[0]),
                to_float(values[1]),
            )
            if coordinates:
                result[str(match_id)] = coordinates

    return result


def escape_ics(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def fold_ics_line(line: str) -> str:
    if len(line) <= 73:
        return line

    parts = [line[:73]]
    remaining = line[73:]

    while remaining:
        parts.append(" " + remaining[:72])
        remaining = remaining[72:]

    return "\r\n".join(parts)


def waze_url(
    location: str,
    latitude: float | None,
    longitude: float | None,
) -> str:
    coordinates = valid_coordinates(latitude, longitude)

    if coordinates:
        lat, lng = coordinates
        return (
            "https://waze.com/ul?"
            f"ll={lat:.6f}%2C{lng:.6f}&navigate=yes"
        )

    if not location:
        return ""

    # Coordinate fallback: search for the reserve rather than a specific pitch.
    reserve_name = re.sub(
        r"\s*[-–—]\s*(Pitch|Field|Court|Diamond)\b.*$",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip()

    query = quote_plus(f"{reserve_name or location}, Western Australia")
    return f"https://waze.com/ul?q={query}&navigate=yes"


def competition_details(
    team: dict[str, Any],
    responses: list[dict[str, Any]],
) -> tuple[str, str]:
    competition_id = clean(team.get("competition_id"))
    competition_key = clean(team.get("competition_unique_key"))

    if not competition_key:
        team_query = parse_qs(urlparse(team["url"]).query)
        competition_key = clean(team_query.get("competitionUniqueKey", [""])[0])

    if not competition_id:
        for response in responses:
            response_query = parse_qs(urlparse(response.get("url", "")).query)
            possible_id = clean(response_query.get("competitionId", [""])[0])
            if possible_id and possible_id.isdigit():
                competition_id = possible_id
                break

    return competition_id, competition_key


def squadi_match_url(
    team: dict[str, Any],
    match_id: str,
    competition_id: str,
    competition_key: str,
) -> str:
    if not match_id or not competition_id or not competition_key:
        return team["url"]

    return (
        "https://registration.squadi.com/matchSummary"
        f"?matchId={match_id}"
        f"&competitionId={competition_id}"
        f"&competitionUniqueKey={competition_key}"
    )


def short_team_name(team: str) -> str:
    team = clean(team)

    team = re.sub(
        r"\s*-\s*U\d+.*$",
        "",
        team,
        flags=re.IGNORECASE,
    )

    team = re.sub(
        r"\s+(SC|FC)$",
        "",
        team,
        flags=re.IGNORECASE,
    )

    return team.strip()


def format_round_text(round_value: str) -> str:
    round_text = clean(round_value)

    round_text = re.sub(
        r"^(?:round\s*:?\s*)+",
        "",
        round_text,
        flags=re.IGNORECASE,
    ).strip()

    return f"Round {round_text}" if round_text else ""


def format_kickoff_time(start: datetime) -> str:
    return start.strftime("%I:%M%p").lstrip("0").lower()


def normalise_score(value: Any) -> str:
    """Return a clean numeric score, or an empty string when unavailable."""
    if value is None or isinstance(value, bool):
        return ""

    if isinstance(value, dict):
        return normalise_score(first(value, NESTED_SCORE_KEYS))

    if isinstance(value, (int, float)):
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(numeric)

    text = clean(value)

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        numeric = float(text)
        return str(int(numeric)) if numeric.is_integer() else text

    return ""


def extract_score_pair(obj: dict[str, Any]) -> tuple[str, str]:
    """
    Extract home and away scores from Squadi's match JSON.

    Squadi has used several score field names across endpoints, so this
    checks direct score fields and common nested result containers.
    """
    home_score = normalise_score(first(obj, HOME_SCORE_KEYS))
    away_score = normalise_score(first(obj, AWAY_SCORE_KEYS))

    if home_score and away_score:
        return home_score, away_score

    lower = {str(key).lower(): value for key, value in obj.items()}

    for home_key, away_key in (
        ("hometeam", "awayteam"),
        ("home", "away"),
        ("team1", "team2"),
        ("teamone", "teamtwo"),
    ):
        home_container = lower.get(home_key)
        away_container = lower.get(away_key)

        if isinstance(home_container, dict) and isinstance(away_container, dict):
            home_score = normalise_score(
                first(home_container, NESTED_SCORE_KEYS)
            )
            away_score = normalise_score(
                first(away_container, NESTED_SCORE_KEYS)
            )

            if home_score and away_score:
                return home_score, away_score

    for result_key in ("score", "scores", "result", "matchresult", "finalscore"):
        result_container = lower.get(result_key)

        if not isinstance(result_container, dict):
            continue

        home_score = normalise_score(first(result_container, HOME_SCORE_KEYS))
        away_score = normalise_score(first(result_container, AWAY_SCORE_KEYS))

        if not home_score:
            home_score = normalise_score(
                first(result_container, ("home", "team1", "teamOne"))
            )

        if not away_score:
            away_score = normalise_score(
                first(result_container, ("away", "team2", "teamTwo"))
            )

        if home_score and away_score:
            return home_score, away_score

    return "", ""




LADDER_TEAM_KEYS = (
    "teamName",
    "teamDisplayName",
    "displayTeamName",
    "clubTeamName",
    "clubName",
    "entityName",
)

LADDER_POSITION_KEYS = (
    "position",
    "rank",
    "ladderPosition",
    "standingPosition",
    "place",
)

LADDER_PLAYED_KEYS = (
    "played",
    "gamesPlayed",
    "matchesPlayed",
    "playedCount",
    "gameCount",
)

LADDER_WON_KEYS = (
    "won",
    "wins",
    "gamesWon",
    "matchesWon",
    "winCount",
)

LADDER_DRAWN_KEYS = (
    "drawn",
    "draws",
    "gamesDrawn",
    "matchesDrawn",
    "drawCount",
)

LADDER_LOST_KEYS = (
    "lost",
    "losses",
    "gamesLost",
    "matchesLost",
    "lossCount",
)

LADDER_FOR_KEYS = (
    "goalsFor",
    "pointsFor",
    "for",
    "scoreFor",
    "totalFor",
)

LADDER_AGAINST_KEYS = (
    "goalsAgainst",
    "pointsAgainst",
    "against",
    "scoreAgainst",
    "totalAgainst",
)

LADDER_DIFFERENCE_KEYS = (
    "goalDifference",
    "pointsDifference",
    "difference",
    "diff",
)

LADDER_POINTS_KEYS = (
    "points",
    "totalPoints",
    "ladderPoints",
    "competitionPoints",
    "premiershipPoints",
)

LADDER_PERCENTAGE_KEYS = (
    "percentage",
    "percent",
    "ratio",
    "forAgainstPercentage",
)


def ladder_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = clean(value)
    match = re.fullmatch(r"-?\d+(?:\.0+)?", text)

    if not match:
        return None

    return int(float(text))


def nested_first(
    obj: Any,
    keys: tuple[str, ...],
    max_depth: int = 4,
) -> Any:
    """Find one of the named keys inside a small nested Squadi object."""
    wanted = {key.lower() for key in keys}
    queue: list[tuple[Any, int]] = [(obj, 0)]

    while queue:
        value, depth = queue.pop(0)

        if depth > max_depth:
            continue

        if isinstance(value, dict):
            lower = {
                str(key).lower(): item
                for key, item in value.items()
            }

            for key in wanted:
                if key in lower and lower[key] not in (None, ""):
                    return lower[key]

            for child in value.values():
                if isinstance(child, (dict, list)):
                    queue.append((child, depth + 1))

        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    queue.append((child, depth + 1))

    return None


def ladder_team_name(obj: dict[str, Any]) -> str:
    direct = clean(first(obj, LADDER_TEAM_KEYS))
    if direct:
        return direct

    for container_key in (
        "team",
        "teamDetail",
        "teamDetails",
        "participant",
        "club",
    ):
        container = obj.get(container_key)

        if isinstance(container, dict):
            name = clean(
                first(
                    container,
                    (
                        "teamName",
                        "displayName",
                        "name",
                        "clubName",
                    ),
                )
            )

            if name:
                return name

    return ""


def ladder_stat(
    obj: dict[str, Any],
    keys: tuple[str, ...],
) -> int | None:
    value = first(obj, keys)

    if value in (None, ""):
        value = nested_first(obj, keys, max_depth=3)

    return ladder_int(value)


def ladder_percentage(
    obj: dict[str, Any],
) -> str:
    value = first(obj, LADDER_PERCENTAGE_KEYS)

    if value in (None, ""):
        value = nested_first(
            obj,
            LADDER_PERCENTAGE_KEYS,
            max_depth=3,
        )

    return clean(value)


def parse_squadi_ladder_payloads(
    payloads: list[Any],
) -> list[dict[str, Any]]:
    """Extract ladder rows from any JSON payload returned by Squadi."""
    candidates: dict[str, dict[str, Any]] = {}

    for payload in payloads:
        for obj in walk(payload):
            if not isinstance(obj, dict):
                continue

            team = ladder_team_name(obj)

            if not team or len(team) > 120:
                continue

            played = ladder_stat(obj, LADDER_PLAYED_KEYS)
            won = ladder_stat(obj, LADDER_WON_KEYS)
            drawn = ladder_stat(obj, LADDER_DRAWN_KEYS)
            lost = ladder_stat(obj, LADDER_LOST_KEYS)
            goals_for = ladder_stat(obj, LADDER_FOR_KEYS)
            goals_against = ladder_stat(obj, LADDER_AGAINST_KEYS)
            difference = ladder_stat(obj, LADDER_DIFFERENCE_KEYS)
            points = ladder_stat(obj, LADDER_POINTS_KEYS)
            position = ladder_stat(obj, LADDER_POSITION_KEYS)

            values = (
                played,
                won,
                drawn,
                lost,
                goals_for,
                goals_against,
                difference,
                points,
                position,
            )

            # Fixture objects also contain team names. Require enough
            # ladder-style statistics to prevent false positives.
            completeness = sum(
                value is not None
                for value in values
            )

            if played is None or completeness < 4:
                continue

            if difference is None and (
                goals_for is not None
                and goals_against is not None
            ):
                difference = goals_for - goals_against

            row = {
                "position": position,
                "team": team,
                "played": played,
                "won": won,
                "drawn": drawn,
                "lost": lost,
                "for": goals_for,
                "against": goals_against,
                "difference": difference,
                "points": points,
                "percentage": ladder_percentage(obj),
            }

            key = re.sub(
                r"[^a-z0-9]+",
                "",
                team.lower(),
            )

            current = candidates.get(key)

            if (
                current is None
                or sum(
                    value not in (None, "")
                    for value in row.values()
                )
                > sum(
                    value not in (None, "")
                    for value in current.values()
                )
            ):
                candidates[key] = row

    rows = list(candidates.values())

    if any(row.get("position") is not None for row in rows):
        rows.sort(
            key=lambda row: (
                row.get("position")
                if row.get("position") is not None
                else 999
            )
        )
    else:
        rows.sort(
            key=lambda row: (
                -(row.get("points") or 0),
                -(row.get("difference") or 0),
                -(row.get("for") or 0),
                row.get("team", ""),
            )
        )

        for index, row in enumerate(rows, start=1):
            row["position"] = index

    return rows



def ladder_team_key(value: Any) -> str:
    """
    Compare Squadi team names while ignoring the repeated age/division
    suffix and punctuation.
    """
    name = clean(value)

    name = re.sub(
        r"\s*-\s*U\d+\s+.*$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    aliases = {
        "MUMFC": "Murdoch University Melville FC",
        "SPFC": "Sutherland Park FC",
        "LUFC": "Lynwood United FC",
    }

    name = aliases.get(name, name)

    return re.sub(
        r"[^a-z0-9]+",
        "",
        name.lower(),
    )


def ladder_rows_signature(
    rows: list[dict[str, Any]],
) -> str:
    """
    Produce a stable comparison value containing only real ladder data.

    Diagnostics and timestamps are deliberately excluded so a successful
    refresh does not cause a GitHub Pages deployment when the standings
    have not actually changed.
    """
    normalised = [
        {
            "position": row.get("position"),
            "team": clean(row.get("team")),
            "played": row.get("played"),
            "won": row.get("won"),
            "drawn": row.get("drawn"),
            "lost": row.get("lost"),
            "for": row.get("for"),
            "against": row.get("against"),
            "difference": row.get("difference"),
            "points": row.get("points"),
            "percentage": clean(row.get("percentage")),
        }
        for row in rows
    ]

    return json.dumps(
        normalised,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def ladder_target_summary(
    rows: list[dict[str, Any]],
    target_team: str,
) -> dict[str, Any] | None:
    target_key = ladder_team_key(target_team)

    return next(
        (
            row
            for row in rows
            if ladder_team_key(
                row.get("team")
            )
            == target_key
        ),
        None,
    )


def parse_squadi_ladder_body_text(
    body_text: str,
) -> list[dict[str, Any]]:
    """
    Parse Squadi's rendered ladder.

    Squadi renders the public ladder with divs rather than a normal HTML
    table.  In the rendered text each ladder row is:

      rank, team, MP, W, D, L, GF, GA, PTS, GD

    followed by up to five W/D/L form markers.

    This parser deliberately ignores the form markers and finds the next
    numeric rank, making it tolerant of tabs, blank lines and layout changes.
    """
    # Squadi renders each ladder row with a mixture of newlines and tabs.
    # The statistics can arrive as one tab-delimited line, so split on both
    # line breaks and tab characters before normalising each cell.
    raw_tokens = re.split(
        r"[\r\n\t]+",
        body_text,
    )

    lines: list[str] = []

    for raw_token in raw_tokens:
        token = clean(raw_token)

        if not token:
            continue

        # Depending on browser/rendering behaviour, Squadi may expose the
        # eight numerical ladder cells as either tab-delimited values or one
        # space-delimited string such as:
        #
        #   "3 3 0 0 6 1 9 5"
        #
        # Split only all-numeric runs; never split a team name on spaces.
        if re.fullmatch(
            r"-?\d+(?:\s+-?\d+)+",
            token,
        ):
            lines.extend(
                token.split()
            )
        else:
            lines.append(
                token
            )

    if not lines:
        return []

    # Start after Squadi's column headings if they are present.
    start_index = 0

    try:
        rank_index = next(
            index
            for index, line in enumerate(lines)
            if line.lower() == "rank"
        )

        for index in range(
            rank_index,
            min(len(lines), rank_index + 30),
        ):
            if lines[index].lower() == "next":
                start_index = index + 1
                break
        else:
            start_index = rank_index + 1

    except StopIteration:
        # The diagnostic preview can occasionally start partway through
        # the page.  In that case simply search from the beginning.
        start_index = 0

    rows: list[dict[str, Any]] = []
    index = start_index

    while index < len(lines):
        # Squadi's legend begins with "MP = Matches Played".
        if (
            lines[index].upper() == "MP"
            and index + 1 < len(lines)
            and lines[index + 1] == "="
        ):
            break

        if not re.fullmatch(r"\d{1,2}", lines[index]):
            index += 1
            continue

        position = int(lines[index])

        # A ladder rank is followed by a team name and eight numeric stats.
        if index + 9 >= len(lines):
            break

        team = lines[index + 1]

        # Do not mistake form/history numbers for ladder positions.
        if not re.search(
            r"(?:FC|SC|U\d+|Academy|SPFC|LUFC|MUMFC)",
            team,
            flags=re.IGNORECASE,
        ):
            index += 1
            continue

        values: list[int] = []
        cursor = index + 2

        while cursor < len(lines) and len(values) < 8:
            value = ladder_int(lines[cursor])

            if value is None:
                break

            values.append(value)
            cursor += 1

        if len(values) != 8:
            index += 1
            continue

        (
            played,
            won,
            drawn,
            lost,
            goals_for,
            goals_against,
            points,
            difference,
        ) = values

        rows.append(
            {
                "position": position,
                "team": team,
                "played": played,
                "won": won,
                "drawn": drawn,
                "lost": lost,
                "for": goals_for,
                "against": goals_against,
                "difference": difference,
                "points": points,
                "percentage": "",
            }
        )

        # Skip the W/D/L form markers.  The next iteration will find the
        # next numeric rank, regardless of how many form markers Squadi shows.
        index = cursor

    # Reject obvious false positives and keep only one row per rank.
    unique: dict[int, dict[str, Any]] = {}

    for row in rows:
        position = row["position"]

        if 1 <= position <= 50:
            unique[position] = row

    return [
        unique[position]
        for position in sorted(unique)
    ]


def repair_squadi_ladder_from_diagnostics(
    item: dict[str, Any],
) -> dict[str, Any]:
    """
    If a live ladder parse fails, try the rendered text saved in diagnostics.

    This is particularly useful after upgrading the parser: the repository
    already contains the complete Squadi ladder text from the previous run.
    """
    if item.get("rows"):
        return item

    diagnostic_sources = [
        item.get("diagnostics"),
        item.get("last_attempt_diagnostics"),
    ]

    for diagnostics in diagnostic_sources:
        if not isinstance(diagnostics, dict):
            continue

        # Preserve tabs/newlines in the saved page text. Flattening this
        # whitespace would merge the ladder statistics back together.
        preview = str(
            diagnostics.get(
                "body_text_preview"
            )
            or ""
        )

        if not preview.strip():
            continue

        rows = parse_squadi_ladder_body_text(
            preview
        )

        if not rows:
            continue

        target_key = re.sub(
            r"[^a-z0-9]+",
            "",
            clean(item.get("target_team")).lower(),
        )

        target_summary = next(
            (
                row
                for row in rows
                if re.sub(
                    r"[^a-z0-9]+",
                    "",
                    clean(row.get("team")).lower(),
                )
                == target_key
            ),
            None,
        )

        repaired = item.copy()
        repaired["rows"] = rows
        repaired["target_summary"] = target_summary
        repaired["status"] = "ok"
        repaired["diagnostics"] = {
            **diagnostics,
            "source": "rendered_text_repair",
        }
        repaired.pop("last_attempt_status", None)
        repaired.pop("last_attempt_diagnostics", None)

        return repaired

    return item


def parse_squadi_ladder_tables(
    raw_tables: list[list[list[str]]],
) -> list[dict[str, Any]]:
    """Fallback for Squadi versions that render an actual HTML table."""
    aliases = {
        "position": {"pos", "position", "rank", "#"},
        "team": {"team", "club"},
        "played": {"p", "pl", "played", "gp"},
        "won": {"w", "won", "wins"},
        "drawn": {"d", "draw", "drawn"},
        "lost": {"l", "lost", "loss"},
        "for": {"gf", "for", "f", "pf"},
        "against": {"ga", "against", "a", "pa"},
        "difference": {"gd", "diff", "difference"},
        "points": {"pts", "points", "pnts"},
    }

    best: list[dict[str, Any]] = []

    for table in raw_tables:
        if len(table) < 2:
            continue

        header_index = None
        mapping: dict[str, int] = {}

        for index, row in enumerate(table[:5]):
            cleaned = [
                re.sub(
                    r"[^a-z0-9#]+",
                    "",
                    clean(cell).lower(),
                )
                for cell in row
            ]

            candidate: dict[str, int] = {}

            for field, names in aliases.items():
                for cell_index, cell in enumerate(cleaned):
                    if cell in names:
                        candidate[field] = cell_index
                        break

            if (
                "team" in candidate
                and "played" in candidate
                and len(candidate) >= 4
            ):
                header_index = index
                mapping = candidate
                break

        if header_index is None:
            continue

        rows: list[dict[str, Any]] = []

        for raw_row in table[header_index + 1 :]:
            cells = [clean(cell) for cell in raw_row]

            if not cells:
                continue

            def cell(field: str) -> str:
                index = mapping.get(field)
                return (
                    cells[index]
                    if index is not None
                    and index < len(cells)
                    else ""
                )

            team = cell("team")

            if not team:
                continue

            row = {
                "position": ladder_int(cell("position")),
                "team": team,
                "played": ladder_int(cell("played")),
                "won": ladder_int(cell("won")),
                "drawn": ladder_int(cell("drawn")),
                "lost": ladder_int(cell("lost")),
                "for": ladder_int(cell("for")),
                "against": ladder_int(cell("against")),
                "difference": ladder_int(cell("difference")),
                "points": ladder_int(cell("points")),
                "percentage": "",
            }

            if row["played"] is not None:
                rows.append(row)

        if len(rows) > len(best):
            best = rows

    for index, row in enumerate(best, start=1):
        if row.get("position") is None:
            row["position"] = index

    return best



def parse_squadi_ladder_flat_text(
    body_text: str,
) -> list[dict[str, Any]]:
    """
    Parse a Squadi ladder even when the browser exposes an entire ladder row
    as one flattened text string rather than individual DOM/text cells.

    Expected logical row:
        rank team MP W D L GF GA PTS GD

    Example after whitespace normalisation:
        2 Armadale SC - U14 JDL D2 3 3 0 0 6 1 9 5 W W W
    """
    text = re.sub(
        r"\s+",
        " ",
        str(body_text or ""),
    ).strip()

    if not text:
        return []

    # Narrow to the actual standings portion where possible.
    rank_match = re.search(
        r"\bRank\b.*?\bNext\b",
        text,
        flags=re.IGNORECASE,
    )

    if rank_match:
        text = text[
            rank_match.end():
        ]

    # Stop before Squadi's abbreviation legend.
    legend_match = re.search(
        r"\bMP\s*=\s*Matches\s+Played\b",
        text,
        flags=re.IGNORECASE,
    )

    if legend_match:
        text = text[
            :legend_match.start()
        ]

    # The team text ends immediately before eight standalone integer stats.
    # Club/team names may contain digits inside tokens such as U14 or D2;
    # those do not match the standalone-number statistic pattern.
    row_pattern = re.compile(
        r"""
        (?:^|\s)
        (?P<position>\d{1,2})
        \s+
        (?P<team>
            .*?
            (?:-\s*U\d+\s+[^0-9]*?[A-Za-z]\d*|Academy(?:\s*-\s*U\d+.*?)?)
        )
        \s+
        (?P<played>-?\d+)
        \s+
        (?P<won>-?\d+)
        \s+
        (?P<drawn>-?\d+)
        \s+
        (?P<lost>-?\d+)
        \s+
        (?P<gf>-?\d+)
        \s+
        (?P<ga>-?\d+)
        \s+
        (?P<points>-?\d+)
        \s+
        (?P<difference>-?\d+)
        (?=
            \s+(?:W|D|L)\b
            |
            \s+\d{1,2}\s+
            |
            \s*$
        )
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    rows: list[dict[str, Any]] = []

    for match in row_pattern.finditer(
        text
    ):
        team = clean(
            match.group("team")
        )

        # Reject anything that clearly isn't a football team row.
        if not re.search(
            r"(?:FC|SC|U\d+|Academy|SPFC|LUFC|MUMFC)",
            team,
            flags=re.IGNORECASE,
        ):
            continue

        rows.append(
            {
                "position": int(
                    match.group(
                        "position"
                    )
                ),
                "team": team,
                "played": int(
                    match.group(
                        "played"
                    )
                ),
                "won": int(
                    match.group(
                        "won"
                    )
                ),
                "drawn": int(
                    match.group(
                        "drawn"
                    )
                ),
                "lost": int(
                    match.group(
                        "lost"
                    )
                ),
                "for": int(
                    match.group(
                        "gf"
                    )
                ),
                "against": int(
                    match.group(
                        "ga"
                    )
                ),
                "points": int(
                    match.group(
                        "points"
                    )
                ),
                "difference": int(
                    match.group(
                        "difference"
                    )
                ),
                "percentage": "",
            }
        )

    # If the primary regex is too strict for a future Squadi team-label
    # variation, use the known division suffix as a much simpler row boundary.
    if not rows:
        simple_pattern = re.compile(
            r"""
            (?:^|\s)
            (?P<position>\d{1,2})
            \s+
            (?P<team>
                [A-Za-z][A-Za-z0-9&().'/ -]+?
                \s*-\s*U\d+\s+[A-Za-z0-9 ]+?
            )
            \s+
            (?P<played>-?\d+)
            \s+
            (?P<won>-?\d+)
            \s+
            (?P<drawn>-?\d+)
            \s+
            (?P<lost>-?\d+)
            \s+
            (?P<gf>-?\d+)
            \s+
            (?P<ga>-?\d+)
            \s+
            (?P<points>-?\d+)
            \s+
            (?P<difference>-?\d+)
            """,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        for match in simple_pattern.finditer(
            text
        ):
            rows.append(
                {
                    "position": int(match.group("position")),
                    "team": clean(match.group("team")),
                    "played": int(match.group("played")),
                    "won": int(match.group("won")),
                    "drawn": int(match.group("drawn")),
                    "lost": int(match.group("lost")),
                    "for": int(match.group("gf")),
                    "against": int(match.group("ga")),
                    "points": int(match.group("points")),
                    "difference": int(match.group("difference")),
                    "percentage": "",
                }
            )

    # Keep one row per ladder position and return in rank order.
    unique: dict[
        int,
        dict[str, Any],
    ] = {}

    for row in rows:
        position = row.get(
            "position"
        )

        if (
            isinstance(position, int)
            and 1 <= position <= 50
        ):
            unique[
                position
            ] = row

    return [
        unique[position]
        for position in sorted(
            unique
        )
    ]


async def scrape_squadi_ladder(
    browser,
    ladder_config: dict[str, str],
) -> dict[str, Any]:
    """
    Load one Squadi public ladder and wait for the dynamically rendered
    ladder rows before parsing.

    Squadi sometimes returns the shell page quickly and populates the ladder
    several seconds later.  A fixed sleep can therefore save yesterday's
    ladder even though the page itself loaded successfully.
    """
    page = await browser.new_page(
        viewport={
            "width": 1440,
            "height": 1400,
        }
    )

    payloads: list[Any] = []
    responses: list[dict[str, Any]] = []

    async def capture(response) -> None:
        content_type = (
            response.headers.get(
                "content-type"
            )
            or ""
        ).lower()

        if "json" not in content_type:
            return

        try:
            payload = await response.json()
            payloads.append(payload)

            responses.append(
                {
                    "url": response.url,
                    "status": response.status,
                }
            )

        except Exception:
            pass

    page.on(
        "response",
        capture,
    )

    try:
        print(
            f"{ladder_config['player']} ladder: opening "
            f"{ladder_config['url']} "
            f"[parser {LADDER_PARSER_VERSION}]"
        )

        await page.goto(
            ladder_config["url"],
            wait_until="domcontentloaded",
            timeout=120_000,
        )

        # Wait until Squadi has rendered a real ladder rather than relying
        # on a fixed delay.  We look for the column headings plus the target
        # club name because those are present in both Finn and Tate's tables.
        try:
            await page.wait_for_function(
                """
                targetName => {
                  const text = (document.body?.innerText || "")
                    .replace(/\\s+/g, " ")
                    .toLowerCase();

                  const simplifiedTarget = targetName
                    .replace(/\\s*-\\s*u\\d+.*$/i, "")
                    .toLowerCase();

                  return (
                    text.includes("rank") &&
                    text.includes("mp") &&
                    text.includes("pts") &&
                    text.includes(simplifiedTarget)
                  );
                }
                """,
                ladder_config[
                    "target_team"
                ],
                timeout=35_000,
            )

        except Exception:
            # Do not fail immediately.  JSON may still contain the ladder,
            # and diagnostics below are useful if Squadi changed the UI.
            print(
                f"{ladder_config['player']} ladder: "
                "render wait timed out; trying captured data anyway."
            )

        await page.evaluate(
            "window.scrollTo("
            "0, document.body.scrollHeight"
            ")"
        )

        await page.wait_for_timeout(
            1_500
        )

        body_text = await page.locator(
            "body"
        ).inner_text()

        try:
            raw_tables = await page.locator(
                "table"
            ).evaluate_all(
                """
                tables => tables.map(table =>
                  Array.from(table.rows).map(row =>
                    Array.from(row.cells).map(cell =>
                      (cell.innerText || cell.textContent || '')
                        .replace(/\\s+/g, ' ')
                        .trim()
                    )
                  )
                )
                """
            )

        except Exception:
            raw_tables = []

        # Try every known Squadi representation, in order.
        rows = parse_squadi_ladder_payloads(
            payloads
        )
        source = "json"

        if not rows:
            rows = parse_squadi_ladder_tables(
                raw_tables
            )
            source = "html_table"

        if not rows:
            rows = parse_squadi_ladder_body_text(
                body_text
            )
            source = "rendered_text"

        if not rows:
            rows = parse_squadi_ladder_flat_text(
                body_text
            )
            source = "flat_rendered_text"

        target_summary = ladder_target_summary(
            rows,
            ladder_config[
                "target_team"
            ],
        )

        status = (
            "ok"
            if rows
            and target_summary
            else "not_found"
        )

        if status == "ok":
            print(
                f"{ladder_config['player']} ladder: "
                f"SCRAPED {len(rows)} teams via {source}; "
                f"Armadale is #{target_summary.get('position')}."
            )
        else:
            print(
                f"{ladder_config['player']} ladder: "
                f"FAILED TO PARSE current standings "
                f"(rows={len(rows)}, source={source})."
            )

            # A compact, escaped preview makes the GitHub Action log useful
            # without dumping the whole page.
            preview = re.sub(
                r"\s+",
                " ",
                body_text,
            ).strip()[:2_500]

            print(
                f"{ladder_config['player']} ladder text preview: "
                f"{preview}"
            )

        return {
            "player": ladder_config[
                "player"
            ],
            "division": ladder_config[
                "division"
            ],
            "target_team": ladder_config[
                "target_team"
            ],
            "source_url": ladder_config[
                "url"
            ],
            "fixture_reference_url": (
                ladder_config.get(
                    "fixture_reference_url",
                    "",
                )
            ),
            "rows": rows,
            "target_summary": (
                target_summary
            ),
            "status": status,
            "diagnostics": {
                "source": source,
                "json_payload_count": len(
                    payloads
                ),
                "response_urls": (
                    responses[:40]
                ),
                # Keep enough rendered text to diagnose a changed Squadi
                # layout.  This is not used to decide whether Pages deploys.
                "body_text_preview": (
                    body_text[:20_000]
                ),
            },
        }

    finally:
        await page.close()



def write_soccer_ladders_data(
    ladders: list[dict[str, Any]],
) -> None:
    """
    Publish fresh Squadi ladders while protecting the website from a
    temporary Squadi failure.

    Important behaviour:
      * Successful standings replace the old data.
      * last_updated only changes when the ladder itself changes.
      * Failed refreshes retain the previous standings but mark them stale.
      * Repeated failures do not create a new timestamp every 10 minutes.
    """
    existing_by_player: dict[
        str,
        dict[str, Any],
    ] = {}

    if SOCCER_LADDER_DATA.exists():
        try:
            existing = json.loads(
                SOCCER_LADDER_DATA.read_text(
                    encoding="utf-8"
                )
            )

            for item in existing.get(
                "ladders",
                [],
            ):
                player = clean(
                    item.get(
                        "player"
                    )
                )

                if player:
                    existing_by_player[
                        player
                    ] = item

        except Exception as exc:
            print(
                "Squadi ladders: could not read "
                f"existing data: {exc}"
            )

    merged: list[
        dict[str, Any]
    ] = []

    now = datetime.now(
        ZoneInfo(
            CONFIG["timezone"]
        )
    ).isoformat(
        timespec="seconds"
    )

    for fresh in ladders:
        player = clean(
            fresh.get(
                "player"
            )
        )

        fresh = (
            repair_squadi_ladder_from_diagnostics(
                fresh
            )
        )

        previous = (
            existing_by_player.get(
                player
            )
        )

        fresh_rows = (
            fresh.get("rows")
            or []
        )

        fresh_target = (
            ladder_target_summary(
                fresh_rows,
                clean(
                    fresh.get(
                        "target_team"
                    )
                ),
            )
            if fresh_rows
            else None
        )

        fresh_success = bool(
            fresh_rows
            and fresh_target
        )

        if fresh_success:
            fresh[
                "target_summary"
            ] = fresh_target

            previous_rows = (
                previous.get("rows")
                if previous
                else []
            ) or []

            changed = (
                ladder_rows_signature(
                    fresh_rows
                )
                != ladder_rows_signature(
                    previous_rows
                )
            )

            if (
                changed
                or not previous
                or not previous.get(
                    "last_updated"
                )
            ):
                fresh[
                    "last_updated"
                ] = now
            else:
                # Preserve the last real standings-change timestamp so a
                # routine successful poll does not modify soccer_ladders.json.
                fresh[
                    "last_updated"
                ] = previous.get(
                    "last_updated"
                )

            fresh["status"] = "ok"
            fresh["stale"] = False
            fresh.pop(
                "last_attempt_status",
                None,
            )

            # Diagnostics are helpful while developing, but they can contain
            # volatile network details. Keep the current parser source only.
            fresh["diagnostics"] = {
                "source": (
                    fresh.get(
                        "diagnostics",
                        {},
                    ).get(
                        "source",
                        "unknown",
                    )
                ),
                "team_count": len(
                    fresh_rows
                ),
                "parser_version": (
                    LADDER_PARSER_VERSION
                ),
            }

            merged.append(
                fresh
            )

            print(
                f"{player} ladder: UPDATED "
                f"({len(fresh_rows)} teams, "
                f"Armadale #{fresh_target.get('position')}, "
                f"changed={'yes' if changed else 'no'})."
            )

            continue

        # Fresh scrape failed.  Keep the last successful rows if available,
        # but make the stale state visible instead of silently presenting them
        # as newly refreshed.
        if previous and previous.get(
            "rows"
        ):
            kept = previous.copy()

            kept["status"] = "stale"
            kept["stale"] = True
            kept[
                "last_attempt_status"
            ] = (
                fresh.get("status")
                or "not_found"
            )

            kept["diagnostics"] = {
                "source": "cached_previous",
                "fresh_parse_source": (
                    fresh.get(
                        "diagnostics",
                        {},
                    ).get(
                        "source",
                        "unknown",
                    )
                ),
            }

            merged.append(
                kept
            )

            print(
                f"{player} ladder: STALE - "
                "fresh Squadi parse failed; "
                "retaining last successful standings."
            )

        else:
            failed = {
                "player": player,
                "division": fresh.get(
                    "division"
                ),
                "target_team": fresh.get(
                    "target_team"
                ),
                "source_url": fresh.get(
                    "source_url"
                ),
                "fixture_reference_url": (
                    fresh.get(
                        "fixture_reference_url",
                        "",
                    )
                ),
                "rows": [],
                "target_summary": None,
                "status": "not_found",
                "stale": True,
                "last_attempt_status": (
                    fresh.get(
                        "status"
                    )
                    or "not_found"
                ),
                "diagnostics": {
                    "source": (
                        fresh.get(
                            "diagnostics",
                            {},
                        ).get(
                            "source",
                            "unknown",
                        )
                    ),
                },
            }

            merged.append(
                failed
            )

            print(
                f"{player} ladder: NO DATA - "
                "no current or cached standings available."
            )

    payload = {
        "source": "Squadi",
        "ladders": merged,
    }

    new_text = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )

    old_text = ""

    if SOCCER_LADDER_DATA.exists():
        old_text = (
            SOCCER_LADDER_DATA.read_text(
                encoding="utf-8"
            )
        )

    if new_text == old_text:
        print(
            "Squadi ladders: no published "
            "standings change."
        )
        return

    SOCCER_LADDER_DATA.write_text(
        new_text,
        encoding="utf-8",
    )

    successful = sum(
        bool(item.get("rows"))
        for item in merged
    )

    stale = sum(
        bool(item.get("stale"))
        for item in merged
    )

    print(
        "Squadi ladders: wrote "
        f"{successful}/{len(merged)} "
        "available ladders; "
        f"{stale} marked stale."
    )



def ddmsa_clean(value: Any) -> str:
    """Normalise old DDMSA HTML text without changing team names."""
    return re.sub(
        r"\s+",
        " ",
        str(value or "").replace("\xa0", " "),
    ).strip()


def ddmsa_key(value: str) -> str:
    """Loose comparison key for DDMSA headings and team names."""
    text = ddmsa_clean(value).lower()
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def ddmsa_is_u13_heading(value: str) -> bool:
    key = ddmsa_key(value)
    return "under13" in key and "mixed" in key


def ddmsa_int(value: Any) -> int | None:
    text = ddmsa_clean(value)
    match = re.fullmatch(r"-?\d+", text)
    return int(text) if match else None


def ddmsa_extract_updated(text: str) -> str:
    """Read a DDMSA 'as of' or 'posted up till' date when present."""
    patterns = (
        r"LADDERS?\s+AS\s+OF\s+(?:THE\s+)?([0-9]{1,2}\s*[-/ ]\s*[A-Za-z]{3,9}(?:\s*[-/ ]\s*[0-9]{2,4})?)",
        r"RESULTS?\s+(?:AND\s+LADDER\s+)?POSTED\s+UP\s+TILL\s*[-:]\s*([0-9]{1,2}\s+[A-Za-z]{3,9}(?:\s+[0-9]{2,4})?)",
        r"RESULTS?\s+(?:AS\s+OF|TO)\s+(?:THE\s+)?([0-9]{1,2}\s*[-/ ]\s*[A-Za-z]{3,9}(?:\s*[-/ ]\s*[0-9]{2,4})?)",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return ddmsa_clean(match.group(1))

    return ""


def ddmsa_parse_ladder(
    tables: list[list[list[str]]],
) -> list[dict[str, Any]]:
    """Extract the Under 13's Mixed ladder from DDMSA HTML tables."""
    best: list[dict[str, Any]] = []

    for table in tables:
        heading_index = None

        for index, row in enumerate(table):
            if ddmsa_is_u13_heading(" ".join(row)):
                heading_index = index
                break

        if heading_index is None:
            continue

        ladder: list[dict[str, Any]] = []

        for row in table[heading_index + 1 :]:
            cells = [ddmsa_clean(cell) for cell in row]
            cells = [cell for cell in cells if cell]

            if not cells:
                if ladder:
                    break
                continue

            joined = " ".join(cells)
            key = ddmsa_key(joined)

            if (
                ladder
                and (
                    key.startswith("division")
                    or ("under" in key and not ddmsa_is_u13_heading(joined))
                )
            ):
                break

            if ddmsa_key(cells[0]).startswith("team"):
                continue

            # Expected DDMSA order:
            # Team, Played, Won, Lost, Drawn, For, Against, Ratio, Points, ...
            if len(cells) < 9:
                continue

            played = ddmsa_int(cells[1])
            won = ddmsa_int(cells[2])
            lost = ddmsa_int(cells[3])
            drawn = ddmsa_int(cells[4])
            runs_for = ddmsa_int(cells[5])
            runs_against = ddmsa_int(cells[6])

            # Points is normally column 9 (index 8). If DDMSA changes the
            # spreadsheet slightly, take the first integer after Ratio.
            points = ddmsa_int(cells[8]) if len(cells) > 8 else None

            if played is None or not cells[0]:
                continue

            ladder.append(
                {
                    "position": len(ladder) + 1,
                    "team": cells[0],
                    "played": played,
                    "won": won,
                    "lost": lost,
                    "drawn": drawn,
                    "runs_for": runs_for,
                    "runs_against": runs_against,
                    "ratio": cells[7] if len(cells) > 7 else "",
                    "points": points,
                    "for_against_percent": cells[10] if len(cells) > 10 else "",
                }
            )

        if len(ladder) > len(best):
            best = ladder

    return best


def ddmsa_date_from_cells(cells: list[str], previous: str = "") -> str:
    month_pattern = (
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )

    for cell in cells:
        match = re.search(
            rf"\b(\d{{1,2}}\s*[-/ ]\s*{month_pattern}"
            rf"(?:\s*[-/ ]\s*\d{{2,4}})?)\b",
            cell,
            flags=re.IGNORECASE,
        )
        if match:
            return ddmsa_clean(match.group(1))

    return previous


def ddmsa_matching_team(
    cell: str,
    team_names: list[str],
) -> str | None:
    cell_key = ddmsa_key(cell)

    for team in team_names:
        team_key = ddmsa_key(team)

        if team_key and (
            cell_key == team_key
            or team_key in cell_key
            or cell_key in team_key
        ):
            return team

    return None


def ddmsa_score_near_team(
    cells: list[str],
    team_index: int,
    other_team_index: int,
) -> int | None:
    """
    Find a likely run score adjacent to a team cell.

    Supports common old-HTML result layouts:
      Team | Score | Team | Score
      Team | Score | Score | Team
    """
    candidates: list[tuple[int, int]] = []

    for index, cell in enumerate(cells):
        value = ddmsa_int(cell)

        if value is None or value < 0 or value > 99:
            continue

        # Avoid date/round-style numbers a long way from the team.
        distance = abs(index - team_index)

        if distance <= 2:
            candidates.append((distance, index))

    candidates.sort()

    for _, index in candidates:
        # Prefer the side of the team away from the other team.
        if team_index < other_team_index and index > team_index:
            return ddmsa_int(cells[index])
        if team_index > other_team_index and index < team_index:
            return ddmsa_int(cells[index])

    return ddmsa_int(cells[candidates[0][1]]) if candidates else None



def ddmsa_weekly_u13_results(
    tables: list[list[list[str]]],
    source_url: str = "",
) -> list[dict[str, Any]]:
    """
    Parse one DDMSA weekly-results page.

    The historical results pages are spreadsheet-style HTML.  Each page
    contains several divisions and one section headed something like:

        Division U13s MIXED Saturday 1 AUG

    Rows beneath that heading are normally:

        TEAM A | SCORE | : | SCORE | TEAM B

    We only need the row containing Thornlie Hawks (Blue).
    """
    target_key = ddmsa_key(DDMSA_TEAM)
    results: list[dict[str, Any]] = []

    for table in tables:
        active_u13 = False
        current_date = ""

        for raw_row in table:
            cells = [
                ddmsa_clean(cell)
                for cell in raw_row
                if ddmsa_clean(cell)
            ]

            if not cells:
                continue

            joined = " ".join(cells)
            joined_key = ddmsa_key(joined)

            # Start of the U13 Mixed section.
            if (
                "division" in joined_key
                and "u13" in joined_key
                and "mixed" in joined_key
            ):
                active_u13 = True

                date_match = re.search(
                    r"Saturday\s+(\d{1,2}\s+[A-Za-z]{3,9})",
                    joined,
                    flags=re.IGNORECASE,
                )

                if date_match:
                    current_date = ddmsa_clean(
                        date_match.group(1)
                    )

                continue

            # Stop when the next division begins.
            if (
                active_u13
                and "division" in joined_key
                and not (
                    "u13" in joined_key
                    and "mixed" in joined_key
                )
            ):
                active_u13 = False

            if not active_u13:
                continue

            # Ignore bye rows.
            if "bye" in joined.lower():
                continue

            target_indices = [
                index
                for index, cell in enumerate(cells)
                if target_key in ddmsa_key(cell)
            ]

            if not target_indices:
                continue

            target_index = target_indices[0]

            # Locate likely U13 team-name cells in this row.  Old DDMSA
            # exports vary slightly, so identify text cells rather than
            # relying on fixed column positions.
            team_cells: list[tuple[int, str]] = []

            for index, cell in enumerate(cells):
                key = ddmsa_key(cell)

                if not key:
                    continue

                if key == target_key:
                    team_cells.append(
                        (index, DDMSA_TEAM)
                    )
                    continue

                # Skip punctuation, scores, headings and generic labels.
                if (
                    ddmsa_int(cell) is not None
                    or cell == ":"
                    or "division" in key
                    or key.startswith("team")
                    or key.startswith("score")
                    or key == "bye"
                ):
                    continue

                # Team names in this competition are alphabetic club names,
                # often with a colour in brackets.
                if re.search(
                    r"[A-Za-z]{3}",
                    cell,
                ):
                    team_cells.append(
                        (index, cell)
                    )

            opponent_hit = next(
                (
                    item
                    for item in team_cells
                    if item[0] != target_index
                    and ddmsa_key(item[1])
                    != target_key
                ),
                None,
            )

            if opponent_hit is None:
                continue

            opponent_index, opponent = opponent_hit

            # Weekly result rows are visually:
            #
            #   left team | left score | : | right score | right team
            #
            # Find the closest score to each team, moving inward.
            numeric_cells = [
                (index, ddmsa_int(cell))
                for index, cell in enumerate(cells)
                if (
                    ddmsa_int(cell) is not None
                    and 0 <= int(ddmsa_int(cell)) <= 99
                )
            ]

            def inward_score(
                team_index: int,
                other_index: int,
            ) -> int | None:
                if team_index < other_index:
                    candidates = [
                        (index, value)
                        for index, value in numeric_cells
                        if team_index < index < other_index
                    ]

                    if candidates:
                        candidates.sort(
                            key=lambda item: item[0]
                        )
                        return candidates[0][1]

                else:
                    candidates = [
                        (index, value)
                        for index, value in numeric_cells
                        if other_index < index < team_index
                    ]

                    if candidates:
                        candidates.sort(
                            key=lambda item: item[0],
                            reverse=True,
                        )
                        return candidates[0][1]

                # Fallback: nearest numeric cell to this team.
                nearest = sorted(
                    numeric_cells,
                    key=lambda item: abs(
                        item[0] - team_index
                    ),
                )

                return (
                    nearest[0][1]
                    if nearest
                    else None
                )

            thornlie_score = inward_score(
                target_index,
                opponent_index,
            )
            opponent_score = inward_score(
                opponent_index,
                target_index,
            )

            # If both lookups returned the same score, use the two scores
            # between the two teams explicitly.
            if (
                thornlie_score is not None
                and opponent_score is not None
                and thornlie_score == opponent_score
            ):
                between = [
                    (index, value)
                    for index, value in numeric_cells
                    if min(
                        target_index,
                        opponent_index,
                    )
                    < index
                    < max(
                        target_index,
                        opponent_index,
                    )
                ]

                between.sort(
                    key=lambda item: item[0]
                )

                if len(between) >= 2:
                    if target_index < opponent_index:
                        thornlie_score = between[0][1]
                        opponent_score = between[-1][1]
                    else:
                        opponent_score = between[0][1]
                        thornlie_score = between[-1][1]

            outcome = ""

            if (
                thornlie_score is not None
                and opponent_score is not None
            ):
                if thornlie_score > opponent_score:
                    outcome = "W"
                elif thornlie_score < opponent_score:
                    outcome = "L"
                else:
                    outcome = "D"

            results.append(
                {
                    "date": current_date,
                    "opponent": opponent,
                    "thornlie_score": thornlie_score,
                    "opponent_score": opponent_score,
                    "result": outcome,
                    "source_url": source_url,
                    "raw": cells,
                }
            )

    return results


def ddmsa_parse_results(
    tables: list[list[list[str]]],
    ladder: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Extract all Thornlie Hawks (Blue) U13 results from DDMSA result tables.

    DDMSA's historical pages are old spreadsheet-to-HTML exports.  Some
    tables contain the "Under 13" heading and some don't, so this parser
    identifies the U13 section by the team names from the current ladder
    instead of requiring a heading in every table.
    """
    team_names = [
        ddmsa_clean(item.get("team"))
        for item in ladder
        if ddmsa_clean(item.get("team"))
    ]

    if DDMSA_TEAM not in team_names:
        team_names.append(DDMSA_TEAM)

    results: list[dict[str, Any]] = []
    seen: set[
        tuple[str, str, int | None, int | None]
    ] = set()

    def add_result(
        date: str,
        opponent: str,
        thornlie_score: int | None,
        opponent_score: int | None,
        raw: list[str],
    ) -> None:
        if not opponent:
            return

        outcome = ""

        if (
            thornlie_score is not None
            and opponent_score is not None
        ):
            if thornlie_score > opponent_score:
                outcome = "W"
            elif thornlie_score < opponent_score:
                outcome = "L"
            else:
                outcome = "D"

        signature = (
            ddmsa_clean(date),
            ddmsa_key(opponent),
            thornlie_score,
            opponent_score,
        )

        if signature in seen:
            return

        seen.add(signature)
        results.append(
            {
                "date": ddmsa_clean(date),
                "opponent": opponent,
                "thornlie_score": thornlie_score,
                "opponent_score": opponent_score,
                "result": outcome,
                "raw": raw,
            }
        )

    for table in tables:
        current_date = ""

        # Entries where DDMSA puts one team + score on each row are paired
        # after the direct two-team row pass.
        single_entries: list[
            tuple[str, str, int | None, list[str]]
        ] = []

        for raw_row in table:
            cells = [
                ddmsa_clean(cell)
                for cell in raw_row
                if ddmsa_clean(cell)
            ]

            if not cells:
                continue

            current_date = ddmsa_date_from_cells(
                cells,
                current_date,
            )

            team_hits: list[tuple[int, str]] = []

            for cell_index, cell in enumerate(cells):
                team = ddmsa_matching_team(
                    cell,
                    team_names,
                )

                if (
                    team
                    and all(
                        ddmsa_key(existing[1])
                        != ddmsa_key(team)
                        for existing in team_hits
                    )
                ):
                    team_hits.append(
                        (cell_index, team)
                    )

            # Most result exports have both teams on the same row.
            if len(team_hits) >= 2:
                target_hit = next(
                    (
                        hit
                        for hit in team_hits
                        if ddmsa_key(hit[1])
                        == ddmsa_key(DDMSA_TEAM)
                    ),
                    None,
                )

                opponent_hit = next(
                    (
                        hit
                        for hit in team_hits
                        if ddmsa_key(hit[1])
                        != ddmsa_key(DDMSA_TEAM)
                    ),
                    None,
                )

                if target_hit and opponent_hit:
                    target_index, _ = target_hit
                    opponent_index, opponent = opponent_hit

                    target_score = ddmsa_score_near_team(
                        cells,
                        target_index,
                        opponent_index,
                    )
                    opponent_score = ddmsa_score_near_team(
                        cells,
                        opponent_index,
                        target_index,
                    )

                    # A compact spreadsheet row may contain the two scores
                    # between the team cells. Prefer the two numeric cells
                    # nearest the two team names if the first pass duplicated.
                    if (
                        target_score is not None
                        and opponent_score is not None
                        and target_score == opponent_score
                    ):
                        numeric = [
                            (index, ddmsa_int(cell))
                            for index, cell in enumerate(cells)
                            if ddmsa_int(cell) is not None
                            and 0 <= int(ddmsa_int(cell)) <= 99
                        ]

                        relevant = [
                            item
                            for item in numeric
                            if min(
                                abs(item[0] - target_index),
                                abs(item[0] - opponent_index),
                            )
                            <= 3
                        ]

                        if len(relevant) >= 2:
                            target_score = relevant[0][1]
                            opponent_score = relevant[1][1]

                    add_result(
                        current_date,
                        opponent,
                        target_score,
                        opponent_score,
                        cells,
                    )

                continue

            # Some DDMSA exports use:
            #   Team A | score
            #   Team B | score
            # rather than both teams in one row.
            if len(team_hits) == 1:
                team_index, team = team_hits[0]

                numeric = [
                    (abs(index - team_index), ddmsa_int(cell))
                    for index, cell in enumerate(cells)
                    if ddmsa_int(cell) is not None
                    and 0 <= int(ddmsa_int(cell)) <= 99
                    and abs(index - team_index) <= 3
                ]

                numeric.sort(
                    key=lambda item: item[0]
                )

                score = (
                    numeric[0][1]
                    if numeric
                    else None
                )

                single_entries.append(
                    (
                        current_date,
                        team,
                        score,
                        cells,
                    )
                )

        # Pair adjacent one-team rows belonging to U13 teams.
        for index in range(len(single_entries) - 1):
            first_entry = single_entries[index]
            second_entry = single_entries[index + 1]

            first_date, first_team, first_score, first_raw = first_entry
            second_date, second_team, second_score, second_raw = second_entry

            if ddmsa_key(first_team) == ddmsa_key(second_team):
                continue

            if (
                ddmsa_key(first_team) == ddmsa_key(DDMSA_TEAM)
                and ddmsa_key(second_team) != ddmsa_key(DDMSA_TEAM)
            ):
                add_result(
                    first_date or second_date,
                    second_team,
                    first_score,
                    second_score,
                    first_raw + second_raw,
                )

            elif (
                ddmsa_key(second_team) == ddmsa_key(DDMSA_TEAM)
                and ddmsa_key(first_team) != ddmsa_key(DDMSA_TEAM)
            ):
                add_result(
                    second_date or first_date,
                    first_team,
                    second_score,
                    first_score,
                    first_raw + second_raw,
                )

    return results


async def ddmsa_extract_document(frame) -> dict[str, Any]:
    """Extract visible text, tables and links from one DDMSA frame/page."""
    try:
        body_text = await frame.locator("body").inner_text(timeout=5_000)
    except Exception:
        body_text = ""

    try:
        tables = await frame.locator("table").evaluate_all(
            """
            tables => tables.map(table =>
              Array.from(table.rows).map(row =>
                Array.from(row.cells).map(cell =>
                  (cell.innerText || cell.textContent || '').replace(/\\s+/g, ' ').trim()
                )
              )
            )
            """
        )
    except Exception:
        tables = []

    try:
        links = await frame.locator("a[href]").evaluate_all(
            """
            links => links.map(link => ({
              text: (link.innerText || link.textContent || '').replace(/\\s+/g, ' ').trim(),
              href: link.href || ''
            }))
            """
        )
    except Exception:
        links = []

    return {
        "url": frame.url,
        "body_text": body_text,
        "tables": tables,
        "links": links,
    }


async def scrape_ddmsa_softball(browser) -> dict[str, Any]:
    """
    Scrape Tate's U13 softball ladder and results from DDMSA's legacy
    framed results site.

    The frame page changes its dated ladder/result filenames during the
    season, so links are discovered dynamically instead of hard-coding
    'Ladder 20 Jul.htm'.
    """
    page = await browser.new_page(
        viewport={"width": 1440, "height": 1200}
    )

    documents: list[dict[str, Any]] = []
    visited: set[str] = set()

    try:
        await page.goto(
            DDMSA_RESULTS_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(3_000)

        # resframe.htm normally contains a navigation frame and a content
        # frame. Extract every currently loaded frame first.
        for frame in page.frames:
            document = await ddmsa_extract_document(frame)
            if document["url"] and document["url"] not in visited:
                visited.add(document["url"])
                documents.append(document)

        candidate_links: list[tuple[int, str]] = []

        for document in documents:
            for link in document.get("links", []):
                href = ddmsa_clean(link.get("href"))
                text = ddmsa_clean(link.get("text"))
                combined = f"{text} {href}".lower()

                if not href or "ddmsa.com" not in href.lower():
                    continue

                if not re.search(r"\.html?(?:$|[?#])", href, re.IGNORECASE):
                    continue

                score = 0

                if "ladder" in combined:
                    score += 100
                if "result" in combined:
                    score += 100
                if "2026" in combined:
                    score += 20
                if "junior" in combined or "u13" in combined:
                    score += 10

                if score:
                    candidate_links.append((score, href))

        # The DDMSA homepage may expose the current Season Ladders & Results
        # link more clearly than the frame navigation, so inspect it too.
        home = await browser.new_page()

        try:
            await home.goto(
                DDMSA_HOME_URL,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await home.wait_for_timeout(1_000)
            home_document = await ddmsa_extract_document(home)

            for link in home_document.get("links", []):
                href = ddmsa_clean(link.get("href"))
                text = ddmsa_clean(link.get("text"))
                combined = f"{text} {href}".lower()

                if (
                    href
                    and "ddmsa.com" in href.lower()
                    and re.search(r"\.html?(?:$|[?#])", href, re.IGNORECASE)
                    and ("ladder" in combined or "result" in combined)
                ):
                    candidate_links.append((80, href))
        finally:
            await home.close()

        # Follow current and historical result pages. DDMSA's "Past
        # Results" page is itself framed, so every child frame must be
        # extracted rather than only the outer HTML document.
        candidate_links.append(
            (150, "https://ddmsa.com/pastres.htm")
        )

        queue: list[tuple[int, str, int]] = []

        for score, href in sorted(
            candidate_links,
            key=lambda item: item[0],
            reverse=True,
        ):
            if href not in visited:
                queue.append((score, href, 0))

        queued = {
            href
            for _, href, _ in queue
        }

        processed_pages = 0

        while queue and processed_pages < 60:
            _, href, depth = queue.pop(0)

            if href in visited:
                continue

            candidate_page = await browser.new_page()

            try:
                await candidate_page.goto(
                    href,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                await candidate_page.wait_for_timeout(800)
                processed_pages += 1

                page_documents: list[
                    dict[str, Any]
                ] = []

                for frame in candidate_page.frames:
                    document = (
                        await ddmsa_extract_document(
                            frame
                        )
                    )

                    document_url = ddmsa_clean(
                        document.get("url")
                    )

                    if (
                        document_url
                        and document_url
                        not in visited
                    ):
                        visited.add(
                            document_url
                        )
                        documents.append(
                            document
                        )
                        page_documents.append(
                            document
                        )

                # Historical menus commonly contain one link per week.
                # Follow result/past/week/2026 links one additional level.
                if depth < 2:
                    for document in page_documents:
                        for link in document.get(
                            "links",
                            [],
                        ):
                            linked_href = (
                                ddmsa_clean(
                                    link.get("href")
                                )
                            )
                            text = ddmsa_clean(
                                link.get("text")
                            )
                            combined = (
                                f"{text} {linked_href}"
                                .lower()
                            )

                            if (
                                not linked_href
                                or "ddmsa.com"
                                not in linked_href.lower()
                                or not re.search(
                                    r"\.html?"
                                    r"(?:$|[?#])",
                                    linked_href,
                                    re.IGNORECASE,
                                )
                            ):
                                continue

                            historical_hint = (
                                bool(
                                    re.search(
                                        r"week\s*0?\d+",
                                        combined,
                                        flags=re.IGNORECASE,
                                    )
                                )
                                or any(
                                    token in combined
                                    for token in (
                                        "result",
                                        "past",
                                        "2026",
                                        "junior",
                                        "u13",
                                        "ladder",
                                    )
                                )
                            )

                            if not historical_hint:
                                continue

                            if (
                                linked_href
                                not in visited
                                and linked_href
                                not in queued
                            ):
                                queued.add(
                                    linked_href
                                )
                                queue.append(
                                    (
                                        50,
                                        linked_href,
                                        depth + 1,
                                    )
                                )

            except Exception:
                pass
            finally:
                await candidate_page.close()

        ladder_candidates: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []

        for document in documents:
            ladder = ddmsa_parse_ladder(document.get("tables", []))

            if not ladder:
                continue

            score = len(ladder)

            if "ladder" in document.get("url", "").lower():
                score += 100

            if "2026" in document.get("url", "").lower():
                score += 20

            if re.search(
                r"LADDERS?\s+AS\s+OF",
                document.get("body_text", ""),
                flags=re.IGNORECASE,
            ):
                score += 50

            ladder_candidates.append((score, document, ladder))

        ladder: list[dict[str, Any]] = []
        ladder_document: dict[str, Any] | None = None

        if ladder_candidates:
            _, ladder_document, ladder = max(
                ladder_candidates,
                key=lambda item: item[0],
            )

        results: list[dict[str, Any]] = []
        result_sources: list[str] = []
        result_seen: set[
            tuple[str, str, int | None, int | None]
        ] = set()

        for document in documents:
            document_results = (
                ddmsa_weekly_u13_results(
                    document.get("tables", []),
                    document.get("url", ""),
                )
            )

            # Keep the broad parser as a fallback for any DDMSA page that
            # does not use the standard weekly U13 Mixed layout.
            if not document_results:
                document_results = ddmsa_parse_results(
                    document.get("tables", []),
                    ladder,
                )

            if not document_results:
                continue

            document_url = ddmsa_clean(
                document.get("url")
            )

            if (
                document_url
                and document_url
                not in result_sources
            ):
                result_sources.append(
                    document_url
                )

            for result in document_results:
                signature = (
                    ddmsa_clean(
                        result.get("date")
                    ),
                    ddmsa_key(
                        result.get("opponent", "")
                    ),
                    result.get(
                        "thornlie_score"
                    ),
                    result.get(
                        "opponent_score"
                    ),
                )

                if signature in result_seen:
                    continue

                result_seen.add(signature)
                results.append(result)

        def result_sort_key(
            result: dict[str, Any],
        ) -> datetime:
            raw_date = ddmsa_clean(
                result.get("date")
            )

            if not raw_date:
                return datetime(
                    1900,
                    1,
                    1,
                )

            text = raw_date

            if not re.search(
                r"\b20\d{2}\b",
                text,
            ):
                text = f"{text} 2026"

            try:
                parsed = dateparser.parse(
                    text,
                    dayfirst=True,
                )

                return parsed or datetime(
                    1900,
                    1,
                    1,
                )
            except Exception:
                return datetime(
                    1900,
                    1,
                    1,
                )

        results.sort(
            key=result_sort_key
        )

        results_document: dict[str, Any] | None = (
            next(
                (
                    document
                    for document in documents
                    if ddmsa_clean(
                        document.get("url")
                    )
                    in result_sources
                ),
                None,
            )
        )

        team_row = next(
            (
                row
                for row in ladder
                if ddmsa_key(row.get("team", ""))
                == ddmsa_key(DDMSA_TEAM)
            ),
            None,
        )

        updated = ""

        for document in (
            ladder_document,
            results_document,
            *documents,
        ):
            if not document:
                continue

            updated = ddmsa_extract_updated(
                document.get("body_text", "")
            )

            if updated:
                break

        return {
            "source": "Dale Districts Men's Softball Association",
            "source_url": DDMSA_RESULTS_URL,
            "division": DDMSA_DIVISION,
            "team": DDMSA_TEAM,
            "updated": updated,
            "team_summary": team_row,
            "ladder": ladder,
            "results": results,
            "ladder_source_url": (
                ladder_document.get("url", "")
                if ladder_document
                else ""
            ),
            "results_source_url": (
                results_document.get("url", "")
                if results_document
                else ""
            ),
            "results_source_urls": result_sources,
            "status": (
                "ok"
                if ladder
                else "ladder_not_found"
            ),
            # Keep small diagnostics useful if DDMSA changes its old site.
            "diagnostics": {
                "documents_checked": len(documents),
                "past_results_found": len(results),
                "weekly_u13_results_found": len(results),
                "result_source_count": len(result_sources),
                "result_document_previews": [
                    {
                        "url": document.get("url", ""),
                        "text": document.get("body_text", "")[:3_000],
                        "tables": document.get("tables", [])[:4],
                    }
                    for document in documents
                    if (
                        "result" in document.get("url", "").lower()
                        or "pastres" in document.get("url", "").lower()
                        or DDMSA_TEAM.lower()
                        in document.get("body_text", "").lower()
                    )
                ][:8],
                "candidate_urls": [
                    document.get("url", "")
                    for document in documents
                    if document.get("url")
                ][:30],
            },
        }

    finally:
        await page.close()


def write_ddmsa_softball_data(data: dict[str, Any]) -> bool:
    """
    Publish DDMSA data only when a useful ladder was scraped.

    If DDMSA is temporarily unavailable, keep the previously published
    softball.json instead of replacing it with an empty file.
    """
    if not data.get("ladder"):
        print(
            "DDMSA warning: U13 ladder was not detected; "
            "keeping existing docs/softball.json."
        )
        return False

    SOFTBALL_DATA.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    SOFTBALL_DATA.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "DDMSA: wrote "
        f"{len(data.get('ladder', []))} ladder rows and "
        f"{len(data.get('results', []))} Tate result rows "
        f"to {SOFTBALL_DATA}."
    )

    return True


SCHOOL_EVENT_DATE_KEYS = (
    # Teamup API/event payload names.
    "start_dt", "start",
    # Generic fallbacks.
    "startDate", "startDateTime", "startTime",
    "date", "eventDate", "dateTime",
)
SCHOOL_EVENT_END_KEYS = (
    "end_dt", "end",
    "endDate", "endDateTime", "endTime",
)
SCHOOL_EVENT_LOCATION_KEYS = (
    "location", "locationName", "venue", "venueName", "address", "where",
)

def normalise_school_event_text(value: Any) -> str:
    """
    Normalise Teamup event text for matching.

    This deliberately treats hyphen, en-dash and em-dash as equivalent,
    collapses whitespace, and ignores case.
    """
    text = str(value or "")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def school_event_text_matches(value: Any) -> bool:
    text = normalise_school_event_text(value)

    if not text:
        return False

    # Flexible match for variations such as:
    # ACC soccer Y10-12 boys
    # ACC Soccer Y10 - 12 Boys
    # ACC SOCCER Y10–12 BOYS
    return bool(
        re.search(
            r"\bacc\b.*?\bsoccer\b.*?\by\s*10\s*-\s*12\b.*?\bboys\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def school_object_matches(obj: dict[str, Any]) -> bool:
    return any(
        isinstance(value, str) and school_event_text_matches(value)
        for value in obj.values()
    )

def school_fixture_from_json(
    obj: dict[str, Any],
    timezone: ZoneInfo,
) -> dict[str, Any] | None:
    if not school_object_matches(obj):
        return None

    start = parse_datetime(first(obj, SCHOOL_EVENT_DATE_KEYS), timezone)
    if not start:
        return None

    end = parse_datetime(first(obj, SCHOOL_EVENT_END_KEYS), timezone)
    duration = (
        max(15, int((end - start).total_seconds() // 60))
        if end and end > start
        else 60
    )

    title = next(
        (
            clean(obj.get(key))
            for key in ("title", "name", "summary", "eventTitle", "eventName", "subject")
            if clean(obj.get(key))
            and school_event_text_matches(clean(obj.get(key)))
        ),
        SCHOOL_SOCCER_MATCH_TEXT,
    )

    location = normalise_location(
        clean(first(obj, SCHOOL_EVENT_LOCATION_KEYS))
    )
    source_url = clean(
        first(obj, ("url", "link", "eventUrl", "eventURL", "href"))
    )
    if not source_url.startswith("http"):
        source_url = SCHOOL_CALENDAR_PAGE_URL

    source_id = clean(
        first(obj, ("id", "eventId", "eventID", "uid", "guid"))
    )
    if not source_id:
        source_id = "school-" + hashlib.sha256(
            f"{title}|{start.isoformat()}|{location}".encode("utf-8")
        ).hexdigest()[:16]

    return {
        "start": start,
        "home": "St John Bosco College",
        "away": "ACC Soccer",
        "venue": location,
        "field": "",
        "round": "",
        "source_id": source_id,
        "label": "Finn",
        "source_url": source_url,
        "latitude": None,
        "longitude": None,
        "coordinate_source": "",
        "home_score": "",
        "away_score": "",
        "sport_icon": "🏫",
        "sport_name": "School Soccer",
        "time_label": "KO",
        "duration_minutes": duration,
        "reminder_minutes": int(CONFIG.get("reminder_minutes", 90)),
        "notes": "",
        "display_title": title,
        "source_type": "school_calendar",
    }

def parse_school_card_datetime(text: str, timezone: ZoneInfo) -> datetime | None:
    text = clean(text)
    if not text:
        return None
    if not re.search(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?\b"
        r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
        text,
        flags=re.IGNORECASE,
    ):
        return None
    try:
        parsed = dateparser.parse(text, fuzzy=True, dayfirst=True)
        if not parsed:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except Exception:
        return None

async def scrape_school_soccer(browser, timezone: ZoneInfo):
    page = await browser.new_page(viewport={"width": 1440, "height": 1400})
    payloads: list[Any] = []
    response_log: list[dict[str, Any]] = []

    async def capture(response) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        url_lower = response.url.lower()
        if (
            "json" not in content_type
            and "calendar" not in url_lower
            and "event" not in url_lower
        ):
            return

        response_log.append({
            "url": response.url,
            "status": response.status,
            "content_type": content_type,
        })

        if "json" in content_type:
            try:
                payloads.append(await response.json())
            except Exception:
                pass

    page.on("response", capture)

    try:
        print(
            "St John Bosco school soccer: opening "
            + SCHOOL_CALENDAR_URL
            + f" [school scraper {SCHOOL_SOCCER_SCRAPER_VERSION}]"
        )
        await page.goto(
            SCHOOL_CALENDAR_URL,
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        await page.wait_for_timeout(12_000)

        fixtures: list[dict[str, Any]] = []

        # Diagnostic: print Teamup titles containing ACC or soccer so the
        # GitHub Action log reveals the exact wording returned by Teamup.
        interesting_titles: list[str] = []

        for payload in payloads:
            for obj in walk(payload):
                for key in ("title", "name", "summary", "eventTitle", "eventName", "subject"):
                    value = clean(obj.get(key))

                    if not value:
                        continue

                    lower = value.lower()

                    if (
                        "acc" in lower
                        or "soccer" in lower
                    ):
                        if value not in interesting_titles:
                            interesting_titles.append(value)

        if interesting_titles:
            print(
                "St John Bosco Teamup candidate titles: "
                + " | ".join(interesting_titles[:30])
            )
        else:
            print(
                "St John Bosco Teamup candidate titles: "
                "none containing ACC or soccer"
            )

        # Preferred route: structured calendar/event JSON.
        for payload in payloads:
            for obj in walk(payload):
                fixture = school_fixture_from_json(obj, timezone)
                if fixture:
                    fixtures.append(fixture)

        frame_debug: list[dict[str, Any]] = []

        # Fallback: search visible main-page/iframe event cards.
        if not fixtures:
            for frame_index, frame in enumerate(page.frames):
                try:
                    body_text = await frame.locator("body").inner_text(timeout=5_000)
                except Exception:
                    continue

                contains_target = (
                    SCHOOL_SOCCER_MATCH_TEXT.lower() in body_text.lower()
                )
                frame_debug.append({
                    "frame_index": frame_index,
                    "url": frame.url,
                    "contains_target": contains_target,
                    "body_text_preview": body_text[:5_000],
                })

                if not contains_target:
                    continue

                try:
                    matches = frame.get_by_text(
                        re.compile(
                            r"ACC.*soccer.*Y\s*10\s*[-–—]\s*12.*boys",
                            re.IGNORECASE,
                        )
                    )
                    count = min(await matches.count(), 50)
                except Exception:
                    count = 0

                for index in range(count):
                    try:
                        data = await matches.nth(index).evaluate(
                            """el => {
                              let node = el;
                              let best = (el.innerText || el.textContent || '').trim();
                              for (let i = 0; i < 8 && node; i += 1) {
                                const text = (node.innerText || node.textContent || '')
                                  .replace(/\\s+/g, ' ').trim();
                                if (text.length >= best.length && text.length <= 1800) {
                                  best = text;
                                }
                                node = node.parentElement;
                              }
                              const a = el.closest('a') || el.querySelector?.('a');
                              return {text: best, href: a?.href || ''};
                            }"""
                        )
                    except Exception:
                        continue

                    card_text = clean(data.get("text"))
                    start = parse_school_card_datetime(card_text, timezone)
                    if not start:
                        continue

                    location = ""
                    loc_match = re.search(
                        r"(?:Location|Venue|Where)\s*[:\-]\s*([^|]+)",
                        card_text,
                        flags=re.IGNORECASE,
                    )
                    if loc_match:
                        location = normalise_location(clean(loc_match.group(1)))

                    fixtures.append({
                        "start": start,
                        "home": "St John Bosco College",
                        "away": "ACC Soccer",
                        "venue": location,
                        "field": "",
                        "round": "",
                        "source_id": "school-dom-" + hashlib.sha256(
                            f"{card_text}|{start.isoformat()}".encode("utf-8")
                        ).hexdigest()[:16],
                        "label": "Finn",
                        "source_url": clean(data.get("href")) or SCHOOL_CALENDAR_PAGE_URL,
                        "latitude": None,
                        "longitude": None,
                        "coordinate_source": "",
                        "home_score": "",
                        "away_score": "",
                        "sport_icon": "🏫",
                        "sport_name": "School Soccer",
                        "time_label": "KO",
                        "duration_minutes": 60,
                        "reminder_minutes": int(CONFIG.get("reminder_minutes", 90)),
                        "notes": card_text,
                        "display_title": SCHOOL_SOCCER_MATCH_TEXT,
                        "source_type": "school_calendar",
                    })

        # De-duplicate the same school event if the page exposes it more than once.
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for fixture in fixtures:
            key = (
                fixture["start"].isoformat(),
                clean(fixture.get("display_title")).lower(),
            )
            unique[key] = fixture

        fixtures = sorted(unique.values(), key=lambda item: item["start"])

        print(
            "St John Bosco Teamup: "
            f"captured {len(payloads)} JSON payloads and "
            f"found {len(fixtures)} matching "
            f"'{SCHOOL_SOCCER_MATCH_TEXT}' events."
        )

        return fixtures, {
            "source": SCHOOL_CALENDAR_URL,
            "match_text": SCHOOL_SOCCER_MATCH_TEXT,
            "fixture_count": len(fixtures),
            "json_payload_count": len(payloads),
            "responses": response_log[:40],
            "frames": frame_debug,
        }
    finally:
        await page.close()


def load_manual_fixtures(
    timezone: ZoneInfo,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load manually maintained fixtures, such as Tate's softball games."""

    if not MANUAL_FIXTURES.exists():
        return [], {
            "file": MANUAL_FIXTURES.name,
            "file_found": False,
            "fixture_count": 0,
            "errors": [],
        }

    try:
        payload = json.loads(
            MANUAL_FIXTURES.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read {MANUAL_FIXTURES.name}: {exc}"
        ) from exc

    raw_fixtures = payload.get("fixtures", [])
    if not isinstance(raw_fixtures, list):
        raise RuntimeError(
            f"{MANUAL_FIXTURES.name} must contain a 'fixtures' list."
        )

    fixtures: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, item in enumerate(raw_fixtures, start=1):
        if not isinstance(item, dict):
            errors.append(f"Fixture {index}: expected an object.")
            continue

        source_id = clean(item.get("id")) or f"manual-{index}"
        start_text = clean(item.get("start"))
        label = clean(item.get("label"))
        home = clean(item.get("home"))
        away = clean(item.get("away"))

        try:
            start = dateparser.isoparse(start_text)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone)
            else:
                start = start.astimezone(timezone)
        except (TypeError, ValueError, OverflowError):
            errors.append(
                f"Fixture {source_id}: invalid start date '{start_text}'."
            )
            continue

        if not label or not home or not away:
            errors.append(
                f"Fixture {source_id}: label, home and away are required."
            )
            continue

        # Do not publish manually entered byes as calendar matches.
        if home.lower() == "bye" or away.lower() == "bye":
            continue

        latitude = to_float(item.get("latitude"))
        longitude = to_float(item.get("longitude"))
        coordinates = valid_coordinates(latitude, longitude)

        fixtures.append(
            {
                "start": start,
                "home": home,
                "away": away,
                "venue": normalise_location(clean(item.get("venue"))),
                "field": normalise_location(clean(item.get("field"))),
                "round": clean(item.get("round")),
                "source_id": source_id,
                "label": label,
                "source_url": clean(item.get("source_url")),
                "latitude": coordinates[0] if coordinates else None,
                "longitude": coordinates[1] if coordinates else None,
                "coordinate_source": "manual" if coordinates else "",
                "sport_icon": clean(item.get("sport_icon")) or "🏅",
                "sport_name": clean(item.get("sport_name")),
                "time_label": clean(item.get("time_label")) or "Start",
                "duration_minutes": int(
                    item.get(
                        "duration_minutes",
                        CONFIG.get("default_match_minutes", 60),
                    )
                ),
                "reminder_minutes": int(
                    item.get(
                        "reminder_minutes",
                        CONFIG.get("reminder_minutes", 90),
                    )
                ),
                "notes": clean(item.get("notes")),
                "home_score": normalise_score(item.get("home_score")),
                "away_score": normalise_score(item.get("away_score")),
            }
        )

    return fixtures, {
        "file": MANUAL_FIXTURES.name,
        "file_found": True,
        "fixture_count": len(fixtures),
        "errors": errors,
    }


async def scrape_team(
    browser,
    team: dict[str, Any],
    timezone: ZoneInfo,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = await browser.new_page(viewport={"width": 1440, "height": 1200})

    payloads: list[Any] = []
    responses: list[dict[str, Any]] = []

    async def capture(response) -> None:
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" not in content_type:
            return

        try:
            payloads.append(await response.json())
            responses.append({"url": response.url, "status": response.status})
        except Exception:
            pass

    page.on("response", capture)

    await page.goto(
        team["url"],
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    await page.wait_for_timeout(12_000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(3_000)

    body_text = await page.locator("body").inner_text()
    location_by_match_id = locations_from_page_text(body_text)
    page_coordinates = await coordinates_from_page(page)
    coordinate_index = build_coordinate_index(payloads)

    competition_id, competition_key = competition_details(team, responses)
    fixtures: list[dict[str, Any]] = []

    for payload in payloads:
        for obj in walk(payload):
            start = parse_datetime(first(obj, DATE_KEYS), timezone)
            home = clean(first(obj, HOME_KEYS) or first(obj, ("home", "team1")))
            away = clean(first(obj, AWAY_KEYS) or first(obj, ("away", "team2")))

            if not start or not home or not away or home == away:
                continue

            source_id = clean(first(obj, ID_KEYS))
            match_url = squadi_match_url(
                team,
                source_id,
                competition_id,
                competition_key,
            )

            venue = normalise_location(clean(first(obj, VENUE_KEYS)))
            field = normalise_location(clean(first(obj, FIELD_KEYS)))
            page_location = location_by_match_id.get(source_id, "")

            if page_location:
                venue = page_location
                field = ""

            coordinates = page_coordinates.get(source_id)
            coordinate_source = "page_map_link" if coordinates else ""

            if not coordinates:
                coordinates = extract_coordinates(obj)
                if coordinates:
                    coordinate_source = "match_json"

            if not coordinates:
                for reference_id in fixture_reference_ids(obj):
                    coordinates = coordinate_index.get(reference_id)
                    if coordinates:
                        coordinate_source = f"venue_record:{reference_id}"
                        break

            latitude = coordinates[0] if coordinates else None
            longitude = coordinates[1] if coordinates else None
            home_score, away_score = extract_score_pair(obj)

            fixtures.append(
                {
                    "start": start,
                    "home": home,
                    "away": away,
                    "venue": venue,
                    "field": field,
                    "round": clean(first(obj, ROUND_KEYS)),
                    "source_id": source_id,
                    "label": team["name"],
                    "source_url": match_url,
                    "latitude": latitude,
                    "longitude": longitude,
                    "coordinate_source": coordinate_source,
                    "home_score": home_score,
                    "away_score": away_score,
                    "sport_name": "Soccer",
                }
            )

    await page.close()

    debug = {
        "team": team["name"],
        "competition_id": competition_id,
        "competition_unique_key": competition_key,
        "responses": responses,
        "locations_found": location_by_match_id,
        "page_coordinates_found": {
            match_id: {"latitude": coords[0], "longitude": coords[1]}
            for match_id, coords in page_coordinates.items()
        },
        "coordinate_index_size": len(coordinate_index),
        "body_text_preview": body_text[:8_000],
    }

    return fixtures, debug


def build_calendar(
    fixtures: list[dict[str, Any]],
    timezone_name: str,
) -> str:
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    default_match_minutes = int(CONFIG.get("default_match_minutes", 60))
    default_reminder_minutes = int(CONFIG.get("reminder_minutes", 90))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Finn and Tate Sports Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + escape_ics(CONFIG["calendar_name"]),
        "X-WR-TIMEZONE:" + timezone_name,
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]

    for fixture in fixtures:
        start = fixture["start"]
        duration_minutes = int(
            fixture.get("duration_minutes", default_match_minutes)
        )
        reminder_minutes = int(
            fixture.get("reminder_minutes", default_reminder_minutes)
        )
        end = start + timedelta(minutes=duration_minutes)

        uid_seed = (
            f"{fixture['label']}|{fixture['source_id']}|{start.isoformat()}|"
            f"{fixture['home']}|{fixture['away']}"
        )
        uid = (
            hashlib.sha256(uid_seed.encode("utf-8")).hexdigest()[:24]
            + "@family-soccer-calendar"
        )

        location_parts: list[str] = []
        for part in (fixture["venue"], fixture["field"]):
            if part and part not in location_parts:
                location_parts.append(part)
        location = " — ".join(location_parts)

        latitude = fixture.get("latitude")
        longitude = fixture.get("longitude")
        navigation_url = waze_url(location, latitude, longitude)

        round_text = format_round_text(fixture["round"])
        source_url = clean(fixture.get("source_url"))
        notes = clean(fixture.get("notes"))
        home_score = clean(fixture.get("home_score"))
        away_score = clean(fixture.get("away_score"))
        result_text = (
            f"Result: {home_score}-{away_score}"
            if home_score and away_score
            else ""
        )
        description_lines = [
            round_text,
            result_text,
            notes,
            ((("Open school calendar" if clean(fixture.get("source_type")) == "school_calendar" else "Open in Squadi") + ": " + source_url) if source_url else ""),
        ]
        description = "\n".join(filter(None, description_lines))

        sport_icon = clean(fixture.get("sport_icon")) or "⚽"
        time_label = clean(fixture.get("time_label")) or "KO"
        display_title = clean(fixture.get("display_title"))

        match_title = display_title or (

            f"{short_team_name(fixture['home'])} vs "

            f"{short_team_name(fixture['away'])}"

        )

        title = (

            f"{sport_icon} {fixture['label']} | "

            f"{match_title} | "

            f"{time_label} {format_kickoff_time(start)}"

        )

        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID={timezone_name}:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={timezone_name}:{end.strftime('%Y%m%dT%H%M%S')}",
            "SUMMARY:" + escape_ics(title),
            "LOCATION:" + escape_ics(location),
            "X-PERSON:" + escape_ics(clean(fixture.get("label"))),
            "X-SPORT:" + escape_ics(
                clean(fixture.get("sport_name")) or "Soccer"
            ),
            "X-HOME-TEAM:" + escape_ics(short_team_name(fixture["home"])),
            "X-AWAY-TEAM:" + escape_ics(short_team_name(fixture["away"])),
            "X-SOURCE-TYPE:" + escape_ics(clean(fixture.get("source_type"))),
        ]

        if home_score and away_score:
            event_lines.extend(
                [
                    "X-HOME-SCORE:" + escape_ics(home_score),
                    "X-AWAY-SCORE:" + escape_ics(away_score),
                ]
            )

        coordinates = valid_coordinates(latitude, longitude)
        if coordinates:
            lat, lng = coordinates
            event_lines.append(f"GEO:{lat:.6f};{lng:.6f}")

        # Apple Calendar displays this as the event's Open link.
        if navigation_url:
            event_lines.append(f"URL:{navigation_url}")

        event_lines.extend(
            [
                "DESCRIPTION:" + escape_ics(description),
                "STATUS:CONFIRMED",
                "BEGIN:VALARM",
                f"TRIGGER:-PT{reminder_minutes}M",
                "ACTION:DISPLAY",
                "DESCRIPTION:"
                + escape_ics(f"{fixture['label']} fixture reminder"),
                "END:VALARM",
                "END:VEVENT",
            ]
        )

        lines.extend(event_lines)

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n"


async def main() -> None:
    timezone = ZoneInfo(CONFIG["timezone"])
    all_fixtures: list[dict[str, Any]] = []
    debug_teams: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        for team in CONFIG["teams"]:
            fixtures, debug = await scrape_team(browser, team, timezone)
            all_fixtures.extend(fixtures)
            debug_teams.append(debug)

        try:
            school_fixtures, school_debug = await scrape_school_soccer(
                browser,
                timezone,
            )
            all_fixtures.extend(school_fixtures)
        except Exception as exc:
            school_debug = {
                "source": SCHOOL_CALENDAR_URL,
                "match_text": SCHOOL_SOCCER_MATCH_TEXT,
                "fixture_count": 0,
                "error": str(exc),
            }
            print(f"St John Bosco school soccer warning: {exc}")

        soccer_ladders: list[dict[str, Any]] = []

        for ladder_config in SOCCER_LADDERS:
            try:
                soccer_ladders.append(
                    await scrape_squadi_ladder(
                        browser,
                        ladder_config,
                    )
                )
            except Exception as exc:
                soccer_ladders.append(
                    {
                        "player": ladder_config["player"],
                        "division": ladder_config["division"],
                        "target_team": ladder_config[
                            "target_team"
                        ],
                        "source_url": ladder_config["url"],
                        "fixture_reference_url": ladder_config.get(
                            "fixture_reference_url",
                            "",
                        ),
                        "rows": [],
                        "target_summary": None,
                        "status": "error",
                        "diagnostics": {
                            "error": str(exc),
                        },
                    }
                )

        write_soccer_ladders_data(
            soccer_ladders
        )

        try:
            ddmsa_softball = await scrape_ddmsa_softball(browser)
            write_ddmsa_softball_data(ddmsa_softball)
        except Exception as exc:
            # Do not allow a temporary DDMSA outage to break the soccer
            # calendar or erase the last successfully published softball data.
            print(f"DDMSA warning: {exc}")

        await browser.close()

    manual_fixtures, manual_debug = load_manual_fixtures(timezone)
    all_fixtures.extend(manual_fixtures)

    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for fixture in all_fixtures:
        key = (
            fixture["label"],
            fixture["start"].isoformat(),
            fixture["home"].lower(),
            fixture["away"].lower(),
        )
        unique[key] = fixture

    fixtures = sorted(unique.values(), key=lambda item: item["start"])

    DEBUG.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone).isoformat(),
                "fixture_count": len(fixtures),
                "coordinate_fixture_count": sum(
                    1
                    for fixture in fixtures
                    if valid_coordinates(
                        fixture.get("latitude"),
                        fixture.get("longitude"),
                    )
                ),
                "teams": debug_teams,
                "school_soccer": school_debug,
                "manual_fixtures": manual_debug,
                "manual_fixture_count": len(manual_fixtures),
                "fixtures": [
                    {
                        **fixture,
                        "start": fixture["start"].isoformat(),
                    }
                    for fixture in fixtures
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if not fixtures:
        raise RuntimeError(
            "No fixtures were detected. Open docs/debug.json for details."
        )

    OUTPUT.write_text(
        build_calendar(fixtures, CONFIG["timezone"]),
        encoding="utf-8",
    )

    print(
        f"Wrote {len(fixtures)} fixtures to {OUTPUT}; "
        f"{sum(1 for fixture in fixtures if fixture.get('latitude') is not None)} "
        "had coordinates."
    )


if __name__ == "__main__":
    asyncio.run(main())
