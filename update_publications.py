#!/usr/bin/env python3
"""Fetches publications and citation history, generates publications.json and
citation_history.json.

Supports two data sources:
  --source s2        Semantic Scholar API (default)
  --source scholar   Google Scholar via the `scholarly` library
"""

import argparse
import json
import os
import re
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

# Both Semantic Scholar author profiles (split profile)
# TODO: Go claim the pages and deduplicate
AUTHOR_IDS = ["5966892", "2264465163"]
API_BASE = "https://api.semanticscholar.org/graph/v1"
API_URL = API_BASE + "/author/{}/papers"
CITATION_API_URL = API_BASE + "/paper/{}/citations"
FIELDS = "title,year,venue,citationCount,url,externalIds,authors"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Optional Semantic Scholar API key (free tier: 100 req/sec vs 100/5min without)
S2_API_KEY = os.environ.get("S2_API_KEY")


def _make_request(url, retries=3):
    """Make an API request with optional API key and retry on rate limits."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            if S2_API_KEY:
                req.add_header("x-api-key", S2_API_KEY)
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def fetch_papers_for_author(author_id, retries=3):
    params = urllib.parse.urlencode({"fields": FIELDS, "limit": 100})
    url = API_URL.format(author_id) + f"?{params}"
    data = _make_request(url, retries=retries)
    return data["data"]


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


def _deduplicate_by_title(items, citation_field="citationCount"):
    """Deduplicate items by normalized title, keeping the one with more citations.

    Google Scholar and Semantic Scholar both list multiple versions of the same
    paper (arXiv preprint + published venue). These share most citers, so we
    keep the entry with the highest citation count.
    """
    seen = {}
    for item in items:
        key = _normalize_title(item.get("title", ""))
        if key in seen:
            if (item.get(citation_field) or 0) > (seen[key].get(citation_field) or 0):
                seen[key] = item
        else:
            seen[key] = item
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

    return _merge_manual_and_sort(publications)


def extract_paper_id(url):
    """Extract Semantic Scholar paper ID from URL."""
    if url:
        return url.rstrip("/").split("/")[-1]
    return None


def fetch_citations_for_paper(paper_id):
    """Fetch all citing papers' years for a given paper, with pagination."""
    years = []
    offset = 0
    limit = 100
    while True:
        params = urllib.parse.urlencode(
            {"fields": "year", "limit": limit, "offset": offset}
        )
        url = CITATION_API_URL.format(paper_id) + f"?{params}"
        data = _make_request(url)
        for entry in data.get("data", []):
            citing = entry.get("citingPaper", {})
            year = citing.get("year")
            if year is not None:
                years.append(year)
        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
        # Polite delay between pages
        delay = 0.5 if S2_API_KEY else 3
        time.sleep(delay)
    return years


def fetch_citation_history(publications):
    """Fetch citation-year data for all publications, with incremental caching."""
    cache_path = os.path.join(SCRIPT_DIR, "media", "citation_history.json")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cache = json.load(f)

    cached_papers = cache.get("papers", {})
    delay = 0.5 if S2_API_KEY else 3
    updated = 0

    for i, pub in enumerate(publications):
        paper_id = extract_paper_id(pub.get("url"))
        if not paper_id:
            continue

        current_count = pub.get("citationCount", 0)
        title = pub.get("title", "")
        key = _paper_key(title)
        cached = cached_papers.get(key, {})

        # Skip if citation count hasn't changed
        if cached.get("citationCount") == current_count and "citations_by_year" in cached:
            continue

        if i > 0 and updated > 0:
            time.sleep(delay)

        print(f"    Fetching citations for: {title[:60]}...")
        try:
            years = fetch_citations_for_paper(paper_id)
        except Exception as e:
            print(f"      Error: {e}")
            continue

        # Build year histogram
        by_year = {}
        for y in years:
            by_year[str(y)] = by_year.get(str(y), 0) + 1

        cached_papers[key] = {
            "title": title,
            "citationCount": current_count,
            "citations_by_year": by_year,
        }
        updated += 1

    # Build aggregate histogram
    aggregate = {}
    for paper_data in cached_papers.values():
        for year, count in paper_data.get("citations_by_year", {}).items():
            aggregate[year] = aggregate.get(year, 0) + count

    result = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "aggregate": dict(sorted(aggregate.items())),
        "papers": cached_papers,
    }

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved {cache_path} ({updated} papers updated)")

    # Print summary
    total = sum(aggregate.values())
    print(f"  Total citations tracked: {total}")
    for year in sorted(aggregate.keys()):
        print(f"    {year}: {aggregate[year]}")

    return result


# ---------------------------------------------------------------------------
# Google Scholar source (via `scholarly` library)
# ---------------------------------------------------------------------------
SCHOLAR_AUTHOR_ID = "1vkpStcAAAAJ"


def _normalize_title(title):
    """Normalize a title for deduplication: lowercase, strip trailing year,
    remove punctuation, collapse whitespace."""
    t = title.strip().lower()
    t = re.sub(r'[,\s]+\d{4}\s*$', '', t)   # trailing ", YYYY"
    t = re.sub(r'[^a-z0-9\s]', '', t)         # punctuation
    return re.sub(r'\s+', ' ', t).strip()


def _paper_key(title):
    """Generate a short key for matching publications to citation history entries."""
    return _normalize_title(title).replace(' ', '_')[:60]


def _merge_manual_and_sort(publications):
    """Merge manual publications and sort by year (newest first), then citations."""
    manual = load_manual_publications()
    if manual:
        print(f"  Merging {len(manual)} manual publications.")
        existing = {p["title"].strip().lower() for p in publications}
        for m in manual:
            if m["title"].strip().lower() not in existing:
                publications.append(m)
    publications.sort(key=lambda p: (-(p["year"] or 0), -p["citationCount"]))
    return publications


def fetch_from_google_scholar():
    """Fetch publications and citation history from Google Scholar."""
    from scholarly import scholarly, ProxyGenerator

    # Use free proxy rotation to avoid IP-based rate limiting from Google
    try:
        pg = ProxyGenerator()
        pg.FreeProxies()
        scholarly.use_proxy(pg)
        print("  Using free proxy rotation.")
    except Exception:
        print("  Could not set up proxy, using direct connection.")

    print("  Looking up Google Scholar profile...")
    author = scholarly.search_author_id(SCHOLAR_AUTHOR_ID)
    author = scholarly.fill(author, sections=["basics", "publications"])

    raw_publications = []
    citation_papers = {}

    pubs = author.get("publications", [])
    print(f"  Found {len(pubs)} publications. Filling details...")

    for i, pub_stub in enumerate(pubs):
        if i > 0 and i % 5 == 0:
            print(f"    {i}/{len(pubs)} done...")
            time.sleep(3)  # Longer delay every 5 papers to avoid rate limiting
        elif i > 0:
            time.sleep(1)

        try:
            pub_filled = scholarly.fill(pub_stub)
        except Exception as e:
            print(f"    Warning: could not fill publication {i}: {e}")
            # Use stub data as fallback
            pub_filled = pub_stub
        bib = pub_filled.get("bib", {})

        title = bib.get("title", "")
        year = bib.get("pub_year")
        if year:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None

        citation_count = pub_filled.get("num_citations", 0)
        venue = bib.get("journal") or bib.get("conference") or bib.get("venue", "")
        authors = bib.get("author", "").split(" and ") if bib.get("author") else []

        pub_url = pub_filled.get("pub_url", "")
        eprint = bib.get("eprint", "")
        arxiv = ""
        if eprint and "arxiv" in eprint.lower():
            arxiv = eprint if eprint.startswith("http") else f"https://arxiv.org/abs/{eprint}"

        pub = {
            "title": title,
            "year": year,
            "venue": venue,
            "citationCount": citation_count,
            "url": pub_url,
            "authors": authors,
            "pdf": "",
        }
        if arxiv:
            pub["arxiv"] = arxiv
        raw_publications.append(pub)

        # Citation history — scholarly provides cites_per_year directly.
        # Google Scholar lists multiple versions of the same paper (arXiv,
        # conference, journal). Their citation sets mostly overlap — Google
        # Scholar deduplicates citers internally — so we merge duplicates as:
        #   - citationCount: max (the main entry subsumes the others)
        #   - cites_per_year: element-wise max per year (avoids double-counting
        #     while preserving any years only captured by a minor version)
        cites_per_year = pub_filled.get("cites_per_year", {})
        if cites_per_year or citation_count > 0:
            paper_key = _paper_key(title)
            new_by_year = {str(y): c for y, c in cites_per_year.items()}
            existing = citation_papers.get(paper_key)
            if existing:
                # Merge: max citationCount, element-wise max for cites_per_year
                merged_by_year = dict(existing.get("citations_by_year", {}))
                for y, c in new_by_year.items():
                    merged_by_year[y] = max(merged_by_year.get(y, 0), c)
                citation_papers[paper_key] = {
                    "title": existing["title"] if existing["citationCount"] >= citation_count else title,
                    "citationCount": max(existing["citationCount"], citation_count),
                    "citations_by_year": merged_by_year,
                }
            else:
                citation_papers[paper_key] = {
                    "title": title,
                    "citationCount": citation_count,
                    "citations_by_year": new_by_year,
                }

    # Deduplicate publications: keep the one with more citations for each title
    publications = _deduplicate_by_title(raw_publications)
    print(f"  After deduplication: {len(publications)} (from {len(raw_publications)})")

    publications = _merge_manual_and_sort(publications)

    # Use the author-level citation data from Google Scholar's profile sidebar.
    # This is the exact aggregate shown on the profile — already deduplicated
    # across papers and versions by Google Scholar internally.
    # Falls back to summing per-paper data if author-level data is unavailable.
    author_citedby = author.get("citedby", 0)
    author_cites_per_year = author.get("cites_per_year", {})

    if author_cites_per_year:
        aggregate = {str(y): c for y, c in sorted(author_cites_per_year.items())}
    else:
        # Fallback: build aggregate from per-paper citation histories
        aggregate = {}
        for paper_data in citation_papers.values():
            for year, count in paper_data.get("citations_by_year", {}).items():
                aggregate[year] = aggregate.get(year, 0) + count
        aggregate = dict(sorted(aggregate.items()))

    citation_history = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "google_scholar",
        "citedby": author_citedby,
        "aggregate": aggregate,
        "papers": citation_papers,
    }

    return publications, citation_history


def main():
    parser = argparse.ArgumentParser(description="Update publications and citation data.")
    parser.add_argument(
        "--source",
        choices=["s2", "scholar"],
        default="s2",
        help="Data source: 's2' for Semantic Scholar (default), 'scholar' for Google Scholar",
    )
    args = parser.parse_args()

    if args.source == "scholar":
        print("Fetching from Google Scholar...")
        out_json = os.path.join(SCRIPT_DIR, "media", "publications_scholar.json")
        cache_path = os.path.join(SCRIPT_DIR, "media", "citation_history_scholar.json")

        try:
            publications, citation_history = fetch_from_google_scholar()
        except Exception as e:
            # Google Scholar rate-limits aggressively. If the fetch fails,
            # keep the previously cached files and exit gracefully.
            print(f"\n  Error: {e}")
            if os.path.exists(out_json) and os.path.exists(cache_path):
                print("  Using previously cached Scholar data (files unchanged).")
            else:
                print("  No cached data available. Try again after a few minutes.")
            return

        print(f"Total publications: {len(publications)}")

        with open(out_json, "w") as f:
            json.dump(publications, f, indent=2)
        print(f"Saved {out_json}")

        with open(cache_path, "w") as f:
            json.dump(citation_history, f, indent=2)
        print(f"Saved {cache_path}")

        # Print summary
        total = citation_history.get("citedby") or sum(citation_history["aggregate"].values())
        print(f"\n{len(publications)} publications, {total} total citations:")
        for year in sorted(citation_history["aggregate"].keys()):
            print(f"    {year}: {citation_history['aggregate'][year]}")
    else:
        main_s2()


def main_s2():
    print("Fetching publications from Semantic Scholar...")
    papers = fetch_all_publications()

    print(f"Total papers fetched: {len(papers)}")
    papers = _deduplicate_by_title(papers)
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

    # Fetch citation history
    print("\nFetching citation history...")
    fetch_citation_history(publications)


if __name__ == "__main__":
    main()
