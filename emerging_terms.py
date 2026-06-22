"""
emerging_terms.py — surface NEW vocabulary appearing in tracked authors' posts.

Companion to the Reddit / YouTube / Google Alerts monitors. Reads the combined
Master tab from the Prototype Google Sheet (same credentials.json / token.json as
the scrapers), reuses keywords.csv so it knows what's ALREADY tracked, and ranks
the remaining words/phrases by how many DISTINCT AUTHORS use them — the metric
that separates a real cross-source trend from one channel's verbal preference.

Stopwords live entirely in stopwords.csv (required). Outputs:
  emerging_terms_latest.csv      - this run's ranked candidates (overwritten)
  emerging_terms_history.csv     - every run appended, with run_date (trend-over-time)
  emerging_terms_by_author.csv   - term x author breakdown, so you can see WHO drives a term
"""

import os
import re
import csv
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter, defaultdict

import pandas as pd
import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

AEST = ZoneInfo("Australia/Sydney")

# ----------------------------- Configuration --------------------------------
KEYWORDS_FILE  = "keywords.csv"          # same file the scrapers use
STOPWORDS_FILE = "stopwords.csv"         # comes from NLTK's list of english stopwords - you can custom add if you want. 
                                        # i decided to not add noisewords like "health" to the list because decided it may still be in a trend

SPREADSHEET_NAME = "Prototype"           # same spreadsheet the scrapers write to
MASTER_TAB_NAME  = "Master2"              # the tab that combines all sources (Reddit, YouTube, Alerts) into one table

# Text column(s) to mine. The master holds 'title'. If you later store body text
# (Reddit selftext, YouTube description, Alerts summary), add the column name here.
TEXT_FIELDS = ["title"]

# Restrict mining to the N most active authors ("most common offenders").
# 0 = use every author. Set e.g. 30 to focus on the prolific accounts.
TOP_AUTHORS = 0

# A candidate must clear BOTH thresholds to make the list.
MIN_AUTHORS = 2     # used by >= this many distinct authors  (the trend signal)
MIN_POSTS   = 3     # appears in >= this many distinct posts (the volume signal)

UPLOAD_TO_SHEETS = True                 # flip on to push the latest snapshot back to the sheet
OUTPUT_TAB_NAME  = "Emerging Terms"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
STOP = set()                             # stopwords come only from stopwords.csv
# -----------------------------------------------------------------------------


def load_keywords(filename):
    """Identical loader to the scrapers, so the tracked list stays in sync."""
    keywords = []
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kw = row["keyword"].strip()
            if kw:
                keywords.append(kw)
    return keywords


def tracked_word_set(keywords):
    """Break every (possibly multi-word) keyword into component words. Mirrors
    find_keywords' AND-on-words logic, so we exclude exactly what the scrapers
    already match on."""
    words = set()
    for kw in keywords:
        for w in re.findall(r"[a-z']+", kw.lower()):
            words.add(w.strip("'"))
    return words


def load_stopwords():
    if not os.path.exists(STOPWORDS_FILE):
        print(f"  WARNING: {STOPWORDS_FILE} not found — NO stopwords will be applied, "
              f"so results will be flooded with common words. Add the file and re-run.")
        return set()
    extra = set()
    with open(STOPWORDS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or [None]
        col = "stopword" if "stopword" in cols else cols[0]
        for row in reader:
            v = (row.get(col) or "").strip().lower()
            if v:
                extra.add(v)
    return extra


def _get_creds():
    """Shared OAuth handling — identical pattern to the scrapers' get_sheet()."""
    creds = None
    if os.path.exists("token.json"):
        creds = OAuthCredentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES).run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds


def load_corpus():
    """Pull the combined Master tab from the Prototype spreadsheet."""
    sh = gspread.authorize(_get_creds()).open(SPREADSHEET_NAME)
    try:
        ws = sh.worksheet(MASTER_TAB_NAME)
    except gspread.WorksheetNotFound:
        tabs = [w.title for w in sh.worksheets()]
        raise SystemExit(
            f"Tab '{MASTER_TAB_NAME}' not found in '{SPREADSHEET_NAME}'.\n"
            f"  Set MASTER_TAB_NAME to one of: {tabs}")
    records = ws.get_all_records()       # first row treated as headers
    print(f"  read {len(records)} rows from '{MASTER_TAB_NAME}' tab in '{SPREADSHEET_NAME}'")
    df = pd.DataFrame(records)
    if "post_id" in df.columns:          # harmless if the tab is already deduplicated
        df = df.drop_duplicates(subset="post_id", keep="first")
    return df


def tokenize(text, stop, tracked):
    text = html.unescape(str(text)).lower()
    words = [w.strip("'-") for w in re.findall(r"[a-z][a-z'-]+", text)]
    words = [w for w in words if len(w) > 2]
    bad = stop | tracked
    uni = [w for w in words if w not in bad]
    bi = []
    for a, b in zip(words, words[1:]):
        if a in stop or b in stop:        # never bridge a stopword
            continue
        if a in tracked and b in tracked: # both already tracked -> not novel
            continue
        bi.append(f"{a} {b}")
    return uni, bi


def main():
    run_date = datetime.now(AEST).strftime("%Y-%m-%d")
    print(f"\nEmerging-terms pass — {run_date}")

    keywords = load_keywords(KEYWORDS_FILE)
    tracked = tracked_word_set(keywords)
    stop = STOP | load_stopwords()
    print(f"  {len(keywords)} tracked keywords -> {len(tracked)} excluded words; "
          f"{len(stop)} stopwords")

    df = load_corpus()
    df = df[df["author"].notna() & (df["author"].astype(str).str.strip() != "")]

    if TOP_AUTHORS > 0:
        keep = df["author"].value_counts().head(TOP_AUTHORS).index
        df = df[df["author"].isin(keep)]
        print(f"  focusing on top {TOP_AUTHORS} authors ({len(df)} rows)")
    else:
        print(f"  mining all {df['author'].nunique()} authors ({len(df)} rows)")

    posts = Counter()
    authors = defaultdict(set)
    platforms = defaultdict(set)
    ttype = {}
    by_author = Counter()

    for _, row in df.iterrows():
        text = " ".join(str(row.get(c, "")) for c in TEXT_FIELDS)
        uni, bi = tokenize(text, stop, tracked)
        a = str(row["author"])
        p = str(row.get("platform", ""))
        for t in set(uni):
            posts[t] += 1; authors[t].add(a); platforms[t].add(p); ttype[t] = "word"
            by_author[(t, a)] += 1
        for t in set(bi):
            posts[t] += 1; authors[t].add(a); platforms[t].add(p); ttype[t] = "phrase"
            by_author[(t, a)] += 1

    rows = []
    for t, n in posts.items():
        na = len(authors[t])
        if na >= MIN_AUTHORS and n >= MIN_POSTS:
            rows.append({
                "run_date": run_date,
                "term": t,
                "type": ttype[t],
                "distinct_authors": na,
                "posts": n,
                "platforms": ", ".join(sorted(platforms[t])),
            })
    out = pd.DataFrame(rows).sort_values(
        ["distinct_authors", "posts"], ascending=False).reset_index(drop=True)

    out.to_csv("emerging_terms_latest.csv", index=False)
    print(f"\n  {len(out)} candidate terms -> emerging_terms_latest.csv")

    hist = "emerging_terms_history.csv"
    out.to_csv(hist, mode="a", header=not os.path.exists(hist), index=False)
    # dedupe history in case of re-runs on the same day, but recurrences across diff days are preserved as that shows trend
    hist_df = pd.read_csv(hist).drop_duplicates(subset=["run_date", "term"], keep="last")
    hist_df.to_csv(hist, index=False)
    print(f"  history now {len(hist_df)} rows -> {hist}")

    kept = set(out["term"])
    ba = pd.DataFrame(
        [{"run_date": run_date, "term": t, "author": a, "posts": c}
         for (t, a), c in by_author.items() if t in kept]
    ).sort_values(["term", "posts"], ascending=[True, False])
    ba.to_csv("emerging_terms_by_author.csv", index=False)
    print(f"  term x author breakdown -> emerging_terms_by_author.csv")

    print("\n  Top 15 this run:")
    print(out.head(15).to_string(index=False))

    if UPLOAD_TO_SHEETS:
        upload_to_sheets(out)


def upload_to_sheets(df):
    """Optional: push the latest snapshot to an Emerging Terms tab in the sheet."""
    sh = gspread.authorize(_get_creds()).open(SPREADSHEET_NAME)
    try:
        ws = sh.worksheet(OUTPUT_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=OUTPUT_TAB_NAME, rows=2000, cols=10)
    ws.clear()
    ws.update([df.columns.tolist()] + df.astype(str).values.tolist())
    print(f"  uploaded {len(df)} rows to '{OUTPUT_TAB_NAME}'")


if __name__ == "__main__":
    main()