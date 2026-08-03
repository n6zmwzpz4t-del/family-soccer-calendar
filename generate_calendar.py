from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())
OUT = ROOT / "docs" / "fixtures.ics"
DEBUG = ROOT / "docs" / "debug.json"

DATE_KEYS = (
    "fixtureDate", "matchDate", "gameDate", "startDate", "startDateTime",
    "dateTime", "startTime", "scheduledDate", "date"
)
HOME_KEYS = ("homeTeamName", "homeTeam", "team1Name", "homeName")
AWAY_KEYS = ("awayTeamName", "awayTeam", "team2Name", "awayName")
VENUE_KEYS = (
    "venueName", "venue", "groundName", "locationName", "ground",
    "venueCourtName", "venueCourt", "subVenueName", "courtVenueName"
)
FIELD_KEYS = (
    "fieldName", "courtName", "pitchName", "field", "court", "pitch",
    "venueCourtName", "subVenueName"
)
ROUND_KEYS = ("roundName", "round", "roundNumber", "fixtureRound")
ID_KEYS = ("fixtureId", "gameId", "matchId", "id", "uniqueKey")


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in (
            "name", "displayName", "teamName", "title", "label", "value",
            "venueName", "courtName"
        ):
            if key in value and value[key] not in (None, ""):
                return clean(value[key])
        return ""
    if isinstance(value, list):
        return ", ".join(filter(None, (clean(item) for item in value)))
    return re.sub(r"\s+", " ", str(value)).strip()


def first(obj: dict, keys):
    lower = {str(key).lower(): value for key, value in obj.items()}
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        if key.lower() in lower and lower[key.lower()] not in (None, ""):
            return lower[key.lower()]
    return None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def parse_dt(value, timezone):
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, timezone)

        parsed = dateparser.parse(clean(value), dayfirst=False)
        if not parsed:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except Exception:
        return None


def normalise_location(location: str) -> str:
    location = clean(location).replace("\xa0", " ")
    # Make common Squadi venue/field combinations easier to read.
    location = re.sub(
        r"\s*-\s*(Field|Pitch|Court)\s*",
        r" — \1 ",
        location,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", location).strip(" -—")


def locations_from_page_text(body_text: str) -> dict[str, str]:
    """Map each Squadi Match ID to the venue line shown on the public page."""
    lines = [line.strip().replace("\xa0", " ") for line in body_text.splitlines()]
    locations: dict[str, str] = {}

    for index, line in enumerate(lines):
        match = re.fullmatch(r"Match ID:\s*(\d+)", line)
        if not match:
            continue

        match_id = match.group(1)
        cursor = index - 1

        # The line immediately before Match ID is normally "Match Centre".
        while cursor >= 0 and (
            not lines[cursor]
            or lines[cursor].lower() == "match centre"
        ):
            cursor -= 1

        if cursor < 0:
            continue

        candidate = normalise_location(lines[cursor])

        # Avoid accidentally treating a score, round or team name as a venue.
        invalid = (
            not candidate
            or candidate.startswith("Round ")
            or candidate.startswith("Match ID:")
            or candidate in {"-", "Bye", "B"}
            or re.fullmatch(r"\d+\s*:\s*\d+", candidate)
        )
        if not invalid:
            locations[match_id] = candidate

    return locations


def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


async def scrape(browser, team, timezone):
    page = await browser.new_page(viewport={"width": 1440, "height": 1200})
    payloads = []
    responses = []

    async def capture(response):
        if "json" not in (response.headers.get("content-type") or "").lower():
            return
        try:
            payloads.append(await response.json())
            responses.append({"url": response.url, "status": response.status})
        except Exception:
            pass

    page.on("response", capture)
    await page.goto(team["url"], wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_timeout(12000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(3000)

    body_text = await page.locator("body").inner_text()
    location_by_match_id = locations_from_page_text(body_text)
    preview = body_text[:8000]
    await page.close()

    found = []
    for payload in payloads:
        for obj in walk(payload):
            start = parse_dt(first(obj, DATE_KEYS), timezone)
            home = clean(first(obj, HOME_KEYS) or first(obj, ("home", "team1")))
            away = clean(first(obj, AWAY_KEYS) or first(obj, ("away", "team2")))

            if not start or not home or not away or home == away:
                continue

            source_id = clean(first(obj, ID_KEYS))
            venue = clean(first(obj, VENUE_KEYS))
            field = clean(first(obj, FIELD_KEYS))

            # Squadi's visible match card is the reliable fallback when the API
            # object does not expose its venue under a predictable field name.
            page_location = location_by_match_id.get(source_id, "")
            if not venue and page_location:
                venue = page_location
                field = ""

            found.append(
                {
                    "start": start,
                    "home": home,
                    "away": away,
                    "venue": normalise_location(venue),
                    "field": normalise_location(field),
                    "round": clean(first(obj, ROUND_KEYS)),
                    "source_id": source_id,
                    "label": team["name"],
                    "url": team["url"],
                }
            )

    return found, {
        "team": team["name"],
        "responses": responses,
        "locations_found": location_by_match_id,
        "body_text_preview": preview,
    }


def build(fixtures, timezone_name):
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Family Soccer Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(CONFIG['calendar_name'])}",
        f"X-WR-TIMEZONE:{timezone_name}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]

    for fixture in fixtures:
        start = fixture["start"]
        end = start + timedelta(minutes=int(CONFIG["default_match_minutes"]))
        uid = (
            hashlib.sha256(
                (
                    f"{fixture['label']}|{fixture['source_id']}|"
                    f"{start.isoformat()}|{fixture['home']}|{fixture['away']}"
                ).encode()
            ).hexdigest()[:24]
            + "@family-soccer-calendar"
        )

        location_parts = []
        for part in (fixture["venue"], fixture["field"]):
            if part and part not in location_parts:
                location_parts.append(part)
        location = " — ".join(location_parts)

        description = "\n".join(
            filter(
                None,
                [
                    fixture["label"],
                    f"Round: {fixture['round']}" if fixture["round"] else "",
                    f"{fixture['home']} vs {fixture['away']}",
                    fixture["url"],
                ],
            )
        )

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID={timezone_name}:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={timezone_name}:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{esc(fixture['label'] + ' | ' + fixture['home'] + ' vs ' + fixture['away'])}",
            f"LOCATION:{esc(location)}",
            f"DESCRIPTION:{esc(description)}",
            "STATUS:CONFIRMED",
            "BEGIN:VALARM",
            "TRIGGER:-PT90M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(fixture['label'] + ' fixture in 90 minutes')}",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


async def main():
    timezone = ZoneInfo(CONFIG["timezone"])
    all_fixtures = []
    debug_teams = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        for team in CONFIG["teams"]:
            fixtures, debug = await scrape(browser, team, timezone)
            all_fixtures += fixtures
            debug_teams.append(debug)
        await browser.close()

    unique = {}
    for fixture in all_fixtures:
        unique[
            (
                fixture["label"],
                fixture["start"].isoformat(),
                fixture["home"].lower(),
                fixture["away"].lower(),
            )
        ] = fixture

    fixtures = sorted(unique.values(), key=lambda item: item["start"])

    DEBUG.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone).isoformat(),
                "fixture_count": len(fixtures),
                "teams": debug_teams,
                "fixtures": [
                    {**fixture, "start": fixture["start"].isoformat()}
                    for fixture in fixtures
                ],
            },
            indent=2,
        )
    )

    if not fixtures:
        raise RuntimeError(
            "No fixtures were detected. Open docs/debug.json for details."
        )

    OUT.write_text(build(fixtures, CONFIG["timezone"]))
    print(f"Wrote {len(fixtures)} fixtures")


if __name__ == "__main__":
    asyncio.run(main())
