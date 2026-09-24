"""Public SJBC calendar only. No SEQTA, email, AI, or private student data."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

PERTH = ZoneInfo('Australia/Perth')
# Same Timely calendar and term page used by calendar_digest.py/sjbc_sources.py.
FEED_URL = 'https://timelyapp.time.ly/api/calendars/54716732/export?format=ics&no_html=true'
TERM_URL = 'https://www.stjohnbosco.wa.edu.au/term-dates-and-day-structures/'
RELIGION = re.compile(r'\b(mass|eucharist\w*|confirmation|communion|reconciliation|liturgy|liturgies|liturgical|prayer|rosary|sacrament\w*|pentecost|lent|advent|ash wednesday|holy\s+\w+|catholic|religious education|rea|cpaf|archbishop|lifelink|vinnies|jubilee cross|ministry|retreat|loving for life|christmas|nativity|baptism|blessing|ascension|assumption|all saints|all souls|st[ .]*valentine.?s day|feast day|stations of the cross|sacramental)\b', re.I)
FRIENDS_MEETING = re.compile(r'\b(?:friends of st john bosco|fsjb)\b.*\bmeetings?\b|\bmeetings?\b.*\b(?:friends of st john bosco|fsjb)\b', re.I)
CLOSURE = re.compile(r'\b(student[ -]free|pupil[ -]free|staff development|professional development|teacher training)\b', re.I)
YEAR_PREFIX = r'(?:years?|yrs?|y)\s*'
YEAR_GROUP = re.compile(r'\b'+YEAR_PREFIX+r'(\d{1,2}(?:(?:\s*(?:-|–|—|to|&|and|,|/|\+)\s*)(?:'+YEAR_PREFIX+r')?\d{1,2})*)', re.I)
CLASS = re.compile(r'\b(?:year\s*|yr\s*|class\s*)?6\s+(teal|purple|blue|green|red|gold|white|orange)\b', re.I)
MONTHS = 'January February March April May June July August September October November December'.split()
MONTH_PATTERN = '|'.join(m+'|'+m[:3] for m in MONTHS)
DATE_PATTERN = re.compile(r'\b('+MONTH_PATTERN+r')\s+(\d{1,2})(?:st|nd|rd|th)?\b', re.I)


def download(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'sjbc-family-calendar/1.0'})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise ValueError('School response exceeds size limit')
            return data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def plain(value):
    return BeautifulSoup(str(value or ''), 'html.parser').get_text(' ', strip=True)


def display_title(title):
    # Timely sometimes publishes its event titles in capitals. Calendar apps
    # control the actual font, but the subscription controls title casing.
    if not title.isupper():
        return title
    small = {'and', 'at', 'by', 'for', 'from', 'in', 'of', 'on', 'the', 'to', 'with'}
    acronyms = {'ACC', 'ATAR', 'ANZAC', 'NAPLAN', 'OLNA', 'SJBC', 'WA', 'WACE', 'SEAS', 'STEM', 'PP'}
    words = title.title()
    def case_word(match):
        word = match.group(0)
        upper = word.upper()
        if upper in acronyms:
            return upper
        if word.lower() in small and match.start() != 0:
            return word.lower()
        return word
    return re.sub(r'\b[A-Za-z]+\b', case_word, words)


def years_in(text):
    result = set()
    for match in YEAR_GROUP.finditer(text):
        part = match.group(1)
        result.update(int(n) for n in re.findall(r'\d+', part))
        for a, b in re.findall(r'(\d+)\s*(?:-|–|—|to)\s*(?:'+YEAR_PREFIX+r')?(\d+)', part, re.I):
            result.update(range(int(a), int(b)+1))
    # Kindy/PP through a year is an inclusive range, not only the last year.
    for n in re.findall(r'\b(?:kindergarten|kindy|pre-primary|pp)\s*(?:to|-|–)\s*(?:year\s*)?(\d+)', text, re.I):
        result.update(range(0, int(n)+1))
    return result


def children_for(config, year):
    offset = year - config['base_year'] if config.get('advance_year_levels') else 0
    return [{**c, 'year': c['year']+offset, 'class': c.get('class') if offset == 0 else None}
            for c in config['children'] if 0 <= c['year']+offset <= 12]


def tags_of(event):
    value = event.get('CATEGORIES')
    if isinstance(value, list):
        categories = ','.join(str(x.to_ical().decode()) for x in value)
    else:
        categories = value.to_ical().decode() if value else ''
    return categories + ',' + str(event.get('X-TAGS', ''))


def audience(event, config, year):
    title, desc, tags = plain(event.get('SUMMARY')), plain(event.get('DESCRIPTION')), tags_of(event)
    title_classes = {c.lower() for c in CLASS.findall(title)}
    scopes = years_in(title) or years_in(tags)
    if not scopes and re.search(r'selected students|for (?:students|years)|students from', desc, re.I):
        scopes = years_in(desc)
    # Descriptions often mention meeting locations in other year-level rooms.
    # Use title/tags for cohort scope; never mistake a room for an audience.
    primary = bool(re.search(r'\bprimary\b', title+' '+tags, re.I))
    secondary = bool(re.search(r'\b(?:secondary|high school)\b', title+' '+tags, re.I))
    whole = bool(re.search(r'whole (?:college|school)|all students|all families', title+' '+tags, re.I))
    if re.search(r'\b(girls|mother.?daughter|big sister)\b', title, re.I):
        return []
    if re.search(r'\b(atar|wace)\b', title, re.I) and not scopes:
        scopes = {11, 12}
    if re.search(r'\bnaplan\b', title, re.I) and not scopes:
        scopes = {3, 5, 7, 9}
    if re.search(r'\bolna\b', title, re.I) and not scopes:
        return []  # Eligibility must be supplied by the school.
    if re.search(r'pre-kindergarten|kindergarten|\bkindy\b|pre-primary|mums?\s*(?:&|and)\s*bubs|college tour', title, re.I) and not scopes:
        return []
    eligible = []
    for child in children_for(config, year):
        grade = child['year']
        if scopes and grade not in scopes:
            continue
        if title_classes and grade == 6 and (not child.get('class') or child['class'].lower() not in title_classes):
            continue
        if not scopes:
            if primary and not secondary and grade > 6:
                continue
            if secondary and not primary and grade < 7:
                continue
            if not (primary or secondary or whole or CLOSURE.search(title)):
                # Include genuinely general family events, not unidentified teams.
                if not re.search(r'book (?:week|fair)|uniform shop|parent.*interview|learning journey|disco|photo|father.?s day|mother.?s day|school holiday|term\s*\d|student.*commence|student.*conclude|teacher appreciation|friends of st john bosco', title, re.I):
                    continue
        eligible.append(child['name'])
    return eligible


def date_only(value):
    return value.astimezone(PERTH).date() if isinstance(value, datetime) else value


def clean_description(value):
    soup = BeautifulSoup(str(value or ''), 'html.parser')
    lines = soup.get_text('\n', strip=True).splitlines()
    # Never leak another Year 6 class's time or instructions into Tate's event.
    return '\n'.join(line for line in lines if not any(c.lower() != 'teal' for c in CLASS.findall(line)))


def normalise_feed(raw, config, now):
    source = Calendar.from_ical(raw)
    events = source.walk('VEVENT')
    if not events:
        raise ValueError('School feed contains no events; previous feed preserved')
    output, exclusions = [], []
    for original in events:
        if not original.get('UID') or not original.get('DTSTART') or not original.get('SUMMARY'):
            raise ValueError('School feed has an incomplete event')
        start = date_only(original.decoded('DTSTART'))
        title = plain(original.get('SUMMARY'))
        if start.year < now.year and not any(original.get(k) for k in ('RRULE', 'RDATE')):
            continue
        if start.year > now.year+1:
            continue
        closed = bool(CLOSURE.search(title))
        if FRIENDS_MEETING.search(title):
            exclusions.append({'title': title, 'reason': 'Friends of St John Bosco meeting'})
            continue
        if not closed and RELIGION.search(title+' '+tags_of(original)):
            exclusions.append({'title': title, 'reason': 'religious'})
            continue
        # The term page supplies authoritative, child-specific boundaries.
        if re.search(r'\bterm\s*[1-4]\b', title, re.I) and re.search(r'commence|conclude|start|end', title, re.I) and not re.search(r'pre-kindergarten|administration', title, re.I):
            continue
        names = audience(original, config, max(now.year, start.year))
        if not names:
            exclusions.append({'title': title, 'reason': 'other or unspecified cohort'})
            continue
        event = Event()
        # Explicit public-data allowlist, including all recurrence information.
        for key in ('UID', 'DTSTART', 'DTEND', 'DURATION', 'RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID', 'STATUS', 'LOCATION', 'URL'):
            if key in original:
                event[key] = copy.deepcopy(original[key])
        event.add('summary', ('Student-free day' if closed else display_title(title)) + ' — ' + ' & '.join(names))
        event.add('description', 'Applies to: '+ ' and '.join(names) + '.\n' +
                  ('No school for students.' if closed else clean_description(original.get('DESCRIPTION'))))
        output.append(event)
    return output, exclusions


def dates_in(text, year):
    return [date(year, next(i for i,m in enumerate(MONTHS,1) if m.lower().startswith(month.lower())), int(day))
            for month,day in DATE_PATTERN.findall(text)]


def make_event(key, title, start, end, names, description=''):
    event = Event()
    event.add('uid', 'sjbc-'+key+'@family-school-calendar')
    event.add('summary', title+' — '+' & '.join(names))
    event.add('dtstart', start)
    event.add('dtend', end or start+timedelta(days=1))
    event.add('description', description or 'Applies to: '+' and '.join(names)+'.')
    event.add('url', TERM_URL)
    return event


def term_events(html, config, now):
    soup = BeautifulSoup(html, 'html.parser')
    output = []
    term_counts = {}
    for heading in soup.select('.et_pb_toggle_title'):
        heading_text = heading.get_text(' ', strip=True)
        match = re.match(r'(20\d{2})\s+(.+)', heading_text)
        if not match:
            continue
        year, section = int(match[1]), match[2].lower()
        if not now.year <= year <= now.year+1:
            continue
        block = heading.find_next_sibling()
        if block is None:
            raise ValueError('Term-page layout changed')
        text = block.get_text(' ', strip=True)
        children = children_for(config, year)
        names = [c['name'] for c in children]
        if not names:
            continue
        if section == 'term dates':
            starts = {}
            for li in block.select('li'):
                line = li.get_text(' ', strip=True)
                ds = dates_in(line, year)
                if 'commence' in line.lower() and ds:
                    for child in children:
                        if child['year'] in years_in(line):
                            starts[child['name']] = ds[0]
            count = 0
            for m in re.finditer(r'\bTerm (One|Two|Three|Four)\s+(.+?)(?=\bTerm (?:One|Two|Three|Four)|There will|$)', text.split('There will')[0]):
                number = ['One','Two','Three','Four'].index(m[1])+1
                ds = dates_in(m[2], year)
                if len(ds) < 2:
                    raise ValueError('Missing term boundary')
                count += 1
                start_groups = {}
                for child in children:
                    start = starts.get(child['name'], ds[0]) if number == 1 else ds[0]
                    start_groups.setdefault(start, []).append(child['name'])
                for start, who in start_groups.items():
                    output.append(make_event(f'{year}-term{number}-start-'+ '-'.join(who).lower(),f'First day of Term {number}',start,None,who))
                output.append(make_event(f'{year}-term{number}-end',f'Last day of Term {number}',ds[1],None,names))
            term_counts[year] = count
        elif section == 'student free days':
            for d in dates_in(text, year):
                output.append(make_event(f'student-free-{d}', 'Student-free day', d, None, names, 'No school for students.'))
        elif section == 'public holidays during term time':
            for d in dates_in(text, year):
                output.append(make_event(f'public-holiday-{d}', 'Public holiday — school closed', d, None, names))
        elif section == 'secondary examinations':
            active_grade = None
            for p in block.select('p'):
                line = p.get_text(' ', strip=True)
                grade = re.fullmatch(r'Year (\d+) Exams', line, re.I)
                if grade:
                    active_grade = int(grade[1]); continue
                ds = dates_in(line, year)
                if active_grade and len(ds) == 2:
                    who = [c['name'] for c in children if c['year'] == active_grade]
                    if who:
                        output.append(make_event(f'{year}-exams-y{active_grade}-{ds[0]}',f'Year {active_grade} exams',ds[0],ds[1]+timedelta(days=1),who,'School examination window; consult the subject timetable for individual exam times.'))
        elif section == 'parent teacher student interviews':
            for p in block.select('p'):
                line = p.get_text(' ', strip=True)
                ds = dates_in(line, year)
                scope = years_in(line.split('STUDY DAY')[0])
                who = [c['name'] for c in children if c['year'] in scope]
                if ds and who:
                    clock = re.search(r'\((\d{1,2})(?::(\d{2}))?(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?(am|pm)\)',line,re.I)
                    start, end = ds[0], None
                    if clock:
                        a,am,ap,b,bm,bp = clock.groups()
                        start = datetime.combine(ds[0],datetime.min.time(),PERTH).replace(hour=int(a)%12+(12 if ap.lower()=='pm' else 0),minute=int(am or 0))
                        end = start.replace(hour=int(b)%12+(12 if bp.lower()=='pm' else 0),minute=int(bm or 0))
                    output.append(make_event(f'interviews-{ds[0]}','Parent–teacher–student interviews',start,end,who))
    if term_counts.get(now.year) != 4:
        raise ValueError(f'Could not verify all four terms for {now.year}; previous feed preserved')
    return output


def fingerprint(event):
    clone = copy.deepcopy(event)
    for key in ('DTSTAMP','LAST-MODIFIED','SEQUENCE','CREATED'):
        clone.pop(key, None)
    return hashlib.sha256(clone.to_ical()).hexdigest()


def build(raw, html, config, now, previous=None):
    events, exclusions = normalise_feed(raw, config, now)
    terms = term_events(html, config, now)
    # Term-page closures replace duplicate Timely entries on the same date.
    closures = {date_only(e.decoded('DTSTART')) for e in terms if 'Student-free day' in str(e['SUMMARY'])}
    events = [e for e in events if not ('Student-free day' in str(e['SUMMARY']) and date_only(e.decoded('DTSTART')) in closures)]
    for term in terms:
        day = date_only(term.decoded('DTSTART'))
        title = str(term['SUMMARY'])
        if title.startswith('First day'):
            duplicate = r'students? commence'
        elif title.startswith('Public holiday'):
            duplicate = r'public holiday|college closed'
        elif title.startswith('Parent–teacher'):
            duplicate = r'parent.*teacher.*interview'
        else:
            continue
        events = [e for e in events if not (date_only(e.decoded('DTSTART')) == day and re.search(duplicate,str(e['SUMMARY']),re.I))]
    events += terms
    seen, unique = set(), []
    for event in events:
        key = (str(event['UID']),str(event.get('RECURRENCE-ID','')))
        if key not in seen:
            unique.append(event); seen.add(key)
    old = {(str(e['UID']),str(e.get('RECURRENCE-ID',''))):e for e in previous.walk('VEVENT')} if previous else {}
    cal = Calendar()
    for key,value in [('version','2.0'),('prodid','-//SJBC Family Digest//School calendar//EN'),('calscale','GREGORIAN'),('method','PUBLISH'),('x-wr-calname',config['calendar_name']),('x-wr-timezone','Australia/Perth'),('x-published-ttl','PT2H')]:
        cal.add(key,value)
    cal.add('refresh-interval',timedelta(hours=2),parameters={'VALUE':'DURATION'})
    for zone in Calendar.from_ical(raw).walk('VTIMEZONE'):
        cal.add_component(copy.deepcopy(zone))
    for event in sorted(unique,key=lambda e:(date_only(e.decoded('DTSTART')),str(e['UID']))):
        prior = old.get((str(event['UID']),str(event.get('RECURRENCE-ID',''))))
        unchanged = prior is not None and fingerprint(event)==fingerprint(prior)
        stamp = prior.decoded('DTSTAMP') if unchanged else now.astimezone(timezone.utc)
        event.add('dtstamp',stamp)
        event.add('last-modified',stamp)
        event.add('sequence',int(prior.get('SEQUENCE',0))+(0 if unchanged else 1) if prior else 0)
        cal.add_component(event)
    if not unique:
        raise ValueError('Refusing to publish an empty calendar')
    return cal, {'generated_at':now.isoformat(),'event_count':len(unique),'excluded':exclusions,'sources':[FEED_URL,TERM_URL]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-ics',type=Path)
    parser.add_argument('--term-html',type=Path)
    parser.add_argument('--output',type=Path,default=Path('output/school.ics'))
    parser.add_argument('--config',type=Path,default=Path('config/school-calendar.json'))
    args = parser.parse_args()
    now = datetime.now(PERTH)
    raw = args.source_ics.read_bytes() if args.source_ics else download(FEED_URL)
    html = args.term_html.read_bytes() if args.term_html else download(TERM_URL)
    previous = Calendar.from_ical(args.output.read_bytes()) if args.output.exists() else None
    cal, report = build(raw,html,json.loads(args.config.read_text()),now,previous)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    data = cal.to_ical()
    Calendar.from_ical(data)  # Validate before replacing the last good copy.
    temporary = args.output.with_suffix('.ics.tmp')
    temporary.write_bytes(data); temporary.replace(args.output)
    args.output.with_suffix('.report.json').write_text(json.dumps(report,indent=2))
    print(f'Built {report["event_count"]} public school events; excluded {len(report["excluded"])}.')

if __name__ == '__main__':
    main()
