**Keyword-matching logic and per-platform scraper configuration:**

The keywords.csv contained 7 words from vaccination (vaccination, vaccine, selective vaccine schedule, pharma vaccine lying, vaccine autism parent group, vaccine death data, vaccine less than natural immunity) and 7 words from fluoridation (fluoridation, fluoride, fluoride free australia, fluoride water filter, fluoride byproduct, fluoride thyroid, mass medication fluoride).

The keyword matching mechanism across all 3 social media site’s scrapers is as follows: each keyword is split into individual words, and it counts as a match only if every one of those words appears somewhere in the (lowercased, by default) text as a substring, regardless of order, adjacency, or word boundaries. So a multi-word keyword like “fluoride free australia” matches whenever all “fluoride”, “free”, and “australia” appear anywhere in the text, and single words match even inside larger words, such as “free” would match “freedom”.

For Reddit, the scraper searches the title and body text of the post, and if there’s a keyword hit in the post, the scraper will also fetch and count keyword hits in the comments. For YouTube, the scraper searches the title and description of up to 25 most recent videos per keyword searched in the searchbar, and if there’s a keyword hit in that post, the scraper makes a comment call and counts keyword hits for up to 100 top-level comments. For Google Alerts, the scraper reads each RSS feed and records every new article the alert returns. “google_monitor.py” scans the article’s title and summary against the shared keyword list to populate the relevance columns, but unlike Reddit and YouTube, there’s no keyword gate as the alert’s own keyword already qualifies the item, so every new entry is logged.


**Challenge:**
The prototype's data pipeline changed substantially mid-project, creating a data gap and some structural complexity worth noting. These iterations explain a structural quirk: the "Reddit" tab feeds a separate "Reddit Uniq" tab before reaching "Master2." I deduplicated in a separate tab rather than risk breaking the live pipeline by deduplicating in place.

**Recommendations and Future Work in refining pipeline:**
1. Aggregate the Master tab at the scraper step: The current information flow is that each platform has its own scraper, each scraper uploads to its own platform tab in Google Sheets, and the Master tab is then assembled as an aggregate of those individual tabs. Ideally, the aggregation into the Master tab would happen directly at the scraper step rather than as a downstream consolidation.

2. Resolve the known duplicate issue in the Reddit data: Early tests and reruns of the Reddit monitor produced duplicate entries. These have been deduplicated in the "Reddit Uniq" tab of the "Prototype" spreadsheet, but be aware that results_all.csv on GitHub still contains the duplicates and should be cleaned before reuse.

3. Split the platform cell in the "Emerging Terms" tab: At present, the platforms for each term are listed together in a single cell, separated by commas. Splitting these into one platform per cell would allow a term- × platform heatmap, making it easy to see which terms are emerging on which platforms.

4. Split the keywords_matched cell in "Master2": This cell currently combines all matched keywords together. I recommend splitting it into individual keyword matches, but not having that new field wholly replace the existing one. It would be good to have both fields to retain the topic-level view while gaining the ability to drill into any single term.
a. agg_keyword_match (the current keywords_matched): preserves which combinations of keywords appear together, giving a view of topics by keyword co-occurrence.
b. individual_keyword_match (the proposed new field): breaks matches out one keyword per row, enabling trend analysis for a single specific keyword (for example, tracking it by author or platform over time).

**Systems diagram of files in the repo:**
![There is a Python script that analyses the Master tab, and aims to capture emerging misinformation trends by logging the words that are not in the keyword list but are appearing in collated titles. The Google Sheet connects to Google Data Studio to display the data as charts on a dashboard.](Prototype systems diagram (2).png)
