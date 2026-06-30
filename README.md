# Information that the report was referring to
**Keyword-matching logic and per-platform scraper configuration:**

The keywords.csv contained 7 words from vaccination (vaccination, vaccine, selective vaccine schedule, pharma vaccine lying, vaccine autism parent group, vaccine death data, vaccine less than natural immunity) and 7 words from fluoridation (fluoridation, fluoride, fluoride free australia, fluoride water filter, fluoride byproduct, fluoride thyroid, mass medication fluoride).

The keyword matching mechanism across all 3 social media site’s scrapers is as follows: each keyword is split into individual words, and it counts as a match only if every one of those words appears somewhere in the (lowercased, by default) text as a substring, regardless of order, adjacency, or word boundaries. So a multi-word keyword like “fluoride free australia” matches whenever all “fluoride”, “free”, and “australia” appear anywhere in the text, and single words match even inside larger words, such as “free” would match “freedom”.

For Reddit, the scraper searches the title and body text of the post, and if there’s a keyword hit in the post, the scraper will also fetch and count keyword hits in the comments. For YouTube, the scraper searches the title and description of up to 25 most recent videos per keyword searched in the searchbar, and if there’s a keyword hit in that post, the scraper makes a comment call and counts keyword hits for up to 100 top-level comments. For Google Alerts, the scraper reads each RSS feed and records every new article the alert returns. “google_monitor.py” scans the article’s title and summary against the shared keyword list to populate the relevance columns, but unlike Reddit and YouTube, there’s no keyword gate as the alert’s own keyword already qualifies the item, so every new entry is logged.


**Challenge:**
The prototype's data pipeline changed substantially mid-project, creating a data gap and some structural complexity worth noting. These iterations explain a structural quirk: the "Reddit" tab feeds a separate "Reddit Uniq" tab before reaching "Master2." I deduplicated in a separate tab rather than risk breaking the live pipeline by deduplicating in place.

**Recommendations and Future Work in refining pipeline:**
1. Aggregate the Master2 tab at the scraper step: The current information flow is that each platform has its own scraper, each scraper uploads to its own platform tab in Google Sheets, and the Master tab is then assembled as an aggregate of those individual tabs. Ideally, the aggregation into the Master tab would happen directly at the scraper step rather than as a downstream consolidation.

2. Resolve the known duplicate issue in the Reddit data: Early tests and reruns of the Reddit monitor produced duplicate entries. These have been deduplicated in the "Reddit Uniq" tab of the "Prototype" spreadsheet, but be aware that results_all.csv on GitHub still contains the duplicates and should be cleaned before reuse.

3. Split the platform cell in the "Emerging Terms" tab: At present, the platforms for each term are listed together in a single cell, separated by commas. Splitting these into one platform per cell would allow a term- × platform heatmap, making it easy to see which terms are emerging on which platforms.

4. Split the keywords_matched cell in "Master2": This cell currently combines all matched keywords together. I recommend splitting it into individual keyword matches, but not having that new field wholly replace the existing one. It would be good to have both fields to retain the topic-level view while gaining the ability to drill into any single term.
a. agg_keyword_match (the current keywords_matched): preserves which combinations of keywords appear together, giving a view of topics by keyword co-occurrence.
b. individual_keyword_match (the proposed new field): breaks matches out one keyword per row, enabling trend analysis for a single specific keyword (for example, tracking it by author or platform over time).

# Systems diagram as of 1st July
![There is a Python script that analyses the Master2 tab, and aims to capture emerging misinformation trends by logging the words that are not in the keyword list but are appearing in collated titles. The Google Sheet connects to Google Data Studio to display the data as charts on a dashboard.](newdiagram.png)


# Maintenance Manual
(I note that this manual was written with the help of AI, but I want to note that I have checked the details to make sure they are accurate.)

This repository holds the surveillance prototype described in the research report
*"Low-cost misinformation tracking for vaccination and fluoridation in Australia"*
(Elizabeth Pham, SCIE30001, 2026). It automatically collects posts and articles
about fluoridation and vaccination from **Reddit, YouTube, and Google Alerts**, and
writes them into a Google Sheet that feeds a live dashboard.

This guide is written for whoever maintains the tool next. It is in two parts:

- **Part A — Operating the tool** (no coding needed): what it does, where things
  live, and how to change what's being monitored.
- **Part B — Under the hood** (some Python/GitHub knowledge needed): how the scripts
  work, how the automation runs, and how to fix things when they break.

An honest note up front: *operating* this tool (reading the dashboard, editing the
keyword and source lists) needs no coding. But *fixing* it when something breaks —
an expired login, a website changing its rules — needs someone comfortable with
Python and GitHub. Budget for that when planning who takes this over.

---

## PART A — OPERATING THE TOOL

### What the system does, in one paragraph

Three Python scripts run automatically every day on GitHub. Each one searches a
different place — Reddit, YouTube, and Google Alerts — for a list of fluoridation
and vaccination keywords. Whatever they find is written into the **"Prototype"
Google Sheet**, one tab per source. A fourth script analyses everything to surface
"emerging" words that aren't on the keyword list yet. The Google Sheet is connected
to a **Google Data Studio dashboard**, which turns the data into charts. You don't
have to run anything by hand — it happens on a schedule.

### Where everything lives

| Thing | Where | Notes |
|---|---|---|
| Google account | lightweightprototype@gmail.com | Owns everything below. Login shared privately with supervisors. |
| The data (Google Sheet) | "Prototype" spreadsheet in the account's Google Drive | One tab per source, plus the Master2 tab |
| The dashboard | Google Data Studio (link in report Appendix 9) | Two pages: "Existing keywords" and "Emerging words" |
| The code | This GitHub repository (github.com/EP04/disinformation-tracker) | Scripts, config files, and the automation schedules |
| The engine room | Google Cloud project (under the same account) | Holds the API keys that let the scripts talk to YouTube and Google Sheets |

### How to change what's monitored (no coding)

This is the main thing you'll want to do, and it's the whole point of the design:
you change **what** is tracked by editing simple list files, never the code itself.
Each file is a spreadsheet-style `.csv` you can open and edit in Excel, Google
Sheets, or any text editor, then save and commit back to the repository.

- **`keywords.csv`** — the search terms, used by all three sources. Two columns:
  `keyword` (the phrase to search) and `weight` (how specific/important it is —
  `1` for broad words like "vaccine", `5` for narrow phrases like "vaccine autism
  parent group"). To track a new term, add a row. The weight feeds the dashboard's
  relevance filter (see below).
- **`subreddits.csv`** — the 93 Australian subreddits Reddit results are limited to.
  One column, `subreddit`. Add or remove rows to change Reddit's coverage.
- **`rss_links.csv`** — the Google Alerts feeds. To change these you also need to
  create/edit the matching alert at google.com/alerts (signed in as the project
  account), then paste its RSS link into this file.
- **`stopwords.csv`** — common words ("the", "and") the emerging-term analysis
  ignores. Rarely needs touching.

After editing any of these, commit the change to GitHub. The next scheduled run
picks it up automatically — nothing else to do.

### Reading the dashboard

The dashboard has two pages (report Appendix 9):

- **"Existing keywords"** — charts for the terms on your tracking list: volume by
  platform, activity over time, and a relevance-filtered table. Use the
  **relevance-weight filter** to hide low-signal noise: set it high (e.g. ≥5) to
  see only records that matched specific, narrow keywords; set it to 1 to see
  everything including broad-term noise.
- **"Emerging words"** — words and authors that keep recurring but *aren't* on the
  keyword list, as candidates for new trends. These always need human judgement —
  see the report's Appendix 10 for why ("shorts" is just YouTube noise, etc.).

You can add more charts yourself with no coding, using Data Studio's drag-and-drop.

### How to check it's running

Go to the repository's **Actions** tab on GitHub. Each scheduled run shows a
**green tick** (worked) or a **red X** (failed). If you see red X's for several
days running, the data has stopped updating and someone with Part B knowledge
needs to look. A single red X is usually a temporary blip and often fixes itself
on the next run.

---

## PART B — UNDER THE HOOD

### The three monitors

All three write the **same 15-column schema** so the data can be stacked and
compared. The columns are:

`timestamp, post_id, platform, subreddit, title, keywords_matched, match_count,
keywords_in_post, keywords_in_comments, score, num_comments, author, url,
created_aest, relevance_weight`

- `timestamp` = when the script found the item; `created_aest` = when the item was
  originally posted (converted to Australian Eastern time).
- `relevance_weight` = the sum of the matched keywords' weights from `keywords.csv`.
  This is the noise filter: broad-only matches score low, specific matches score high.
- For YouTube and Google Alerts, which have no subreddit/author/score in the Reddit
  sense, those columns are mapped (channel/source domain) or left blank — documented
  in each script's comments.

**`reddit_monitor.py`** — searches each keyword via the **PullPush.io** API (a
third-party Reddit archive), then keeps only results from the subreddits in
`subreddits.csv`. Writes to the "Reddit" tab. *Why PullPush and not Reddit directly:*
Reddit deprecated unauthenticated access on 30 May 2026 and rejected the Researcher
API application (report Appendix 7). PullPush is the free workaround, but it lags
and can be flaky (report Appendix 8) — expect occasional timeouts on long
multi-word keywords; the script retries and moves on.

**`youtube_monitor.py`** — searches each keyword via the official **YouTube Data
API**. Runs in two modes via the `APPEND_AUSTRALIA` environment variable: unset =
bare keywords → "YouTube" tab; set to `true` = keyword + " australia" → "YouTube AU"
tab. Both run daily (report Phase 4 explains why both: regionCode=AU is an imperfect
filter, so the bare tab catches global content Australians watch, the AU tab catches
explicitly-Australian discussion). Searching costs 100 quota units/keyword; the free
budget is 10,000/day, so two full runs (~3,300 units) sit comfortably under.

**`google_monitor.py`** — reads the Google Alerts RSS feeds listed in
`rss_links.csv`, strips Google's HTML/redirect wrapping, and writes to the
"Google Alerts v2" tab. Replaced the old InoReader→Zapier chain (now retired —
see below).

### The analysis script

**`emerging_terms.py`** — reads the Master2 tab and counts words (and authors) that
recur across titles but aren't in `keywords.csv`, excluding the `stopwords.csv`
list. Feeds the "Emerging words" dashboard page.

### How the data is stacked: the Master2 tab

Each source writes to its own tab. A **Master2 tab** stacks them all into one table
(same 15 columns) so the dashboard reads from a single source. This is done with a
live spreadsheet formula in the Master2 tab, so it updates automatically as the
monitors append rows. (Report Figure 2 shows the full pipeline.)

### How the automation runs (GitHub Actions)

The schedules live in `.github/workflows/`. Each workflow checks out the repo,
installs dependencies, writes the credentials from GitHub Secrets to disk, runs the
relevant script(s), then commits the updated `seen_ids` and results files back to
the repo so the next run remembers what it already collected.

Schedules (note: GitHub Actions cron is in **UTC**, and runs can be 5–30 min late):

- **Reddit** — once daily
- **YouTube** — once daily (runs both bare and australia modes back-to-back)
- **Google Alerts** — three times daily (`30 4,13,20` UTC = ~11:30pm / 6:30am /
  2:30pm AEST), because each RSS feed only holds ~20 items and busy feeds can
  overflow between runs

To run a workflow by hand (e.g. to test), use **Actions tab → pick the workflow →
Run workflow**.

### The secrets

Stored under **Settings → Secrets and variables → Actions** (values never appear in
the code). There are three:

- `GOOGLE_CREDENTIALS` — the OAuth client JSON for Google Sheets/Drive access
- `GOOGLE_TOKEN` — the saved login token (`token.json`)
- `YOUTUBE_API_KEY` — the YouTube Data API key

The actual secret values are kept in the project's password manager / handover
note, **not** in this repo. If the Google login ever breaks (you'll see Sheets
upload failures in the logs with an `invalid_grant` error), the `token.json` needs
regenerating by re-running a script locally and signing in as the project account,
then updating the `GOOGLE_TOKEN` secret. The OAuth consent screen must stay set to
**External / Published** to avoid the token expiring every 7 days.

### Navigating and setting up Google Cloud

Google Cloud is the "engine room" — it holds the keys that let the scripts talk to
YouTube and to Google Sheets. You rarely need to touch it once it's working, but
here's how to find your way around and how to rebuild it if needed.

**Getting in:** go to https://console.cloud.google.com and sign in as
lightweightprototype@gmail.com. The project is named **"My First Project"** — check
the project name in the dropdown at the top of the page is showing that, since the
console can default to a different project.

**The two areas that matter** (both under the ☰ menu → **APIs & Services**):

- **Enabled APIs & services** — confirms the three APIs this project depends on are
  switched on: **YouTube Data API v3**, **Google Sheets API**, and **Google Drive
  API**. If any is off, the matching script will fail.
- **Credentials** — holds the two things the scripts authenticate with: the **OAuth
  2.0 Client** (used for Sheets/Drive — this is what `credentials.json` comes from)
  and the **API key** (used for YouTube).

**Setting it up from scratch** (only needed if rebuilding in a new account):

1. **Enable the APIs.** APIs & Services → Library → search and **Enable** each of:
   YouTube Data API v3, Google Sheets API, Google Drive API.
2. **Create the OAuth client** (for Sheets/Drive):
   - APIs & Services → **OAuth consent screen** → set User Type to **External**,
     fill in the basic fields, and **Publish** the app to production. *Publishing
     matters:* if left in "Testing", the login token expires every 7 days and the
     scripts break with an `invalid_grant` error.
   - APIs & Services → Credentials → **Create Credentials → OAuth client ID** →
     application type **Desktop app**. Download the JSON — this is your
     `credentials.json`.
3. **Create the API key** (for YouTube):
   - Credentials → **Create Credentials → API key**. Copy the key.
   - Click the key to **Restrict** it → under API restrictions, allow only
     **YouTube Data API v3**. This limits damage if the key ever leaks.
   - This key becomes the `YOUTUBE_API_KEY` secret/`.env` value.
4. Generate `token.json` by running any script locally once and signing in as the
   project account when the browser opens (see local-run steps below).

**Note on service accounts:** an earlier setup attempt used a service-account key,
but the account's organisation policy blocks service-account key creation
(`iam.disableServiceAccountKeyCreation`). That's why this project uses the OAuth
*user*-login flow (`credentials.json` + `token.json`) instead. Don't try to switch
to a service account unless that policy changes.

### ⚠ Free trial expiry — read this

The Google Cloud **free trial ends on approximately 19th August 2026**. **This should
not stop the tool from working**, and here's why: the three APIs this project uses
(YouTube Data, Sheets, Drive) are **free, quota-based services**. They don't spend
the trial's credit and don't require an active paid billing account — they have
daily usage *limits*, not usage *charges*. The trial credit is for billable
infrastructure (servers, databases) that this project doesn't use.

When the trial ends:
- The project ("My First Project") is **not deleted** — it stays, and its APIs and
  credentials keep working.
- You simply lose the USD $300 trial credit, which this project wasn't drawing on.

**What to do as the trial nears its end:**
1. A few days after the trial expires, check the **Actions** tab on GitHub — if the
   YouTube and Sheets-writing runs still show green ticks, everything's fine.
2. If you *do* see failures mentioning billing, go to Google Cloud → **Billing** and
   confirm the project is on the free tier; you may need to dismiss a prompt asking
   to upgrade to a paid account, but you should not need to actually pay.
3. Do **not** delete the project or its credentials when Google emails about the
   trial ending — that's the one action that *would* break the tool.

If usage ever genuinely exceeds the free YouTube quota (10,000 units/day), the fix
may be to reduce run frequency or keyword count, not to start paying.

### Running a script locally (for testing or regenerating the token)

1. Install Python 3.11+
2. `pip install requests pandas gspread google-auth google-auth-oauthlib feedparser python-dotenv`
3. Put `credentials.json` and `token.json` in the folder (or run once to generate
   `token.json` via the browser sign-in)
4. For YouTube, set the key — either a `.env` file containing
   `YOUTUBE_API_KEY=...` (this file is gitignored, never commit it) or a session
   environment variable
5. Run, e.g. `python youtube_monitor.py`

### What's retired (ignore these)

The original pipeline used **InoReader** (RSS reader) and **Zapier** (automation)
to get Google Alerts into Sheets. Both are **no longer used** — replaced by
`google_monitor.py`, which reads the feeds directly. The Zapier free trial
expired 27 May 2026 (report Figure 6). You do not need InoReader or Zapier accounts
to run the current system. Their mention in older notes is historical only.

The "Master" tab is retired in favour of the "Master2" tab, as the Master contained data from the old pipeline where the Google Alerts data columns couldn't be fully filled in by the InoReader-Zapier pipeline, and when there was not the metric of relevance weight.

### Known limitations (carried from the report)

- **PullPush lag/flakiness** — Reddit data can be stale or sparse; the niche
  keywords genuinely have few recent Australian matches (itself a finding).
- **YouTube is not truly Australia-scoped** — `regionCode=AU` only biases results;
  many are US/UK/India. The bare-vs-AU split is a partial workaround, not a fix. A
  channel-allowlist (like the subreddit list) would be the proper future fix.
- **Text-only matching** — keywords in images or video frames are missed (report
  Appendix 11, the "Is this toothpaste for cookers?" example).
- **Comments only fetched on matched posts** — to save rate-limit/quota budget, so
  misinformation living only in comments of a non-matching post is missed.
- **Human judgement is still required** — relevance weight and emerging-term counts
  only tell you *where to look*; they don't identify misinformation. A high score
  can be a debunking. The tool narrows the haystack; a person still finds the needle.

### Known cleanup tasks (from the report's Future Work)

- Aggregate the Master2 tab at the scraper step rather than via sheet formula
- Resolve duplicate rows in Reddit data
- Split the `platform` cell in the Emerging Terms tab
- Split the `keywords_matched` cell in Master2
- Store body text and comments (currently fetched then discarded) to improve
  emerging-term detection
- Reddit duplicates are removed in the 'Reddit Uniq' tab, but results_all.csv in the repo still contains them — clean before reuse
