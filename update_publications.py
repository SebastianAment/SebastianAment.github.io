#!/usr/bin/env python3
"""Fetches publications and citation history, generates JSON data files for
sebastianament.github.io.

Usage:
  # Semantic Scholar (default, used by CI weekly):
  python3 update_publications.py

  # Google Scholar (more comprehensive, run locally):
  /Users/sebastianament/opt/miniconda3/bin/python3 update_publications.py --source scholar

  # Fill gaps for papers that failed on a previous Scholar run:
  /Users/sebastianament/opt/miniconda3/bin/python3 update_publications.py --infill

  # With Semantic Scholar API key for higher rate limits:
  S2_API_KEY=your_key python3 update_publications.py

  # With ScraperAPI key for reliable Google Scholar fetches:
  SCHOLARLY_SCRAPER_API_KEY=your_key python3 update_publications.py --source scholar

Options:
  --source s2          Semantic Scholar API (default, reliable for CI)
  --source scholar     Google Scholar via `scholarly` (higher counts, fragile)
  --infill             Re-fetch only papers missing citation history data
  --scholar-proxy MODE One of: auto (default), direct, free, scraperapi.
                       'auto' tries direct, then scraperapi (if key), then free.
                       Free proxies often serve cached pages and yield stale
                       per-year counts; prefer 'direct' or 'scraperapi'.

Output files:
  media/publications.json              S2 publications list
  media/citation_history.json          S2 per-paper citation time series
  media/publications_scholar.json      Google Scholar publications list
  media/citation_history_scholar.json  Google Scholar citation time series
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
FIELDS = "title,year,venue,citationCount,url,externalIds,authors,citationStyles"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Optional Semantic Scholar API key (free tier: 100 req/sec vs 100/5min without)
S2_API_KEY = os.environ.get("S2_API_KEY")

# Output paths (defined once and referenced everywhere).
S2_PUBS_PATH = os.path.join(SCRIPT_DIR, "media", "publications.json")
S2_HISTORY_PATH = os.path.join(SCRIPT_DIR, "media", "citation_history.json")
SCHOLAR_PUBS_PATH = os.path.join(SCRIPT_DIR, "media", "publications_scholar.json")
SCHOLAR_HISTORY_PATH = os.path.join(SCRIPT_DIR, "media", "citation_history_scholar.json")


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
        bibtex = (paper.get("citationStyles") or {}).get("bibtex", "")
        if bibtex:
            pub["bibtex"] = bibtex
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
    cache = {}
    if os.path.exists(S2_HISTORY_PATH):
        with open(S2_HISTORY_PATH) as f:
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

    if _write_json_if_changed(S2_HISTORY_PATH, result):
        print(f"  Saved {S2_HISTORY_PATH} ({updated} papers updated)")
    else:
        print(f"  No substantive changes — {S2_HISTORY_PATH} unchanged.")

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


def _write_json_if_changed(path, data, volatile_keys=("fetched_at", "coherence")):
    """Write JSON to *path* only if the substantive content has changed.

    Strips *volatile_keys* (timestamps, coherence diffs) before comparing so
    that re-runs with identical citation data are true no-ops on disk.
    Returns True if the file was written, False if skipped.
    """
    def _strip(d):
        return {k: v for k, v in d.items() if k not in volatile_keys} if isinstance(d, dict) else d

    try:
        with open(path) as f:
            old = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        old = None

    if old is not None and _strip(old) == _strip(data):
        return False

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return True


def _check_citation_coherence(citation_history, publications, prev_cache=None,
                              gap_abs_threshold=3, gap_rel_threshold=0.01):
    """Sanity-check that citation totals and the per-year history line up.

    Google Scholar's per-year chart only covers ~11 years, so the chart sum is
    typically *less than* the headline 'Cited by' total — that's expected.
    This check looks for *unexpected* inconsistencies and prints a warning
    section. It never raises.

    Side effect: writes a 'coherence' block back into ``citation_history``.

    Returns a list of (severity, message) tuples; severity is 'INFO', 'WARN',
    or 'ERROR'. ERROR means a logical impossibility (e.g. chart > total).
    """
    issues = []
    citedby = citation_history.get("citedby") or 0
    aggregate = citation_history.get("aggregate", {})
    papers = citation_history.get("papers", {})

    sum_aggregate = sum(aggregate.values())
    sum_paper_counts = sum(p.get("citationCount", 0) for p in publications)

    # 1. Hard invariant: chart sum cannot exceed total cited-by.
    if sum_aggregate > citedby and citedby > 0:
        issues.append((
            "ERROR",
            f"sum(aggregate)={sum_aggregate} > citedby={citedby} "
            f"(impossible — per-year chart cannot exceed total)"
        ))

    # 2. Soft invariant: the gap (older-than-chart citations) should be small
    #    and stable. A growing gap usually means newer years are under-counted.
    gap = citedby - sum_aggregate
    if citedby > 0 and prev_cache:
        prev_citedby = prev_cache.get("citedby") or 0
        prev_gap = prev_citedby - sum(prev_cache.get("aggregate", {}).values())
        delta_gap = gap - prev_gap
        if abs(delta_gap) >= gap_abs_threshold and abs(delta_gap) / max(citedby, 1) > gap_rel_threshold:
            issues.append((
                "WARN",
                f"chart-vs-total gap moved by {delta_gap:+d} since last run "
                f"(prev gap={prev_gap}, now={gap}). New citations may be "
                f"missing from recent-year bars; see if Scholar is logged in."
            ))

    # 3. Per-paper consistency: each paper's per-year sum should not exceed
    #    its own citationCount (the paper-level bar chart is bounded by its
    #    headline number).
    bad_papers = []
    for key, pd in papers.items():
        cby = pd.get("citationCount", 0)
        s = sum(pd.get("citations_by_year", {}).values())
        if s > cby:
            bad_papers.append((pd.get("title", key)[:60], s, cby))
    if bad_papers:
        issues.append((
            "WARN",
            f"{len(bad_papers)} paper(s) have per-year sum > citationCount "
            f"(first: '{bad_papers[0][0]}' sum={bad_papers[0][1]} "
            f"vs count={bad_papers[0][2]})"
        ))

    # 4. Informational deltas vs prior run.
    if prev_cache:
        prev_citedby = prev_cache.get("citedby") or 0
        prev_agg = prev_cache.get("aggregate", {})
        if prev_citedby and citedby and citedby != prev_citedby:
            issues.append((
                "INFO",
                f"citedby: {prev_citedby} -> {citedby} ({citedby - prev_citedby:+d})"
            ))
        for y in sorted(set(prev_agg) | set(aggregate)):
            old = prev_agg.get(y, 0)
            new = aggregate.get(y, 0)
            if old != new:
                issues.append(("INFO", f"  {y}: {old} -> {new} ({new - old:+d})"))

    # 5. Print a structured summary block.
    print("\nCoherence check:")
    print(f"  citedby (total):           {citedby}")
    print(f"  sum(aggregate per year):   {sum_aggregate}  (gap from total: {gap})")
    print(f"  sum(paper.citationCount):  {sum_paper_counts}")
    if not issues:
        print("  All invariants OK.")
    else:
        # Order: ERROR first, then WARN, then INFO.
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        for sev, msg in sorted(issues, key=lambda i: order.get(i[0], 99)):
            print(f"  [{sev}] {msg}")

    citation_history["coherence"] = {
        "citedby": citedby,
        "sum_aggregate": sum_aggregate,
        "sum_paper_counts": sum_paper_counts,
        "gap_total_minus_aggregate": gap,
        "issues": [{"severity": s, "message": m} for s, m in issues],
    }
    return issues


def _setup_scholar_proxy(mode="auto"):
    """Set up scholarly's connection mode.

    Modes:
      'auto'        : ScraperAPI (if key set) -> direct (no proxy). On a fetch
                      failure, the caller may fall back to free proxies via
                      ``_enable_free_proxy_fallback``.
      'direct'      : no proxy.
      'scraperapi'  : require SCHOLARLY_SCRAPER_API_KEY env var; raises if missing.
      'free'        : free public proxies (often serve cached pages — discouraged).

    Returns the mode that was actually activated (one of 'direct', 'free',
    'scraperapi'). The returned value drives downstream throttling.
    """
    from scholarly import scholarly, ProxyGenerator

    api_key = os.environ.get("SCHOLARLY_SCRAPER_API_KEY")

    if mode == "direct":
        print("  Using direct connection (no proxy).")
        return "direct"

    if mode in ("scraperapi", "auto") and api_key:
        try:
            pg = ProxyGenerator()
            ok = pg.ScraperAPI(api_key)
            if ok:
                scholarly.use_proxy(pg)
                print("  Using ScraperAPI.")
                return "scraperapi"
        except Exception as e:
            print(f"  ScraperAPI setup failed: {e}")
        if mode == "scraperapi":
            raise RuntimeError("ScraperAPI key not provided or setup failed.")

    if mode == "free":
        try:
            pg = ProxyGenerator()
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            print("  Using free proxy rotation (warning: may serve cached pages).")
            return "free"
        except Exception as e:
            print(f"  Free proxy setup failed ({e}); falling back to direct.")
            return "direct"

    # auto with no scraperapi key → start direct, only fall back to free on failure
    print("  Using direct connection (no proxy). Will fall back to free proxies if blocked.")
    return "direct"


def _enable_free_proxy_fallback():
    """Switch scholarly to free proxies after a direct attempt fails."""
    from scholarly import scholarly, ProxyGenerator
    try:
        pg = ProxyGenerator()
        pg.FreeProxies()
        scholarly.use_proxy(pg)
        print("  Switched to free proxy rotation as a fallback.")
        return True
    except Exception as e:
        print(f"  Could not start free proxy fallback: {e}")
        return False


def _process_filled_pub(pub_filled):
    """Convert a scholarly-filled publication into our (pub, citation_record) shape.

    Returns (pub_dict, paper_key, citation_dict_or_None).
    """
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

    cites_per_year = pub_filled.get("cites_per_year", {})
    citation = None
    if cites_per_year:
        citation = {
            "title": title,
            "citationCount": citation_count,
            "citations_by_year": {str(y): c for y, c in cites_per_year.items()},
        }
    return pub, _paper_key(title), citation


def _merge_citation(citation_papers, key, new):
    """Merge a new citation record into the running map (max per year)."""
    if key is None or new is None:
        return
    existing = citation_papers.get(key)
    if not existing:
        citation_papers[key] = new
        return
    merged_by_year = dict(existing.get("citations_by_year", {}))
    for y, c in new.get("citations_by_year", {}).items():
        merged_by_year[y] = max(merged_by_year.get(y, 0), c)
    citation_papers[key] = {
        "title": existing["title"] if existing["citationCount"] >= new["citationCount"] else new["title"],
        "citationCount": max(existing["citationCount"], new["citationCount"]),
        "citations_by_year": merged_by_year,
    }


def _save_partial_cache(cache_path, citation_papers, author_data=None):
    """Persist citation history mid-run so a crash doesn't lose work."""
    if author_data and author_data.get("cites_per_year"):
        # Prefer the author-level chart aggregate when available — it's GS's
        # own deduplicated number, not our per-paper sum.
        aggregate = {
            str(y): c for y, c in sorted(author_data["cites_per_year"].items())
        }
    else:
        aggregate = {}
        for pd in citation_papers.values():
            for y, c in pd.get("citations_by_year", {}).items():
                aggregate[y] = aggregate.get(y, 0) + c
        aggregate = dict(sorted(aggregate.items()))

    payload = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "google_scholar",
        "citedby": (author_data or {}).get("citedby", 0),
        "aggregate": aggregate,
        "papers": citation_papers,
    }
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, cache_path)


def _fetch_with_proxy_fallback(proxy_mode):
    """Fetch the author profile, falling back to free proxies on failure.

    The author profile contains the per-year citation chart that we use as the
    authoritative aggregate. We try the configured connection first, since
    free proxies often serve stale cached HTML that under-counts recent years.
    """
    from scholarly import scholarly

    def _do_fetch():
        author = scholarly.search_author_id(SCHOLAR_AUTHOR_ID)
        return scholarly.fill(author, sections=["basics", "publications"])

    try:
        return _do_fetch()
    except Exception as e:
        # Only fall back to free proxies if we weren't already on a proxy.
        if proxy_mode not in ("auto", "direct"):
            raise
        print(f"  Direct fetch failed ({e}); enabling free-proxy fallback.")
        if not _enable_free_proxy_fallback():
            raise
        return _do_fetch()


def fetch_from_google_scholar(proxy_mode="auto"):
    """Fetch publications and citation history from Google Scholar."""
    from scholarly import scholarly

    proxy_mode = _setup_scholar_proxy(proxy_mode)

    print("  Looking up Google Scholar profile...")
    author = _fetch_with_proxy_fallback(proxy_mode)

    raw_publications = []
    citation_papers = {}
    failed = []  # list of (index, stub) to retry at the end

    pubs = author.get("publications", [])
    print(f"  Found {len(pubs)} publications. Filling details...")

    # Throttle between fills to avoid tripping Google Scholar rate limits.
    # Direct connection: a small delay is enough. With a proxy: be more cautious.
    fill_delay = 2.0 if proxy_mode in ("free", "scraperapi") else 0.5

    for i, pub_stub in enumerate(pubs):
        # Progress log (decoupled from throttling).
        if i > 0 and i % 5 == 0:
            print(f"    {i}/{len(pubs)} done...")
        if i > 0:
            time.sleep(fill_delay)

        try:
            pub_filled = scholarly.fill(pub_stub)
        except Exception as e:
            stub_title = pub_stub.get("bib", {}).get("title", f"index {i}")
            print(f"    Warning: could not fill \"{stub_title[:60]}\": {e}")
            failed.append((i, pub_stub))
            pub_filled = pub_stub

        pub, key, citation = _process_filled_pub(pub_filled)
        raw_publications.append(pub)
        _merge_citation(citation_papers, key, citation)

        # Persist incrementally so a crash mid-run preserves progress.
        if i and i % 10 == 0:
            _save_partial_cache(SCHOLAR_HISTORY_PATH, citation_papers, author)

    # Retry failures once with longer waits + proxy fallback if not already on it.
    if failed:
        print(f"  Retrying {len(failed)} papers that failed on first pass...")
        if proxy_mode == "direct":
            _enable_free_proxy_fallback()
        # title -> pub mapping so the post-retry update is O(1) per paper.
        pubs_by_title = {p["title"]: p for p in raw_publications}
        still_failed = []
        for idx, stub in failed:
            stub_title = stub.get("bib", {}).get("title", f"index {idx}")
            time.sleep(5)
            try:
                pub_filled = scholarly.fill(stub)
            except Exception:
                still_failed.append(stub_title)
                continue
            _, key, citation = _process_filled_pub(pub_filled)
            _merge_citation(citation_papers, key, citation)
            # Update the publication entry's citationCount/year if we have better data now.
            p = pubs_by_title.get(stub_title)
            if p is not None:
                if pub_filled.get("num_citations") is not None:
                    p["citationCount"] = pub_filled["num_citations"]
                bib = pub_filled.get("bib", {})
                if bib.get("pub_year"):
                    try:
                        p["year"] = int(bib["pub_year"])
                    except (ValueError, TypeError):
                        pass
        if still_failed:
            print(f"  Could not fill {len(still_failed)} papers after retry:")
            for t in still_failed:
                print(f"    - {t[:80]}")
        else:
            print("  All retries succeeded.")

    # Deduplicate publications: keep the one with more citations for each title
    publications = _deduplicate_by_title(raw_publications)
    print(f"  After deduplication: {len(publications)} (from {len(raw_publications)})")

    publications = _merge_manual_and_sort(publications)

    # Merge with previously cached citation history to preserve data from
    # papers that failed to fill this run (rate limiting).
    if os.path.exists(SCHOLAR_HISTORY_PATH):
        with open(SCHOLAR_HISTORY_PATH) as f:
            prev_cache = json.load(f)
        for key, prev in prev_cache.get("papers", {}).items():
            if key not in citation_papers and prev.get("citations_by_year"):
                citation_papers[key] = prev

    # Use the author-level citation data from Google Scholar's profile sidebar.
    # This is the exact aggregate shown on the profile — already deduplicated
    # across papers and versions by Google Scholar internally.
    # Falls back to summing per-paper data if author-level data is unavailable.
    author_citedby = author.get("citedby", 0)
    author_cites_per_year = author.get("cites_per_year", {})

    if author_cites_per_year:
        aggregate = {str(y): c for y, c in sorted(author_cites_per_year.items())}
    else:
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


def _infill_missing_citations():
    """Attempt to fill citation history only for papers with missing cites_per_year."""
    from scholarly import scholarly, ProxyGenerator

    if not os.path.exists(SCHOLAR_HISTORY_PATH):
        print("No cached citation history found. Run --source scholar first.")
        return

    with open(SCHOLAR_HISTORY_PATH) as f:
        cache = json.load(f)

    papers = cache.get("papers", {})

    # Find papers with empty citations_by_year in the cache
    missing = {k: v for k, v in papers.items() if not v.get("citations_by_year")}

    # Also find papers in publications that aren't in the cache at all
    if os.path.exists(SCHOLAR_PUBS_PATH):
        with open(SCHOLAR_PUBS_PATH) as f:
            pubs = json.load(f)
        for pub in pubs:
            key = _paper_key(pub.get("title", ""))
            if key and key not in papers and pub.get("citationCount", 0) > 0:
                missing[key] = {"title": pub["title"], "citationCount": pub["citationCount"], "citations_by_year": {}}

    if not missing:
        print("All papers already have citation history. Nothing to infill.")
        return

    print(f"Found {len(missing)} papers missing citation history:")
    for v in missing.values():
        print(f"  - {v.get('title', '?')}")

    # Set up proxy
    try:
        pg = ProxyGenerator()
        pg.FreeProxies()
        scholarly.use_proxy(pg)
        print("  Using free proxy rotation.")
    except Exception:
        print("  Could not set up proxy, using direct connection.")

    # Search and fill each missing paper
    filled = 0
    for key, paper_data in missing.items():
        title = paper_data.get("title", "")
        print(f"  Fetching: {title[:60]}...")
        time.sleep(3)

        try:
            results = scholarly.search_pubs(title)
            pub = next(results, None)
            if pub:
                pub_filled = scholarly.fill(pub)
                cites_per_year = pub_filled.get("cites_per_year", {})
                if cites_per_year:
                    papers[key]["citations_by_year"] = {str(y): c for y, c in cites_per_year.items()}
                    papers[key]["citationCount"] = pub_filled.get("num_citations", paper_data.get("citationCount", 0))
                    filled += 1
                    print(f"    Filled: {cites_per_year}")
                else:
                    print(f"    No cites_per_year available.")
            else:
                print(f"    Not found on Google Scholar.")
        except Exception as e:
            print(f"    Error: {e}")

    if filled > 0:
        # Rebuild aggregate
        aggregate = {}
        for pd in papers.values():
            for year, count in pd.get("citations_by_year", {}).items():
                aggregate[year] = aggregate.get(year, 0) + count

        cache["papers"] = papers
        cache["aggregate"] = dict(sorted(aggregate.items()))
        cache["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with open(SCHOLAR_HISTORY_PATH, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"\nInfilled {filled} papers. Saved {SCHOLAR_HISTORY_PATH}")
    else:
        print("\nNo papers could be filled this run.")


def _render_html_seo():
    """Inject static publication HTML into index.html between SEO markers."""
    index_path = os.path.join(SCRIPT_DIR, "index.html")
    # Prefer Scholar data, fall back to S2
    pubs_path = SCHOLAR_PUBS_PATH if os.path.exists(SCHOLAR_PUBS_PATH) else S2_PUBS_PATH
    if not os.path.exists(pubs_path):
        print("No publications JSON found. Run the fetch first.")
        return

    with open(pubs_path) as f:
        pubs = json.load(f)

    # Generate static HTML for each publication
    lines = []
    for pub in pubs:
        authors = ", ".join(pub.get("authors", []))
        venue = f" &mdash; {pub['venue']}" if pub.get("venue") else ""
        title = pub.get("title", "")
        year = pub.get("year") or "N/A"
        citations = pub.get("citationCount", 0)
        link = pub.get("arxiv") or pub.get("url", "")
        title_html = f'<a href="{link}">{title}</a>' if link else title
        lines.append(
            f'                <li class="publication"><strong>{title_html}</strong><br>'
            f'<span class="pub-authors">{authors}</span><br>'
            f'<span class="pub-meta">{year}{venue} &middot; {citations} citations</span></li>'
        )

    seo_block = "\n".join(lines)

    with open(index_path) as f:
        html = f.read()

    # Replace between markers
    start_marker = "<!-- PUBLICATIONS_SEO -->"
    end_marker = "<!-- /PUBLICATIONS_SEO -->"
    start_idx = html.find(start_marker)
    end_idx = html.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        print("SEO markers not found in index.html")
        return

    new_html = (
        html[: start_idx + len(start_marker)]
        + "\n"
        + seo_block
        + "\n                "
        + html[end_idx:]
    )

    with open(index_path, "w") as f:
        f.write(new_html)
    print(f"Injected {len(pubs)} publications into index.html for SEO")


def main():
    parser = argparse.ArgumentParser(description="Update publications and citation data.")
    parser.add_argument(
        "--source",
        choices=["s2", "scholar"],
        default="s2",
        help="Data source: 's2' for Semantic Scholar (default), 'scholar' for Google Scholar",
    )
    parser.add_argument(
        "--infill",
        action="store_true",
        help="Only fetch citation history for papers missing cites_per_year data",
    )
    parser.add_argument(
        "--render-html",
        action="store_true",
        help="Inject static publication HTML into index.html for SEO",
    )
    parser.add_argument(
        "--scholar-proxy",
        choices=["auto", "direct", "free", "scraperapi"],
        default="auto",
        help=(
            "Connection mode for Google Scholar. 'auto' (default): direct, "
            "falling back to free proxies if blocked. 'direct': no proxy. "
            "'free': free public proxies (may serve stale cached pages — "
            "avoid if you can). 'scraperapi': requires SCHOLARLY_SCRAPER_API_KEY."
        ),
    )
    args = parser.parse_args()

    if args.render_html:
        _render_html_seo()
    elif args.infill:
        _infill_missing_citations()
    elif args.source == "scholar":
        print("Fetching from Google Scholar...")

        # Load the previous cache *before* we overwrite it, so the coherence
        # check can show run-over-run deltas.
        prev_cache = None
        if os.path.exists(SCHOLAR_HISTORY_PATH):
            try:
                with open(SCHOLAR_HISTORY_PATH) as f:
                    prev_cache = json.load(f)
            except Exception:
                prev_cache = None

        try:
            publications, citation_history = fetch_from_google_scholar(
                proxy_mode=args.scholar_proxy
            )
        except Exception as e:
            # Google Scholar rate-limits aggressively. If the fetch fails,
            # keep the previously cached files and exit gracefully.
            print(f"\n  Error: {e}")
            if os.path.exists(SCHOLAR_PUBS_PATH) and os.path.exists(SCHOLAR_HISTORY_PATH):
                print("  Using previously cached Scholar data (files unchanged).")
            else:
                print("  No cached data available. Try again after a few minutes.")
            return

        print(f"Total publications: {len(publications)}")

        # Coherence check (warns; never raises). Mutates citation_history to
        # include a 'coherence' block so the saved JSON records the audit.
        issues = _check_citation_coherence(citation_history, publications, prev_cache)

        pubs_written = _write_json_if_changed(SCHOLAR_PUBS_PATH, publications, volatile_keys=())
        hist_written = _write_json_if_changed(SCHOLAR_HISTORY_PATH, citation_history)

        if pubs_written:
            print(f"Saved {SCHOLAR_PUBS_PATH}")
        if hist_written:
            print(f"Saved {SCHOLAR_HISTORY_PATH}")
        if not pubs_written and not hist_written:
            print("No substantive changes — Scholar files unchanged.")

        # Print summary
        total = citation_history.get("citedby") or sum(citation_history["aggregate"].values())
        print(f"\n{len(publications)} publications, {total} total citations:")
        for year in sorted(citation_history["aggregate"].keys()):
            print(f"    {year}: {citation_history['aggregate'][year]}")

        # Non-zero exit if a hard invariant was violated, but only after we've
        # written the (still-best-effort) data so the website isn't left empty.
        if any(sev == "ERROR" for sev, _ in issues):
            print("\n  WARNING: hard coherence invariant violated. Inspect output above.")
    else:
        main_s2()


def main_s2():
    print("Fetching publications from Semantic Scholar...")
    papers = fetch_all_publications()

    print(f"Total papers fetched: {len(papers)}")
    papers = _deduplicate_by_title(papers)
    print(f"After deduplication: {len(papers)}")

    publications = process_publications(papers)

    if _write_json_if_changed(S2_PUBS_PATH, publications, volatile_keys=()):
        print(f"Saved {S2_PUBS_PATH}")
    else:
        print(f"No substantive changes — {S2_PUBS_PATH} unchanged.")

    # Print summary
    print(f"\n{len(publications)} publications:")
    for pub in publications:
        print(f"  [{pub['year']}] {pub['title']} ({pub['citationCount']} citations)")

    # Fetch citation history
    print("\nFetching citation history...")
    fetch_citation_history(publications)


if __name__ == "__main__":
    main()
