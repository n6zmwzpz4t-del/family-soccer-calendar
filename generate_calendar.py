from __future__ import annotations
import asyncio, hashlib, json, re
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

DATE_KEYS=("fixtureDate","matchDate","gameDate","startDate","startDateTime","dateTime","startTime","scheduledDate","date")
HOME_KEYS=("homeTeamName","homeTeam","team1Name","homeName")
AWAY_KEYS=("awayTeamName","awayTeam","team2Name","awayName")
VENUE_KEYS=("venueName","venue","groundName","locationName","ground")
FIELD_KEYS=("fieldName","courtName","pitchName","field","court","pitch")
ROUND_KEYS=("roundName","round","roundNumber","fixtureRound")
ID_KEYS=("fixtureId","gameId","matchId","id","uniqueKey")

def clean(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, dict):
        for k in ("name","displayName","teamName","title","label","value"):
            if k in v and v[k] not in (None,""): return clean(v[k])
        return ""
    if isinstance(v, list): return ", ".join(filter(None,(clean(x) for x in v)))
    return re.sub(r"\s+"," ",str(v)).strip()

def first(o: dict, keys):
    low={str(k).lower():v for k,v in o.items()}
    for k in keys:
        if k in o and o[k] not in (None,""): return o[k]
        if k.lower() in low and low[k.lower()] not in (None,""): return low[k.lower()]

def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values(): yield from walk(x)
    elif isinstance(v,list):
        for x in v: yield from walk(x)

def parse_dt(v,tz):
    try:
        if isinstance(v,(int,float)):
            return datetime.fromtimestamp(v/1000 if v>10_000_000_000 else v,tz)
        d=dateparser.parse(clean(v),dayfirst=True)
        if not d: return None
        if d.tzinfo is None: d=d.replace(tzinfo=tz)
        return d.astimezone(tz)
    except Exception: return None

def esc(s): return s.replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

async def scrape(browser, team, tz):
    page=await browser.new_page(viewport={"width":1440,"height":1200})
    payloads=[]; responses=[]
    async def capture(r):
        if "json" not in (r.headers.get("content-type") or "").lower(): return
        try:
            payloads.append(await r.json()); responses.append({"url":r.url,"status":r.status})
        except Exception: pass
    page.on("response",capture)
    await page.goto(team["url"],wait_until="domcontentloaded",timeout=120000)
    await page.wait_for_timeout(12000)
    await page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
    await page.wait_for_timeout(3000)
    preview=(await page.locator("body").inner_text())[:8000]
    await page.close()
    found=[]
    for payload in payloads:
        for o in walk(payload):
            dt=parse_dt(first(o,DATE_KEYS),tz)
            home=clean(first(o,HOME_KEYS) or first(o,("home","team1")))
            away=clean(first(o,AWAY_KEYS) or first(o,("away","team2")))
            if not dt or not home or not away or home==away: continue
            found.append({"start":dt,"home":home,"away":away,"venue":clean(first(o,VENUE_KEYS)),"field":clean(first(o,FIELD_KEYS)),"round":clean(first(o,ROUND_KEYS)),"source_id":clean(first(o,ID_KEYS)),"label":team["name"],"url":team["url"]})
    return found,{"team":team["name"],"responses":responses,"body_text_preview":preview}

def build(fixtures,tzname):
    now=datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Family Soccer Calendar//EN","CALSCALE:GREGORIAN","METHOD:PUBLISH",f"X-WR-CALNAME:{esc(CONFIG['calendar_name'])}",f"X-WR-TIMEZONE:{tzname}","REFRESH-INTERVAL;VALUE=DURATION:PT1H","X-PUBLISHED-TTL:PT1H"]
    for f in fixtures:
        start=f["start"]; end=start+timedelta(minutes=int(CONFIG["default_match_minutes"]))
        uid=hashlib.sha256(f"{f['label']}|{f['source_id']}|{start.isoformat()}|{f['home']}|{f['away']}".encode()).hexdigest()[:24]+"@family-soccer-calendar"
        location=" — ".join(x for x in (f["venue"],f["field"]) if x)
        desc="\n".join(filter(None,[f["label"],f"Round: {f['round']}" if f["round"] else "",f"{f['home']} vs {f['away']}",f["url"]]))
        lines += ["BEGIN:VEVENT",f"UID:{uid}",f"DTSTAMP:{now}",f"DTSTART;TZID={tzname}:{start.strftime('%Y%m%dT%H%M%S')}",f"DTEND;TZID={tzname}:{end.strftime('%Y%m%dT%H%M%S')}",f"SUMMARY:{esc(f['label']+' | '+f['home']+' vs '+f['away'])}",f"LOCATION:{esc(location)}",f"DESCRIPTION:{esc(desc)}","STATUS:CONFIRMED","BEGIN:VALARM","TRIGGER:-PT90M","ACTION:DISPLAY",f"DESCRIPTION:{esc(f['label']+' fixture in 90 minutes')}","END:VALARM","END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)+"\r\n"

async def main():
    tz=ZoneInfo(CONFIG["timezone"]); allf=[]; dbg=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        for team in CONFIG["teams"]:
            f,d=await scrape(browser,team,tz); allf+=f; dbg.append(d)
        await browser.close()
    unique={}
    for f in allf: unique[(f["label"],f["start"].isoformat(),f["home"].lower(),f["away"].lower())]=f
    fixtures=sorted(unique.values(),key=lambda x:x["start"])
    DEBUG.write_text(json.dumps({"generated_at":datetime.now(tz).isoformat(),"fixture_count":len(fixtures),"teams":dbg,"fixtures":[{**f,"start":f["start"].isoformat()} for f in fixtures]},indent=2))
    if not fixtures: raise RuntimeError("No fixtures were detected. Open docs/debug.json for details.")
    OUT.write_text(build(fixtures,CONFIG["timezone"]))
    print(f"Wrote {len(fixtures)} fixtures")

if __name__ == "__main__": asyncio.run(main())
