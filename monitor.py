import requests
import pandas as pd
import time
import os
from datetime import datetime, timezone

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

KEYWORDS = [
    #fluoridation
    "fluoridation", "fluoride free australia",
    "fluoride water filter", "fluoride byproduct", "fluoride thyroid", "mass medication fluoride",
    #vaccination
    "vaccination", "selective vaccine schedule", "pharma vaccine lying", "vaccine autism parent group", 
    "vaccine death data", "vaccine less than natural immunity",
]

POST_LIMIT = 100          # posts to fetch per subreddit
CASE_SENSITIVE = False
SLEEP_BETWEEN_REQUESTS = 1   # seconds — be polite to Reddit's servers to not be rate-limited

HEADERS = {"User-Agent": "research-monitor/0.1"}

# --- Timestamped output filename ---
scan_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
OUTPUT_FILE = f"results_{scan_time}.csv"
MASTER_FILE = "results_all.csv"
SEEN_IDS_FILE = "seen_ids.txt"

# --- Load seen IDs to avoid duplicates across scans ---
if os.path.exists(SEEN_IDS_FILE):
    with open(SEEN_IDS_FILE) as f:
        seen_ids = set(f.read().splitlines())
else:
    seen_ids = set()

# --- Fetch posts from a subreddit (with retry on rate limit) ---
def fetch_posts(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={POST_LIMIT}"
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", 10))
                print(f"  Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return [p["data"] for p in response.json()["data"]["children"]]
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for r/{subreddit}: {e}")
            time.sleep(5)
    return []

# --- Check a post for keywords --- 
# AND match — every word in the phrase must appear somewhere in the text, but not necessarily together
# comparable method to how Google Alerts matches keywords in its results
def find_keywords(text):
    haystack = text if CASE_SENSITIVE else text.lower()
    matched = []
    for kw in KEYWORDS:
        words = kw.lower().split()
        if all(word in haystack for word in words):
            matched.append(kw)
    return matched

# check comments for keywords
def fetch_comments(post_id):
    url = f"https://www.reddit.com/comments/{post_id}.json"
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", 10))
                print(f"  Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            comments = response.json()[1]["data"]["children"]
            return " ".join(
                c["data"].get("body", "")
                for c in comments
                if c["kind"] == "t1"
            )
        except Exception as e:
            print(f"  Error fetching comments for {post_id}: {e}")
            time.sleep(5)
    return ""

# --- Main scan ---
print(f"\nScan started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Monitoring {len(SUBREDDITS)} subreddits for {len(KEYWORDS)} keywords\n")

new_rows = []

for sub in SUBREDDITS:
    print(f"Scanning r/{sub}...")
    posts = fetch_posts(sub)
    matches = 0

    for post in posts:
        if post["id"] in seen_ids:
            continue

        post_text = post.get("title", "") + " " + post.get("selftext", "")
        post_hits = find_keywords(post_text)

        if post_hits:
            matches += 1
            seen_ids.add(post["id"])

            # Fetch comments for matched posts only
            print(f"  Match found — fetching comments for post {post['id']}...")
            comment_text = fetch_comments(post["id"])
            comment_hits = find_keywords(comment_text)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

            all_hits = list(dict.fromkeys(post_hits + comment_hits))  # deduplicated, order preserved

            new_rows.append({
                "timestamp":        datetime.now(timezone.utc).isoformat(), #when script found post
                "post_id":          post["id"], #reddit's unique id for post -- avoid duplication across scans, is what's used in seen_ids
                "platform":         "Reddit", #to differentiate from later platforms, e.g. Youtube and Inoreader/Google Alerts
                "subreddit":        sub, # which subreddit post came from
                "title":            post["title"], #post title is what's searched against keywords
                "keywords_matched": ", ".join(all_hits), #which keywords triggered match
                "match_count":      len(all_hits), #how many keywords matched, measures relevance
                "keywords_in_post":     ", ".join(post_hits),
                "keywords_in_comments": ", ".join(comment_hits),
                "score":            post.get("score", 0), #measures traction (upvotes minus downvotes)
                "num_comments":     post.get("num_comments", 0),
                "author":           post.get("author", ""), #reddit username of poster
                "url":              "https://reddit.com" + post.get("permalink", ""),
                "created_utc":      datetime.fromtimestamp(
                                        post["created_utc"],
                                        tz=timezone.utc
                                    ).isoformat(), #when post was originally made in reddit
            })

    print(f"  {len(posts)} posts scanned, {matches} matches")
    time.sleep(SLEEP_BETWEEN_REQUESTS)

new_rows.sort(key=lambda x: x["match_count"], reverse=True) #sort results by relevance (number of keywords matched) before saving

# --- Save results ---
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

# --- Update seen IDs file ---
with open(SEEN_IDS_FILE, "w") as f:
    f.write("\n".join(seen_ids))

print(f"Scan complete at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")