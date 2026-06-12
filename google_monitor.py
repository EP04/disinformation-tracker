import os
import re
import csv
import time
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

import feedparser
import pandas as pd

import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

AEST = ZoneInfo("Australia/Sydney")  # for timestamping in local time

# --- Load keywords (for find_keywords) and alert feeds from CSV ---
def load_csv_column(filename, column):
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row[column].strip() for row in reader if row[column].strip()]

def load_alerts(filename):
    """Returns a list of (alert_keyword, feed_url) tuples."""
    rows = []
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kw  = row.get("Keywords", "").strip()
            url = row.get("RSS Link", "").strip()
            if url and "REPLACE" not in url:   # skip template placeholder rows
                rows.append((kw, url))
    return rows

def load_keywords(filename):
    """Returns (keywords_list, weights_dict) from a CSV with keyword,weight columns."""
    keywords, weights = [], {}
    with open(filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kw = row["keyword"].strip()
            if not kw:
                continue
            keywords.append(kw)
            try:
                weights[kw.lower()] = int(row.get("weight", 1) or 1)
            except ValueError:
                weights[kw.lower()] = 1  # default broad if weight missing/bad
    return keywords, weights

KEYWORDS, KEYWORD_WEIGHTS = load_keywords("keywords.csv")
ALERTS = load_alerts("rss_links.csv")

def relevance_weight(matched):
    """Sum the weights of all matched keywords. Unknown keywords count as 1."""
    return sum(KEYWORD_WEIGHTS.get(kw.lower(), 1) for kw in matched)

# --- Configuration ---
CASE_SENSITIVE = False
SLEEP_BETWEEN_REQUESTS = 1

# --- Google Sheets configuration ---
CREDENTIALS_FILE = "credentials.json"   # OAuth client JSON downloaded from Google Cloud
TOKEN_FILE        = "token.json"         # Auto-created after first login — do not delete
SPREADSHEET_NAME  = "Prototype"          # Exact name of Google Spreadsheet
SHEET_TAB_NAME    = "Google Alerts v2"      # separate tab from Reddit / YouTube

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# --- Timestamped output filename ---
scan_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
OUTPUT_FILE   = f"google_alerts_results_{scan_time}.csv"
MASTER_FILE   = "google_alerts_results_all.csv"
SEEN_IDS_FILE = "google_alerts_seen_ids.txt"

# Shared schema with the Reddit and YouTube monitors so all sources blend
# cleanly in the Master tab / dashboard. Google Alerts has no concept of
# score, comment count, or post comments, so those columns are left blank:
#   post_id  <- alert entry id     subreddit <- source domain
#   author   <- source domain      score / num_comments / keywords_in_comments <- (blank)
COLUMNS = [
    "timestamp", "post_id", "platform", "subreddit", "title",
    "keywords_matched", "match_count", "keywords_in_post", "keywords_in_comments",
    "score", "num_comments", "author", "url", "created_aest",
    "relevance_weight",
]

# --- Load seen IDs ---
if os.path.exists(SEEN_IDS_FILE):
    with open(SEEN_IDS_FILE) as f:
        seen_ids = set(f.read().splitlines())
else:
    seen_ids = set()


# --- Keyword matching (identical logic to the Reddit / YouTube monitors) ---
def find_keywords(text):
    haystack = text if CASE_SENSITIVE else text.lower()
    matched = []
    for kw in KEYWORDS:
        words = kw.lower().split()
        if all(word in haystack for word in words):
            matched.append(kw)
    return matched


# --- Strip HTML tags and unescape entities from Google Alerts title/summary ---
def clean_text(raw):
    if not raw:
        return ""
    no_tags = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(no_tags).strip()


# --- Google Alerts wraps every link in a redirect; pull out the real URL ---
def extract_real_url(google_link):
    try:
        qs = parse_qs(urlparse(google_link).query)
        if "url" in qs:
            return qs["url"][0]
    except Exception:
        pass
    return google_link  # fall back to the raw link if parsing fails


# --- Source domain from a URL, used to fill the 'subreddit'/'author' columns ---
def source_domain(url):
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


# --- Google Sheets related functions ---
def get_sheet():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = OAuthCredentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    client = gspread.authorize(creds)
    spreadsheet = client.open(SPREADSHEET_NAME)
    try:
        sheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_TAB_NAME, rows=10000, cols=20)
        print(f"  Created new tab '{SHEET_TAB_NAME}'")
    return sheet


def upload_to_sheets(new_rows):
    if not new_rows:
        print("  Nothing to upload.")
        return
    print(f"\nUploading {len(new_rows)} rows to Google Sheets...")
    sheet = get_sheet()
    existing = sheet.get_all_values()
    if not existing:
        sheet.append_row(COLUMNS)
        print("  Header row written.")
    rows_to_append = [
        [str(row.get(col, "")) for col in COLUMNS]
        for row in new_rows
    ]
    sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
    print(f"  ✓ {len(rows_to_append)} rows appended to '{SHEET_TAB_NAME}' in '{SPREADSHEET_NAME}'")


# --- Main scan ---
if not ALERTS:
    print("⚠ No alert feeds found in alerts.csv (only template placeholders?).")
    print("  Add your Google Alerts RSS feed URLs to alerts.csv and run again.")
    raise SystemExit(1)

print(f"\nScan started at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Reading {len(ALERTS)} Google Alerts RSS feeds\n")

new_rows = []
seen_this_scan = set()

for alert_keyword, feed_url in ALERTS:
    print(f"  Reading alert '{alert_keyword}'...")
    feed = feedparser.parse(feed_url)
    matches = 0

    for entry in feed.entries:
        entry_id = entry.get("id", "") or entry.get("link", "")
        if not entry_id:
            continue
        if entry_id in seen_ids or entry_id in seen_this_scan:
            continue

        seen_this_scan.add(entry_id)
        seen_ids.add(entry_id)

        title   = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", ""))
        real_url = extract_real_url(entry.get("link", ""))
        domain   = source_domain(real_url)

        # The alert keyword always counts; also scan title+summary for any
        # of our shared keywords so the columns mirror Reddit / YouTube.
        post_hits = find_keywords(title + " " + summary)
        all_hits = list(dict.fromkeys(([alert_keyword] if alert_keyword else []) + post_hits))

        # Convert published time to AEST
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(AEST).isoformat()
        else:
            published = ""

        matches += 1
        new_rows.append({
            "timestamp":            datetime.now(AEST).isoformat(),  # when script found item
            "post_id":              entry_id,                        # Google Alerts entry id
            "platform":             "Google Alerts",
            "subreddit":            domain,                          # source site (maps to Reddit subreddit)
            "title":                title,
            "keywords_matched":     ", ".join(all_hits),
            "match_count":          len(all_hits),
            "keywords_in_post":     ", ".join(post_hits),
            "keywords_in_comments": "",                              # Google Alerts has no comments
            "score":                "",                              # not available
            "num_comments":         "",                              # not available
            "author":               domain,                          # source site (maps to Reddit author)
            "url":                  real_url,
            "created_aest":         published,                       # publish time, converted to AEST
            "relevance_weight":      relevance_weight(all_hits),
        })

    print(f"  {len(feed.entries)} items, {matches} new")
    time.sleep(SLEEP_BETWEEN_REQUESTS)

new_rows.sort(key=lambda x: x["match_count"], reverse=True)

# --- Save results in local CSVs ---
if new_rows:
    new_df = pd.DataFrame(new_rows)

    new_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ {len(new_rows)} new items saved to {OUTPUT_FILE}")

    if os.path.exists(MASTER_FILE):
        master = pd.read_csv(MASTER_FILE)
        combined = pd.concat([master, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(MASTER_FILE, index=False)
    print(f"✓ Master log updated — {len(combined)} total items in {MASTER_FILE}")
else:
    print("\nNo new items found this scan.")

# --- Upload to Google Sheets ---
try:
    upload_to_sheets(new_rows)
except Exception as e:
    print(f"\nGoogle Sheets upload failed: {e}")
    print("  Local CSV files are still saved as a backup.")

# --- Update seen IDs file ---
with open(SEEN_IDS_FILE, "w") as f:
    f.write("\n".join(seen_ids))

print(f"\nScan complete at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}\n")