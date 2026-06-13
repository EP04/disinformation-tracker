import os
import csv
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd

import gspread 
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Load YouTube API key from a local .env file if present (python-dotenv).
# On GitHub Actions there's no .env as the key comes from the repo Secret
# via the environment variable instead. Either way it's read from os.environ below.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AEST = ZoneInfo("Australia/Sydney")

def load_keywords(filename):
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
                weights[kw.lower()] = 1
    return keywords, weights

KEYWORDS, KEYWORD_WEIGHTS = load_keywords("keywords.csv")

def relevance_weight(matched_keywords):
    return sum(KEYWORD_WEIGHTS.get(kw.lower(), 1) for kw in matched_keywords)

#Configuration
#Append Australia would add " australia" to each keyword, which I want to compare to the non-append version
#as the non-append version even with region set to AU is still surfacing global content
#keywords matched for the append-australia version will still show the non-append keyword
# way to differentiate if " australia" was appended to keyword is in the "Platform" column in the output - "YouTube AU" vs "YouTube"
APPEND_AUSTRALIA = os.environ.get("APPEND_AUSTRALIA", "false").lower() == "true"
CASE_SENSITIVE = False
RESULTS_PER_KEYWORD = 25
COMMENTS_PER_VIDEO = 100
REGION_CODE = "AU" #biases results towards Australia
RELEVANCE_LANGUAGE = "en"
SLEEP_BETWEEN_REQUESTS = 1
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

# --- Google Sheets configuration ---
CREDENTIALS_FILE = "credentials.json"   # OAuth client JSON downloaded from Google Cloud
TOKEN_FILE        = "token.json"         # Auto-created after first login — do not delete
SPREADSHEET_NAME  = "Prototype"          # Exact name of Google Spreadsheet
SHEET_TAB_NAME = "YouTube AU" if APPEND_AUSTRALIA else "YouTube"           # separate tab from Reddit / Google Alerts
 
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
 
# --- Timestamped output filename ---
scan_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
suffix = "_au" if APPEND_AUSTRALIA else ""
OUTPUT_FILE = f"youtube_results{suffix}_{scan_time}.csv"
MASTER_FILE = f"youtube_results{suffix}_all.csv"
SEEN_IDS_FILE  = "youtube_au_seen_ids.txt" if APPEND_AUSTRALIA else "youtube_seen_ids.txt"
 
# Shared schema with the Reddit and Google Alerts monitors so all sources blend
# cleanly in the Master tab / dashboard. YouTube-specific data is mapped onto these:
#   post_id  <- video id      subreddit <- channel name     author <- channel name
#   score / num_comments <- (blank, not returned by the search endpoint)
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
 
 
# --- Keyword matching (identical logic to the Reddit / Google Alerts monitors) ---
def find_keywords(text):
    haystack = text if CASE_SENSITIVE else text.lower()
    matched = []
    for kw in KEYWORDS:
        words = kw.lower().split()
        if all(word in haystack for word in words):
            matched.append(kw)
    return matched
 
 
# --- Search YouTube for a keyword ---
def search_videos(keyword):
    query = keyword + " australia" if APPEND_AUSTRALIA else keyword
    params = {
        "key": YOUTUBE_API_KEY,
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": RESULTS_PER_KEYWORD,
        "order": "date",
        "regionCode": REGION_CODE,
        "relevanceLanguage": RELEVANCE_LANGUAGE,
    }
    for attempt in range(3):
        try:
            response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=30)
            if response.status_code == 403:
                # Usually quota exhausted or key/permission problem — report and stop this keyword
                print(f"  Quota or key error for '{keyword}': {response.text[:200]}")
                return []
            response.raise_for_status()
            return response.json().get("items", [])
        except Exception as e:
            print(f"  Attempt {attempt+1} failed searching '{keyword}': {e}")
            time.sleep(5)
    return []
 
 
# --- Fetch comments for a video ---
def fetch_comments(video_id):
    params = {
        "key": YOUTUBE_API_KEY,
        "videoId": video_id,
        "part": "snippet",
        "maxResults": COMMENTS_PER_VIDEO,
        "textFormat": "plainText",
    }
    for attempt in range(3):
        try:
            response = requests.get(YOUTUBE_COMMENTS_URL, params=params, timeout=30)
            # Comments disabled (403) or video gone (404) — normal, not an error
            if response.status_code in (403, 404):
                return ""
            response.raise_for_status()
            items = response.json().get("items", [])
            return " ".join(
                item["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
                for item in items
            )
        except Exception as e:
            print(f"  Error fetching comments for {video_id}: {e}")
            time.sleep(5)
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
if not YOUTUBE_API_KEY:
    print("⚠ No YOUTUBE_API_KEY found.")
    print("  Set it as an environment variable, or put it in a .env file as:")
    print("    YOUTUBE_API_KEY=your-key-here")
    raise SystemExit(1)
 
print(f"\nScan started at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Searching {len(KEYWORDS)} keywords on YouTube (region: {REGION_CODE})\n")
 
new_rows = []
seen_this_scan = set()  # track IDs seen in this run to avoid duplicates within the same scan
 
for keyword in KEYWORDS:
    print(f"  Searching for keyword '{keyword}'...")
    videos = search_videos(keyword)
    matches = 0
 
    for video in videos:
        video_id = video.get("id", {}).get("videoId")
        if not video_id:
            continue
        if video_id in seen_ids or video_id in seen_this_scan:
            continue
 
        snippet = video.get("snippet", {})
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        video_text = title + " " + description
        post_hits = find_keywords(video_text)
 
        if post_hits:
            matches += 1
            seen_this_scan.add(video_id)
            seen_ids.add(video_id)
 
            channel = snippet.get("channelTitle", "")
            print(f"  Match on '{channel}' — fetching comments for {video_id}...")
            comment_text = fetch_comments(video_id)
            comment_hits = find_keywords(comment_text)
            time.sleep(SLEEP_BETWEEN_REQUESTS)
 
            all_hits = list(dict.fromkeys(post_hits + comment_hits))  # deduplicated, order preserved
 
            # Convert publish time (ISO UTC, e.g. 2026-06-12T03:05:25Z) to AEST
            published = snippet.get("publishedAt", "")
            created_aest = (
                datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(AEST).isoformat()
                if published else ""
            )
 
            new_rows.append({
                "timestamp":            datetime.now(AEST).isoformat(),   # when script found video
                "post_id":              video_id,                         # YouTube video id (maps to Reddit post_id)
                "platform":             "YouTube AU" if APPEND_AUSTRALIA else "YouTube",
                "subreddit":            channel,                          # channel name (maps to Reddit subreddit)
                "title":                title,
                "keywords_matched":     ", ".join(all_hits),
                "match_count":          len(all_hits),
                "keywords_in_post":     ", ".join(post_hits),             # keywords in title + description
                "keywords_in_comments": ", ".join(comment_hits),
                "score":                "",                               # not returned by search endpoint
                "num_comments":         "",                               # not returned by search endpoint
                "author":               channel,                          # channel name (maps to Reddit author)
                "url":                  f"https://www.youtube.com/watch?v={video_id}",
                "created_aest":         created_aest,                     # publish time, converted UTC -> AEST
                "relevance_weight":     relevance_weight(all_hits),
            })
 
    print(f"  {len(videos)} videos scanned, {matches} matches found.")
    time.sleep(SLEEP_BETWEEN_REQUESTS)
 
new_rows.sort(key=lambda x: x["match_count"], reverse=True)  # sort by relevance before saving
 
# --- Save results in local CSVs ---
if new_rows:
    new_df = pd.DataFrame(new_rows)
 
    new_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ {len(new_rows)} new matches saved to {OUTPUT_FILE}")
 
    if os.path.exists(MASTER_FILE):
        master = pd.read_csv(MASTER_FILE)
        combined = pd.concat([master, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(MASTER_FILE, index=False)
    print(f"✓ Master log updated — {len(combined)} total matches in {MASTER_FILE}")
else:
    print("\nNo new matches found this scan.")
 
# --- Upload to Google Sheets ---
try:
    upload_to_sheets(new_rows)
except Exception as e:
    print(f"\n⚠ Google Sheets upload failed: {e}")
    print("  Local CSV files are still saved as a backup.")
 
# --- Update seen IDs file ---
with open(SEEN_IDS_FILE, "w") as f:
    f.write("\n".join(seen_ids))
 
print(f"\nScan complete at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}\n")