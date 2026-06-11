import requests
import pandas as pd
import time
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

AEST = ZoneInfo("Australia/Sydney")  # for timestamping in local time

# --- Configuration ---
SUBREDDITS = [
    # News & politics — highest yield
    "australia",
    "AustralianPolitics",
    "AusPol",
    "AusNews",
    "AusPolitics",
    "AustraliaLeftPolitics",
    "AusLeftPolitics",
    "NeutralAustralia",
    "LNPCorruption",
    "MetaAusPol",
    "AusPublicService",  
    "friendlyjordies",   

    # COVID & health — most directly relevant
    "CoronavirusAustralia",
    "CoronavirusDownunder",
    "CoronavirusStraya",
    "Covid19Australia",
    "covidWA",
    "LockdownSkepticismAU",
    "NDIS",              
    "ausjdocs",          
    "CentrelinkOz",

    # Skepticism, alternative health, libertarian — likely hotspots
    "AussieLibertarians",
    "libertarianaustralia",
    "MedicalCannabisAus",
    "MedicalCannabisOz",
    "DrugsAustralia",
    "apskeptic",

    # General large communities
    "straya",
    "aussie", #not picked up in AusReddit list, manually added
    "aus",
    "AskAnAustralian",
    "regionalaustralia",
    "AusFinance",        
    "AusLegal",          
    "australian",        
    "AustralianTeachers",

    # Capital cities
    "sydney",
    "melbourne",
    "brisbane",
    "perth",
    "Adelaide",
    "canberra",
    "hobart",
    "darwin",

    # States & territories
    "queensland",
    "nsw",
    "vic",
    "southaustralia",
    "WesternAustralia",
    "tasmania",
    "northernterritory",

    # Towns & regional cities
    "Cairns",
    "Townsville",
    "Toowoomba",
    "GoldCoast",
    "sunshinecoast",
    "rockhampton",
    "CentralQueensland",
    "GympieQLD", #not picked up in AusReddit list, manually added
    "Mackay",
    "Launceston",
    "HuonValley",
    "newcastle",
    "Nowra",
    "CoffsHarbour",
    "centralcoastnsw",
    "MidNorthCoastNSW",
    "Armidale",
    "albury",
    "Cessnock",
    "newtown",
    "ballarat",
    "Bendigo",
    "Geelong",
    "gippsland",
    "shepparton",
    "warrnambool",
    "Mildura",
    "bluemountains",
    "frankston",
    "mandurah",
    "rockingham",
    "albanywa",
    "Broome",
    "BrokenHill",
    "DarwinAustralia",
    "ipswich",
    "tweedshire",
    "wollongong",
    "NorfolkIsland",
    "Gungahlin",
    "belconnen",
    "altona",
    "Wodonga", #not picked up in AusReddit list, manually added
]

# Lowercase set for fast, case-insensitive subreddit filtering
SUBREDDITS_LOWER = {s.lower() for s in SUBREDDITS}

KEYWORDS = [
    #fluoridation
    "fluoridation", "fluoride", "fluoride free australia",
    "fluoride water filter", "fluoride byproduct", "fluoride thyroid", "mass medication fluoride",
    #vaccination
    "vaccination", "vaccine", "selective vaccine schedule", "pharma vaccine lying", "vaccine autism parent group", 
    "vaccine death data", "vaccine less than natural immunity",
]

SEARCH_SIZE = 100          # posts to fetch per subreddit
CASE_SENSITIVE = False
SLEEP_BETWEEN_REQUESTS = 2   # seconds — be polite to Reddit's servers to not be rate-limited

PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"
PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"

HEADERS = {"User-Agent": "research-monitor/0.2"}

# --- Google Sheets configuration ---
CREDENTIALS_FILE = "credentials.json"   # OAuth client JSON downloaded from Google Cloud
TOKEN_FILE        = "token.json"         # Auto-created after first login — do not delete
SPREADSHEET_NAME  = "Prototype"  # Exact name of Google Spreadsheet I want to upload to
SHEET_TAB_NAME    = "Reddit"                 # Tab name to write into

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# --- Timestamped output filename ---
scan_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
OUTPUT_FILE = f"results_{scan_time}.csv"
MASTER_FILE = "results_all.csv"
SEEN_IDS_FILE = "seen_ids.txt"

COLUMNS = [
    "timestamp", "post_id", "platform", "subreddit", "title",
    "keywords_matched", "match_count", "keywords_in_post", "keywords_in_comments",
    "score", "num_comments", "author", "url", "created_utc",
]

# --- Load seen IDs to avoid duplicates across scans ---
if os.path.exists(SEEN_IDS_FILE):
    with open(SEEN_IDS_FILE) as f:
        seen_ids = set(f.read().splitlines())
else:
    seen_ids = set()

#Pullpush functions
def fetch_submissions(keyword):
    params = {
        "q": keyword,
        "size": SEARCH_SIZE,
        "sort": "desc",
        "sort_type": "created_utc",
    }
    for attempt in range(3):
        try:
            response = requests.get(PULLPUSH_SUBMISSION_URL, params=params, headers=HEADERS,timeout=60)
            if response.status_code == 429:
                print(f"  Rate limited — waiting 30s...")
                time.sleep(30)
                continue
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for submissions with keyword '{keyword}': {e}")
            time.sleep(5)
    return []

def find_keywords(text):
    haystack = text if CASE_SENSITIVE else text.lower()
    matched = []
    for kw in KEYWORDS:
        words = kw.lower().split()
        if all(word in haystack for word in words):
            matched.append(kw)
    return matched

def fetch_comments(post_id):
    params = {"link_id": post_id, "size": 100}
    for attempt in range(3):
        try:
            response = requests.get(PULLPUSH_COMMENT_URL, params=params, headers=HEADERS, timeout=60)
            if response.status_code == 429:
                print(f"  Rate limited — waiting 30s...")
                time.sleep(30)
                continue
            response.raise_for_status()
            comments = response.json().get("data", [])
            return " ".join(c.get("body", "") for c in comments)
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for comments with post ID '{post_id}': {e}")
            time.sleep(5)
    return ""

# Note: may 30th Reddit's API has become more restrictive, and many endpoints now require authentication or are behind paywalls.
# # --- Fetch posts from a subreddit (with retry on rate limit) ---
# def fetch_posts(subreddit):
#     url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={SEARCH_SIZE}"
#     for attempt in range(3):
#         try:
#             response = requests.get(url, headers=HEADERS, timeout=10)
#             if response.status_code == 429:
#                 wait = int(response.headers.get("Retry-After", 10))
#                 print(f"  Rate limited — waiting {wait}s...")
#                 time.sleep(wait)
#                 continue
#             response.raise_for_status()
#             return [p["data"] for p in response.json()["data"]["children"]]
#         except Exception as e:
#             print(f"  Attempt {attempt+1} failed for r/{subreddit}: {e}")
#             time.sleep(5)
#     return []

# # --- Check a post for keywords --- 
# # AND match — every word in the phrase must appear somewhere in the text, but not necessarily together
# # comparable method to how Google Alerts matches keywords in its results
# def find_keywords(text):
#     haystack = text if CASE_SENSITIVE else text.lower()
#     matched = []
#     for kw in KEYWORDS:
#         words = kw.lower().split()
#         if all(word in haystack for word in words):
#             matched.append(kw)
#     return matched

# # check comments for keywords
# def fetch_comments(post_id):
#     url = f"https://www.reddit.com/comments/{post_id}.json"
#     for attempt in range(3):
#         try:
#             response = requests.get(url, headers=HEADERS, timeout=10)
#             if response.status_code == 429:
#                 wait = int(response.headers.get("Retry-After", 10))
#                 print(f"  Rate limited — waiting {wait}s...")
#                 time.sleep(wait)
#                 continue
#             response.raise_for_status()
#             comments = response.json()[1]["data"]["children"]
#             return " ".join(
#                 c["data"].get("body", "")
#                 for c in comments
#                 if c["kind"] == "t1"
#             )
#         except Exception as e:
#             print(f"  Error fetching comments for {post_id}: {e}")
#             time.sleep(5)
#     return ""

# --- Google Sheets related functions
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
print(f"\nScan started at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Searching {len(KEYWORDS)} keywords via PullPush, filtering to {len(SUBREDDITS)} subreddits\n")

new_rows = []
seen_this_scan = set()  # track IDs seen in this run to avoid duplicates within the same scan

for keyword in KEYWORDS:
    print(f"  Searching for keyword '{keyword}'...")
    submissions = fetch_submissions(keyword)
    matches = 0

    for post in submissions:
        post_id = post.get("id")
        if not post_id:
            continue

        #skip posts not in target subreddits (PullPush returns results from all subreddits, so we filter client-side)
        sub = post.get("subreddit", "")
        if sub.lower() not in SUBREDDITS_LOWER:
            continue

        #skip if we've already seen this post in a previous scan or earlier in this scan
        if post_id in seen_ids or post_id in seen_this_scan:
            continue

        post_text = post.get("title", "") + " " + post.get("selftext", "")
        post_hits = find_keywords(post_text)

        if post_hits:
            matches +=1
            seen_this_scan.add(post_id)
            seen_ids.add(post_id)  # add to global seen IDs to prevent future duplicates in this and future scans

            # Fetch comments for matched posts only
            print(f"  Match found in r/{sub} — fetching comments for post {post_id}...")
            comment_text = fetch_comments(post_id)
            comment_hits = find_keywords(comment_text)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

            all_hits = list(dict.fromkeys(post_hits + comment_hits))  # deduplicated, order preserved

            created = post.get("created_utc", 0)

            new_rows.append({
                "timestamp":        datetime.now(AEST).isoformat(), #when script found post
                "post_id":          post_id, #reddit's unique id for post -- avoid duplication across scans, is what's used in seen_ids
                "platform":         "Reddit", #to differentiate from later platforms, e.g. Youtube and Inoreader/Google Alerts
                "subreddit":        sub, # which subreddit post came from
                "title":            post.get("title", ""), #post title is what's searched against keywords
                "keywords_matched": ", ".join(all_hits), #which keywords triggered match
                "match_count":      len(all_hits), #how many keywords matched, measures relevance
                "keywords_in_post":     ", ".join(post_hits),
                "keywords_in_comments": ", ".join(comment_hits),
                "score":            post.get("score", 0), #measures traction (upvotes minus downvotes)
                "num_comments":     post.get("num_comments", 0),
                "author":           post.get("author", ""), #reddit username of poster
                "url":              "https://reddit.com" + post.get("permalink", ""),
                "created_utc":      datetime.fromtimestamp(created, tz=AEST).isoformat(), #when post was created, converted to local time
            })

    print(f"  {len(submissions)} total posts scanned, {matches} matches found.")
    time.sleep(SLEEP_BETWEEN_REQUESTS)



new_rows.sort(key=lambda x: x["match_count"], reverse=True) #sort results by relevance (number of keywords matched) before saving

# --- Save results in local CSVs 
# (the program saves to local csv and also uploads to Google Sheets as you can see
# in the Google Sheets functions above) ---
if new_rows:
    new_df = pd.DataFrame(new_rows)

    # Save timestamped snapshot for this scan
    new_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ {len(new_rows)} new matches saved to {OUTPUT_FILE}")

    # Append to master CSV
    MASTER_FILE = "results_all.csv"
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
    print(f"\n Google Sheets upload failed: {e}")
    print("  Local CSV files are still saved as a backup.")

# --- Update seen IDs file ---
with open(SEEN_IDS_FILE, "w") as f:
    f.write("\n".join(seen_ids))

print(f"Scan complete at {datetime.now(AEST).strftime('%Y-%m-%d %H:%M:%S')}\n")