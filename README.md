# Family Soccer Calendar

Checks Tate and Finn's Squadi pages hourly and publishes one combined Apple Calendar feed.

The same refresh also checks Tate's Thornlie TeeBall draw and The Proper Player's
2026 six-a-side draw and public scores. Finn plays U14 The Army; Tate plays U12
The Academy. Their separate 6-a-side website tabs show team fixtures, division
results and the full division ladder. The ladder follows the league's own
rules: 3 points for a win, 1 for a draw, then goal difference and goals scored.

`sixaside.py` reads the `data.js` and public Firebase score endpoint used by
https://tpp-6aside.netlify.app/ (the online league shown on the Proper Player site).
`docs/sixaside.json` retains the last valid draw and scores when either feed is
unavailable. The refresh workflow publishes changes to this file even if only
another team's result or ladder position changes. Existing calendar event UIDs
are retained when games move, change pitch, or replace a finals placeholder;
withdrawn games are published as cancelled. December 14 finals remain tentative
until a team-specific draw is published. The subscription URL stays the same.

Calendar URL after GitHub Pages is enabled:

`https://n6zmwzpz4t-del.github.io/family-soccer-calendar/fixtures.ics`

## Publish with GitHub Desktop

1. Unzip the package.
2. In GitHub Desktop choose **File > Add Local Repository**.
3. Select the `family-soccer-calendar` folder.
4. If prompted, choose **create a repository here**.
5. Commit all files, then click **Publish repository**.
6. Name it `family-soccer-calendar` and untick **Keep this code private**.

## Enable the hourly workflow

On github.com, open the repository and choose **Actions > Refresh family soccer calendar > Run workflow**.

## Enable GitHub Pages

Open **Settings > Pages**. Choose **Deploy from a branch**, branch `main`, folder `/docs`, then Save.
