# School calendar runtime

Source project: https://github.com/n6zmwzpz4t-del/sjbc-family-digest

This is the deployed copy of that project's public-school calendar generator.
Only public Timely and school term-date data are used. Private student data,
SEQTA, emails and the digest are not copied into this repository.

Cron-job.org dispatches `.github/workflows/school-calendar.yml` every two hours.
It updates `docs/school.ics` using this repository's built-in workflow token.
The sports refresh is independent. Keep this deployment copy synchronised when
changing the generator in sjbc-family-digest.

Subscribe: https://n6zmwzpz4t-del.github.io/family-soccer-calendar/school.ics
Direct feed: https://raw.githubusercontent.com/n6zmwzpz4t-del/family-soccer-calendar/main/docs/school.ics
