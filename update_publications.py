#!/usr/bin/env python3
"""Fetches publications from Semantic Scholar and generates publications.json."""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error

# Both Semantic Scholar author profiles (split profile)
# TODO: Go claim the pages and deduplicate
AUTHOR_IDS = ["5966892", "2264465163"]
API_URL = "https://api.semanticscholar.org/graph/v1/author/{}/papers"
FIELDS = "title,year,venue,citationCount,url,externalIds,authors"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_papers_for_author(author_id, retries=3):
    params = urllib.parse.urlencode({"fields": FIELDS, "limit": 100})
    url = API_URL.format(author_id) + f"?{params}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
            return data["data"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def fetch_all_publications():
    all_papers = []
    for i, author_id in enumerate(AUTHOR_IDS):
        if i > 0:
            print("  Waiting to avoid rate limits...")
            time.sleep(5)
        print(f"  Fetching from author profile {author_id}...")
        papers = fetch_papers_for_author(author_id)
        print(f"    Found {len(papers)} papers.")
        all_papers.extend(papers)
    return all_papers


def deduplicate(papers):
    seen = {}
    for paper in papers:
        title_key = paper.get("title", "").strip().lower()
        if title_key in seen:
            # Keep the one with more citations
            if (paper.get("citationCount") or 0) > (seen[title_key].get("citationCount") or 0):
                seen[title_key] = paper
        else:
            seen[title_key] = paper
    return list(seen.values())


def load_manual_publications():
    path = os.path.join(SCRIPT_DIR, "manual_publications.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def process_publications(papers):
    publications = []
    for paper in papers:
        pub = {
            "title": paper.get("title", ""),
            "year": paper.get("year"),
            "venue": paper.get("venue", ""),
            "citationCount": paper.get("citationCount", 0),
            "url": paper.get("url", ""),
            "authors": [a["name"] for a in paper.get("authors", [])],
            "pdf": "",
        }
        ext_ids = paper.get("externalIds") or {}
        if ext_ids.get("ArXiv"):
            pub["arxiv"] = f"https://arxiv.org/abs/{ext_ids['ArXiv']}"
        publications.append(pub)

    # Merge manual publications
    manual = load_manual_publications()
    if manual:
        print(f"  Merging {len(manual)} manual publications.")
        existing_titles = {p["title"].strip().lower() for p in publications}
        for m in manual:
            if m["title"].strip().lower() not in existing_titles:
                publications.append(m)

    # Sort by year (newest first), then by citations
    publications.sort(key=lambda p: (-(p["year"] or 0), -p["citationCount"]))
    return publications


def main():
    print("Fetching publications from Semantic Scholar...")
    papers = fetch_all_publications()

    print(f"Total papers fetched: {len(papers)}")
    papers = deduplicate(papers)
    print(f"After deduplication: {len(papers)}")

    publications = process_publications(papers)

    # Save JSON
    out_json = os.path.join(SCRIPT_DIR, "media", "publications.json")
    with open(out_json, "w") as f:
        json.dump(publications, f, indent=2)
    print(f"Saved {out_json}")

    # Print summary
    print(f"\n{len(publications)} publications:")
    for pub in publications:
        print(f"  [{pub['year']}] {pub['title']} ({pub['citationCount']} citations)")


if __name__ == "__main__":
    main()
