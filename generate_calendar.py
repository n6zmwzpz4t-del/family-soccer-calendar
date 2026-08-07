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


def ddmsa_parse_results(
    tables: list[list[list[str]]],
    ladder: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Extract Tate's Thornlie Hawks (Blue) result rows.

    DDMSA uses legacy spreadsheets converted to HTML, so this parser is
    intentionally tolerant of slightly different column layouts.
    """
    team_names = [
        ddmsa_clean(item.get("team"))
        for item in ladder
        if ddmsa_clean(item.get("team"))
    ]

    if DDMSA_TEAM not in team_names:
        team_names.append(DDMSA_TEAM)

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()

    for table in tables:
        heading_index = None

        for index, row in enumerate(table):
            if ddmsa_is_u13_heading(" ".join(row)):
                heading_index = index
                break

        if heading_index is None:
            continue

        current_date = ""

        for row in table[heading_index + 1 :]:
            cells = [ddmsa_clean(cell) for cell in row]
            cells = [cell for cell in cells if cell]

            if not cells:
                continue

            joined = " ".join(cells)
            key = ddmsa_key(joined)

            if (
                ("under" in key and not ddmsa_is_u13_heading(joined))
                or key.startswith("division")
            ):
                break

            current_date = ddmsa_date_from_cells(cells, current_date)

            team_hits: list[tuple[int, str]] = []

            for index, cell in enumerate(cells):
                team = ddmsa_matching_team(cell, team_names)
                if team and all(ddmsa_key(existing[1]) != ddmsa_key(team) for existing in team_hits):
                    team_hits.append((index, team))

            if len(team_hits) < 2:
                continue

            target_hit = next(
                (
                    hit
                    for hit in team_hits
                    if ddmsa_key(hit[1]) == ddmsa_key(DDMSA_TEAM)
                ),
                None,
            )

            if target_hit is None:
                continue

            opponent_hit = next(
                (
                    hit
                    for hit in team_hits
                    if ddmsa_key(hit[1]) != ddmsa_key(DDMSA_TEAM)
                ),
                None,
            )

            if opponent_hit is None:
                continue

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

            # If both score lookups picked the same integer in a compact
            # layout, fall back to the two small integers nearest the teams.
            if (
                target_score is not None
                and opponent_score is not None
                and target_score == opponent_score
            ):
                numeric_cells = [
                    (index, ddmsa_int(cell))
                    for index, cell in enumerate(cells)
                    if ddmsa_int(cell) is not None
                    and 0 <= int(ddmsa_int(cell)) <= 99
                ]

                near = [
                    item
                    for item in numeric_cells
                    if min(abs(item[0] - target_index), abs(item[0] - opponent_index)) <= 2
                ]

                distinct = []
                for item in near:
                    if item[1] not in [value for _, value in distinct]:
                        distinct.append(item)

                if len(distinct) >= 2:
                    target_score = distinct[0][1]
                    opponent_score = distinct[1][1]

            outcome = ""

            if target_score is not None and opponent_score is not None:
                if target_score > opponent_score:
                    outcome = "W"
                elif target_score < opponent_score:
                    outcome = "L"
                else:
                    outcome = "D"

            record = {
                "date": current_date,
                "opponent": opponent,
                "thornlie_score": target_score,
                "opponent_score": opponent_score,
                "result": outcome,
                "raw": cells,
            }

            signature = (
                current_date,
                ddmsa_key(opponent),
                target_score,
                opponent_score,
            )

            if signature not in seen:
                seen.add(signature)
                results.append(record)

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

        # Follow the most promising dated result/ladder links. Old DDMSA
        # menus can contain historical links, so cap the number inspected.
        unique_candidates: list[str] = []

        for _, href in sorted(
            candidate_links,
            key=lambda item: item[0],
            reverse=True,
        ):
            if href not in visited and href not in unique_candidates:
                unique_candidates.append(href)

        for href in unique_candidates[:24]:
            candidate_page = await browser.new_page()

            try:
                await candidate_page.goto(
                    href,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                await candidate_page.wait_for_timeout(600)
                document = await ddmsa_extract_document(candidate_page)
                visited.add(href)
                documents.append(document)
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

        result_candidates: list[
            tuple[int, dict[str, Any], list[dict[str, Any]]]
        ] = []

        for document in documents:
            results = ddmsa_parse_results(
                document.get("tables", []),
                ladder,
            )

            if not results:
                continue

            score = len(results)

            if "result" in document.get("url", "").lower():
                score += 100

            if "2026" in document.get("url", "").lower():
                score += 20

            if re.search(
                r"\bRESULT",
                document.get("body_text", ""),
                flags=re.IGNORECASE,
            ):
                score += 50

            result_candidates.append((score, document, results))

        results: list[dict[str, Any]] = []
        results_document: dict[str, Any] | None = None

        if result_candidates:
            _, results_document, results = max(
                result_candidates,
                key=lambda item: item[0],
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
            "status": (
                "ok"
                if ladder
                else "ladder_not_found"
            ),
            # Keep small diagnostics useful if DDMSA changes its old site.
            "diagnostics": {
                "documents_checked": len(documents),
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
            ("Open in Squadi: " + source_url) if source_url else "",
        ]
        description = "\n".join(filter(None, description_lines))

        sport_icon = clean(fixture.get("sport_icon")) or "⚽"
        time_label = clean(fixture.get("time_label")) or "KO"
        title = (
            f"{sport_icon} {fixture['label']} | "
            f"{short_team_name(fixture['home'])} vs "
            f"{short_team_name(fixture['away'])} | "
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
