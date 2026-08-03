from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

OUTPUT = ROOT / "docs" / "fixtures.ics"
DEBUG = ROOT / "docs" / "debug.json"


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
        return ", ".join(
            filter(
                None,
                (clean(item) for item in value),
            )
        )

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def first(
    obj: dict[str, Any],
    keys: tuple[str, ...],
) -> Any:
    lower = {
        str(key).lower(): value
        for key, value in obj.items()
    }

    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]

        lower_key = key.lower()

        if (
            lower_key in lower
            and lower[lower_key] not in (None, "")
        ):
            return lower[lower_key]

    return None


def walk(value: Any):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_datetime(
    value: Any,
    timezone: ZoneInfo,
) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            seconds = (
                value / 1000
                if value > 10_000_000_000
                else value
            )

            return datetime.fromtimestamp(
                seconds,
                timezone,
            )

        text = clean(value)

        if not text:
            return None

        # Squadi supplies dates in month/day/year order.
        parsed = dateparser.parse(
            text,
            dayfirst=False,
        )

        if not parsed:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone,
            )

        return parsed.astimezone(timezone)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def normalise_location(location: str) -> str:
    location = clean(location).replace(
        "\xa0",
        " ",
    )

    # Example:
    # Hossack Reserve-Pitch A
    # becomes:
    # Hossack Reserve — Pitch A
    location = re.sub(
        r"\s*[-–—]\s*(Field|Pitch|Court)\s*",
        r" — \1 ",
        location,
        flags=re.IGNORECASE,
    )

    return re.sub(
        r"\s+",
        " ",
        location,
    ).strip(" -–—")


def is_invalid_location(candidate: str) -> bool:
    if not candidate:
        return True

    if candidate.lower() == "match centre":
        return True

    if candidate.startswith(
        (
            "Round ",
            "Match ID:",
            "Age Group:",
        )
    ):
        return True

    if candidate in {
        "-",
        "Bye",
        "B",
    }:
        return True

    if re.fullmatch(
        r"\d+\s*:\s*\d+",
        candidate,
    ):
        return True

    if re.search(
        r"\b(?:AM|PM|AWST|AEST|ACST)\b",
        candidate,
        re.IGNORECASE,
    ):
        return True

    return False


def locations_from_page_text(
    body_text: str,
) -> dict[str, str]:
    """
    Match each Squadi Match ID to the full venue displayed
    on the fixture card.
    """

    lines = [
        line.strip().replace("\xa0", " ")
        for line in body_text.splitlines()
        if line.strip()
    ]

    locations: dict[str, str] = {}

    for index, line in enumerate(lines):
        match = re.fullmatch(
            r"Match ID:\s*(\d+)",
            line,
        )

        if not match:
            continue

        match_id = match.group(1)

        window = lines[
            max(0, index - 20):index
        ]

        full_venue = ""
        surface_only = ""

        for raw_candidate in reversed(window):
            candidate = normalise_location(
                raw_candidate
            )

            if is_invalid_location(candidate):
                continue

            if VENUE_WORDS.search(candidate):
                full_venue = candidate
                break

            if (
                not surface_only
                and SURFACE_WORDS.search(candidate)
            ):
                surface_only = candidate

        location = full_venue or surface_only

        if location:
            locations[match_id] = location

    return locations


def escape_ics(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def fold_ics_line(line: str) -> str:
    """
    Split long iCalendar lines so Calendar apps can read them
    reliably.
    """

    if len(line) <= 73:
        return line

    parts = [line[:73]]
    remaining = line[73:]

    while remaining:
        parts.append(
            " " + remaining[:72]
        )

        remaining = remaining[72:]

    return "\r\n".join(parts)


def maps_search_url(location: str) -> str:
    if not location:
        return ""

    # Remove pitch, field or court so Waze searches for the reserve.
    reserve_name = re.sub(
        r"\s*[-–—]\s*(Pitch|Field|Court)\b.*$",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip()

    search_text = reserve_name or location

    query = quote_plus(
        f"{search_text}, Western Australia"
    )

    return (
        f"https://waze.com/ul?"
        f"q={query}&navigate=yes"
    )

    def squadi_match_url(
        team: dict[str, Any],
        match_id: str,
    ) -> str:
        """
        Return the specific Squadi match page.
    
        Fall back to the team's fixture page if no match ID is available.
        """
    
        if not match_id:
            return team["url"]
    
        competition_id = team.get("competition_id")
        competition_key = team.get("competition_unique_key")
    
        if not competition_id or not competition_key:
            return team["url"]
    
        return (
            "https://registration.squadi.com/matchSummary"
            f"?matchId={match_id}"
            f"&competitionId={competition_id}"
            f"&competitionUniqueKey={competition_key}"
        )

def short_team_name(team: str) -> str:
    """
    Examples:

    Armadale SC - U14 JDL D2 -> Armadale
    LUFC - U13 JCL SD1       -> LUFC
    Mindarie FC - U14 JDL D2 -> Mindarie
    """

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
    """
    Examples:

    14 -> Round 14
    Round 14 -> Round 14
    Round: Round 14 -> Round 14
    """

    round_text = clean(round_value)

    round_text = re.sub(
        r"^(?:round\s*:?\s*)+",
        "",
        round_text,
        flags=re.IGNORECASE,
    ).strip()

    if not round_text:
        return ""

    return f"Round {round_text}"


async def scrape_team(
    browser,
    team: dict[str, str],
    timezone: ZoneInfo,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    page = await browser.new_page(
        viewport={
            "width": 1440,
            "height": 1200,
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
            payloads.append(
                await response.json()
            )

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

    await page.goto(
        team["url"],
        wait_until="domcontentloaded",
        timeout=120_000,
    )

    await page.wait_for_timeout(
        12_000
    )

    await page.evaluate(
        "window.scrollTo("
        "0, document.body.scrollHeight"
        ")"
    )

    await page.wait_for_timeout(
        3_000
    )

    body_text = await page.locator(
        "body"
    ).inner_text()

    location_by_match_id = (
        locations_from_page_text(
            body_text
        )
    )

    fixtures: list[
        dict[str, Any]
    ] = []

    for payload in payloads:
        for obj in walk(payload):
            start = parse_datetime(
                first(
                    obj,
                    DATE_KEYS,
                ),
                timezone,
            )

            home = clean(
                first(
                    obj,
                    HOME_KEYS,
                )
                or first(
                    obj,
                    ("home", "team1"),
                )
            )

            away = clean(
                first(
                    obj,
                    AWAY_KEYS,
                )
                or first(
                    obj,
                    ("away", "team2"),
                )
            )

            if (
                not start
                or not home
                or not away
                or home == away
            ):
                continue

            source_id = clean(
                first(
                    obj,
                    ID_KEYS,
                )
            )
            
            match_url = squadi_match_url(
                team,
                source_id,
            )
            venue = normalise_location(
                clean(
                    first(
                        obj,
                        VENUE_KEYS,
                    )
                )
            )

            field = normalise_location(
                clean(
                    first(
                        obj,
                        FIELD_KEYS,
                    )
                )
            )

            page_location = (
                location_by_match_id.get(
                    source_id,
                    "",
                )
            )

            # Prefer the full location displayed on Squadi.
            if page_location:
                venue = page_location
                field = ""

            fixtures.append(
                {
                    "start": start,
                    "home": home,
                    "away": away,
                    "venue": venue,
                    "field": field,
                    "round": clean(
                        first(
                            obj,
                            ROUND_KEYS,
                        )
                    ),
                    "source_id": source_id,
                    "label": team["name"],
                    "source_url": match_url,
                }
            )

    await page.close()

    debug = {
        "team": team["name"],
        "responses": responses,
        "locations_found": (
            location_by_match_id
        ),
        "body_text_preview": (
            body_text[:8_000]
        ),
    }

    return fixtures, debug


def build_calendar(
    fixtures: list[dict[str, Any]],
    timezone_name: str,
) -> str:
    now = datetime.now(
        ZoneInfo("UTC")
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    match_minutes = int(
        CONFIG.get(
            "default_match_minutes",
            60,
        )
    )

    reminder_minutes = int(
        CONFIG.get(
            "reminder_minutes",
            90,
        )
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        (
            "PRODID:"
            "-//Family Soccer Calendar//EN"
        ),
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        (
            "X-WR-CALNAME:"
            + escape_ics(
                CONFIG["calendar_name"]
            )
        ),
        (
            "X-WR-TIMEZONE:"
            + timezone_name
        ),
        (
            "REFRESH-INTERVAL;"
            "VALUE=DURATION:PT1H"
        ),
        "X-PUBLISHED-TTL:PT1H",
    ]

    for fixture in fixtures:
        start = fixture["start"]

        end = start + timedelta(
            minutes=match_minutes
        )

        uid_seed = (
            f"{fixture['label']}|"
            f"{fixture['source_id']}|"
            f"{start.isoformat()}|"
            f"{fixture['home']}|"
            f"{fixture['away']}"
        )

        uid = (
            hashlib.sha256(
                uid_seed.encode("utf-8")
            )
            .hexdigest()[:24]
            + "@family-soccer-calendar"
        )

        location_parts: list[str] = []

        for part in (
            fixture["venue"],
            fixture["field"],
        ):
            if (
                part
                and part not in location_parts
            ):
                location_parts.append(
                    part
                )

        location = " — ".join(
            location_parts
        )

        maps_url = maps_search_url(
            location
        )

        round_text = format_round_text(
            fixture["round"]
        )

        # The teams are already in the title and the venue is
        # already in Location, so Notes contains only useful
        # extra information.
        description_lines = [
            round_text,
            (
                "Open in Squadi: "
                + fixture["source_url"]
            ),
        ]

        description = "\n".join(
            filter(
                None,
                description_lines,
            )
        )

        kickoff_time = (
        start.strftime("%I:%M%p")
        .lstrip("0")
        .lower()
        )
        
        title = (
            f"⚽ {fixture['label']} | "
            f"{short_team_name(fixture['home'])} "
            f"vs {short_team_name(fixture['away'])} "
            f"| KO {kickoff_time}"
        )

        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            (
                f"DTSTART;"
                f"TZID={timezone_name}:"
                f"{start.strftime('%Y%m%dT%H%M%S')}"
            ),
            (
                f"DTEND;"
                f"TZID={timezone_name}:"
                f"{end.strftime('%Y%m%dT%H%M%S')}"
            ),
            (
                "SUMMARY:"
                + escape_ics(title)
            ),
            (
                "LOCATION:"
                + escape_ics(location)
            ),
        ]

        # Calendar displays this as the event's Open link.
        if maps_url:
            event_lines.append(
                f"URL:{maps_url}"
            )

        event_lines.extend(
            [
                (
                    "DESCRIPTION:"
                    + escape_ics(
                        description
                    )
                ),
                "STATUS:CONFIRMED",
                "BEGIN:VALARM",
                (
                    f"TRIGGER:"
                    f"-PT{reminder_minutes}M"
                ),
                "ACTION:DISPLAY",
                (
                    "DESCRIPTION:"
                    + escape_ics(
                        f"{fixture['label']} "
                        "fixture reminder"
                    )
                ),
                "END:VALARM",
                "END:VEVENT",
            ]
        )

        lines.extend(
            event_lines
        )

    lines.append(
        "END:VCALENDAR"
    )

    return (
        "\r\n".join(
            fold_ics_line(line)
            for line in lines
        )
        + "\r\n"
    )


async def main() -> None:
    timezone = ZoneInfo(
        CONFIG["timezone"]
    )

    all_fixtures: list[
        dict[str, Any]
    ] = []

    debug_teams: list[
        dict[str, Any]
    ] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True
        )

        for team in CONFIG["teams"]:
            fixtures, debug = await scrape_team(
                browser,
                team,
                timezone,
            )

            all_fixtures.extend(
                fixtures
            )

            debug_teams.append(
                debug
            )

        await browser.close()

    unique: dict[
        tuple[str, str, str, str],
        dict[str, Any],
    ] = {}

    for fixture in all_fixtures:
        key = (
            fixture["label"],
            fixture["start"].isoformat(),
            fixture["home"].lower(),
            fixture["away"].lower(),
        )

        unique[key] = fixture

    fixtures = sorted(
        unique.values(),
        key=lambda item: item["start"],
    )

    DEBUG.write_text(
        json.dumps(
            {
                "generated_at": (
                    datetime.now(
                        timezone
                    ).isoformat()
                ),
                "fixture_count": len(
                    fixtures
                ),
                "teams": debug_teams,
                "fixtures": [
                    {
                        **fixture,
                        "start": (
                            fixture[
                                "start"
                            ].isoformat()
                        ),
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
            "No fixtures were detected. "
            "Open docs/debug.json for details."
        )

    OUTPUT.write_text(
        build_calendar(
            fixtures,
            CONFIG["timezone"],
        ),
        encoding="utf-8",
    )

    print(
        f"Wrote {len(fixtures)} "
        f"fixtures to {OUTPUT}"
    )


if __name__ == "__main__":
    asyncio.run(main())
