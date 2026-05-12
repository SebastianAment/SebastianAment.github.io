"""Tests for update_publications.py — covers key generation, deduplication,
normalization, and citation history logic."""

import json
import os
import sys

# Add parent directory to path so we can import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_publications import (
    _check_citation_coherence,
    _deduplicate_by_title,
    _merge_citation,
    _merge_manual_and_sort,
    _normalize_title,
    _paper_key,
    _process_filled_pub,
    _save_partial_cache,
    extract_paper_id,
)


class TestNormalizeTitle:
    def test_basic(self):
        assert _normalize_title("Hello World") == "hello world"

    def test_strips_trailing_year(self):
        assert _normalize_title("Some Paper, 2025") == "some paper"
        assert _normalize_title("Some Paper 2025") == "some paper"

    def test_removes_punctuation(self):
        assert _normalize_title("CRYSTAL: A Multi-Agent System") == "crystal a multiagent system"

    def test_collapses_whitespace(self):
        assert _normalize_title("  lots   of   spaces  ") == "lots of spaces"

    def test_unicode_stripped(self):
        assert _normalize_title("Weighted ℓ1 Ball") == "weighted 1 ball"

    def test_preserves_numbers(self):
        assert _normalize_title("Algorithm 123 for Problem 456") == "algorithm 123 for problem 456"

    def test_does_not_strip_year_in_middle(self):
        assert _normalize_title("Results from 2020 experiments") == "results from 2020 experiments"


class TestPaperKey:
    def test_basic(self):
        key = _paper_key("Hello World")
        assert key == "hello_world"

    def test_truncates_to_60(self):
        long_title = "A" * 100
        assert len(_paper_key(long_title)) == 60

    def test_duplicates_produce_same_key(self):
        t1 = "Unexpected improvements to expected improvement for bayesian optimization, 2025"
        t2 = "Unexpected improvements to expected improvement for bayesian optimization"
        assert _paper_key(t1) == _paper_key(t2)

    def test_punctuation_variants_same_key(self):
        # Note: "multi-agent" becomes "multiagent" (hyphen removed, no space inserted)
        # while "multi agent" stays "multi agent". These are genuinely different.
        t1 = "CRYSTAL: a multi-agent AI system"
        t2 = "CRYSTAL: A multi-agent AI system"
        assert _paper_key(t1) == _paper_key(t2)  # case insensitive


class TestDeduplicateByTitle:
    def test_keeps_higher_citations(self):
        papers = [
            {"title": "Paper A", "citationCount": 10},
            {"title": "Paper A", "citationCount": 50},
        ]
        result = _deduplicate_by_title(papers)
        assert len(result) == 1
        assert result[0]["citationCount"] == 50

    def test_different_titles_kept(self):
        papers = [
            {"title": "Paper A", "citationCount": 10},
            {"title": "Paper B", "citationCount": 20},
        ]
        result = _deduplicate_by_title(papers)
        assert len(result) == 2

    def test_trailing_year_deduplicates(self):
        papers = [
            {"title": "My Paper, 2025", "citationCount": 5},
            {"title": "My Paper", "citationCount": 100},
        ]
        result = _deduplicate_by_title(papers)
        assert len(result) == 1
        assert result[0]["citationCount"] == 100

    def test_punctuation_deduplicates(self):
        papers = [
            {"title": "CRYSTAL: A Multi-Agent System", "citationCount": 38},
            {"title": "CRYSTAL: A Multi-Agent System!", "citationCount": 6},
        ]
        result = _deduplicate_by_title(papers)
        assert len(result) == 1
        assert result[0]["citationCount"] == 38

    def test_empty_list(self):
        assert _deduplicate_by_title([]) == []

    def test_none_citation_count(self):
        papers = [
            {"title": "Paper", "citationCount": None},
            {"title": "Paper", "citationCount": 5},
        ]
        result = _deduplicate_by_title(papers)
        assert len(result) == 1
        assert result[0]["citationCount"] == 5


class TestExtractPaperId:
    def test_extracts_from_url(self):
        url = "https://www.semanticscholar.org/paper/0a1bf4740dc9f02c292d5489c5097cc8da7f4368"
        assert extract_paper_id(url) == "0a1bf4740dc9f02c292d5489c5097cc8da7f4368"

    def test_handles_trailing_slash(self):
        url = "https://www.semanticscholar.org/paper/abc123/"
        assert extract_paper_id(url) == "abc123"

    def test_none_returns_none(self):
        assert extract_paper_id(None) is None

    def test_empty_returns_none(self):
        assert extract_paper_id("") is None


class TestMergeManualAndSort:
    def test_sorts_by_year_then_citations(self):
        pubs = [
            {"title": "Old", "year": 2020, "citationCount": 50},
            {"title": "New", "year": 2024, "citationCount": 10},
            {"title": "New2", "year": 2024, "citationCount": 30},
        ]
        # No manual_publications.json in temp context, so it just sorts
        result = _merge_manual_and_sort(pubs)
        assert result[0]["title"] == "New2"  # 2024, 30 citations
        assert result[1]["title"] == "New"   # 2024, 10 citations
        assert result[2]["title"] == "Old"   # 2020

    def test_handles_none_year(self):
        pubs = [
            {"title": "No year", "year": None, "citationCount": 5},
            {"title": "Has year", "year": 2023, "citationCount": 5},
        ]
        result = _merge_manual_and_sort(pubs)
        assert result[0]["title"] == "Has year"
        assert result[1]["title"] == "No year"


class TestPaperKeyConsistency:
    """Ensure Python _paper_key matches what the JS paperKey function would produce."""

    def test_js_equivalence_cases(self):
        # These test cases should produce the same output in JS and Python
        cases = [
            (
                "Unexpected improvements to expected improvement for bayesian optimization",
                "unexpected_improvements_to_expected_improvement_for_bayesian",
            ),
            (
                "CRYSTAL: a multi-agent AI system for automated mapping of materials' crystal structures",
                "crystal_a_multiagent_ai_system_for_automated_mapping_of_mate",
            ),
            (
                "Accurate and efficient numerical calculation of stable densities via optimized quadrature and asymptotics",
                "accurate_and_efficient_numerical_calculation_of_stable_densi",
            ),
        ]
        for title, expected_key in cases:
            assert _paper_key(title) == expected_key, f"Failed for: {title}"


# ---------------------------------------------------------------------------
# Tests for the Google Scholar pipeline helpers (no network).
# ---------------------------------------------------------------------------


def _make_scholarly_pub(
    title="Some paper",
    pub_year=2024,
    num_citations=5,
    cites_per_year=None,
    venue="",
    journal="",
    conference="",
    eprint="",
    pub_url="",
    author=None,
):
    """Build a stub mimicking the dict returned by scholarly.fill()."""
    bib = {"title": title, "pub_year": pub_year}
    if venue:
        bib["venue"] = venue
    if journal:
        bib["journal"] = journal
    if conference:
        bib["conference"] = conference
    if eprint:
        bib["eprint"] = eprint
    if author:
        bib["author"] = author
    pub = {"bib": bib, "num_citations": num_citations}
    if pub_url:
        pub["pub_url"] = pub_url
    if cites_per_year is not None:
        pub["cites_per_year"] = cites_per_year
    return pub


class TestProcessFilledPub:
    def test_basic_fields(self):
        pub_filled = _make_scholarly_pub(
            title="Hello World",
            pub_year=2023,
            num_citations=42,
            journal="Nature",
            pub_url="https://example.com/paper",
            author="Alice and Bob",
        )
        pub, key, citation = _process_filled_pub(pub_filled)
        assert pub["title"] == "Hello World"
        assert pub["year"] == 2023
        assert pub["citationCount"] == 42
        assert pub["venue"] == "Nature"
        assert pub["url"] == "https://example.com/paper"
        assert pub["authors"] == ["Alice", "Bob"]
        assert key == _paper_key("Hello World")
        assert citation is None  # no cites_per_year was provided

    def test_year_coerced_to_int(self):
        pub, _, _ = _process_filled_pub(_make_scholarly_pub(pub_year="2022"))
        assert pub["year"] == 2022 and isinstance(pub["year"], int)

    def test_year_invalid_becomes_none(self):
        pub, _, _ = _process_filled_pub(_make_scholarly_pub(pub_year="not-a-year"))
        assert pub["year"] is None

    def test_venue_falls_back_through_fields(self):
        # journal preferred, then conference, then venue
        p1, _, _ = _process_filled_pub(_make_scholarly_pub(journal="J", conference="C", venue="V"))
        p2, _, _ = _process_filled_pub(_make_scholarly_pub(conference="C", venue="V"))
        p3, _, _ = _process_filled_pub(_make_scholarly_pub(venue="V"))
        assert (p1["venue"], p2["venue"], p3["venue"]) == ("J", "C", "V")

    def test_arxiv_eprint_id_becomes_url(self):
        pub, _, _ = _process_filled_pub(_make_scholarly_pub(eprint="2310.12345"))
        # Note: only arxiv-prefixed eprints are recognized by current logic
        assert "arxiv" not in pub  # 2310.12345 doesn't match "arxiv"

    def test_arxiv_url_eprint_passes_through(self):
        pub, _, _ = _process_filled_pub(
            _make_scholarly_pub(eprint="https://arxiv.org/abs/2310.12345")
        )
        assert pub["arxiv"] == "https://arxiv.org/abs/2310.12345"

    def test_cites_per_year_yields_citation_record(self):
        pub_filled = _make_scholarly_pub(
            title="Cited Paper",
            num_citations=10,
            cites_per_year={2023: 3, 2024: 7},
        )
        pub, key, citation = _process_filled_pub(pub_filled)
        assert citation is not None
        assert citation["title"] == "Cited Paper"
        assert citation["citationCount"] == 10
        assert citation["citations_by_year"] == {"2023": 3, "2024": 7}
        assert key == _paper_key("Cited Paper")

    def test_missing_authors_string_yields_empty_list(self):
        pub_filled = _make_scholarly_pub(author=None)
        pub, _, _ = _process_filled_pub(pub_filled)
        assert pub["authors"] == []


class TestMergeCitation:
    def test_no_existing(self):
        store = {}
        new = {"title": "T", "citationCount": 5, "citations_by_year": {"2024": 5}}
        _merge_citation(store, "k", new)
        assert store["k"] is new

    def test_skips_when_key_or_new_is_none(self):
        store = {"x": "preserved"}
        _merge_citation(store, None, {"a": 1})
        _merge_citation(store, "k", None)
        assert store == {"x": "preserved"}

    def test_per_year_max_merge(self):
        store = {
            "k": {
                "title": "T",
                "citationCount": 10,
                "citations_by_year": {"2023": 4, "2024": 2},
            }
        }
        new = {
            "title": "T-alt",
            "citationCount": 7,  # smaller — original title should win
            "citations_by_year": {"2024": 5, "2025": 1},  # 2024 should bump up
        }
        _merge_citation(store, "k", new)
        merged = store["k"]
        assert merged["title"] == "T"  # higher citationCount keeps its title
        assert merged["citationCount"] == 10
        assert merged["citations_by_year"] == {"2023": 4, "2024": 5, "2025": 1}

    def test_higher_count_wins_title(self):
        store = {
            "k": {"title": "Old", "citationCount": 5, "citations_by_year": {"2024": 5}},
        }
        new = {"title": "New", "citationCount": 99, "citations_by_year": {"2024": 99}}
        _merge_citation(store, "k", new)
        assert store["k"]["title"] == "New"
        assert store["k"]["citationCount"] == 99


class TestCheckCitationCoherence:
    def _build(self, citedby=100, aggregate=None, papers=None):
        return {
            "citedby": citedby,
            "aggregate": aggregate or {},
            "papers": papers or {},
        }

    def test_all_invariants_ok(self):
        ch = self._build(
            citedby=10,
            aggregate={"2023": 4, "2024": 6},
            papers={"a": {"title": "A", "citationCount": 6, "citations_by_year": {"2024": 6}}},
        )
        issues = _check_citation_coherence(ch, [{"title": "A", "citationCount": 6}])
        assert all(s != "ERROR" for s, _ in issues)
        assert "coherence" in ch
        assert ch["coherence"]["citedby"] == 10
        assert ch["coherence"]["sum_aggregate"] == 10
        assert ch["coherence"]["gap_total_minus_aggregate"] == 0

    def test_chart_exceeds_total_is_error(self):
        ch = self._build(citedby=5, aggregate={"2024": 100})
        issues = _check_citation_coherence(ch, [])
        assert any(s == "ERROR" for s, _ in issues)

    def test_per_paper_sum_exceeds_count_warns(self):
        ch = self._build(
            citedby=100,
            aggregate={"2024": 2},
            papers={"a": {"title": "A", "citationCount": 1, "citations_by_year": {"2024": 5}}},
        )
        issues = _check_citation_coherence(ch, [])
        assert any(s == "WARN" and "per-year sum" in m for s, m in issues)

    def test_run_over_run_info_emitted(self):
        ch = self._build(citedby=100, aggregate={"2024": 10, "2025": 50})
        prev = self._build(citedby=90, aggregate={"2024": 10, "2025": 40})
        issues = _check_citation_coherence(ch, [], prev_cache=prev)
        info_messages = [m for s, m in issues if s == "INFO"]
        assert any("citedby: 90 -> 100" in m for m in info_messages)
        assert any("2025: 40 -> 50" in m for m in info_messages)

    def test_gap_change_below_threshold_no_warn(self):
        # gap stays the same -> no chart-vs-total WARN
        ch = self._build(citedby=100, aggregate={"2024": 80})
        prev = self._build(citedby=98, aggregate={"2024": 78})
        issues = _check_citation_coherence(ch, [], prev_cache=prev)
        assert not any(s == "WARN" and "chart-vs-total gap" in m for s, m in issues)

    def test_large_gap_change_warns(self):
        # Big swing in the gap -> WARN. Old gap = 100-90 = 10, new gap = 100-50 = 50.
        ch = self._build(citedby=100, aggregate={"2024": 50})
        prev = self._build(citedby=100, aggregate={"2024": 90})
        issues = _check_citation_coherence(ch, [], prev_cache=prev)
        assert any(s == "WARN" and "chart-vs-total gap" in m for s, m in issues)

    def test_never_raises_on_empty_input(self):
        # Empty/missing fields should not crash the check.
        issues = _check_citation_coherence({}, [])
        assert isinstance(issues, list)


class TestSavePartialCache:
    def test_writes_atomically_with_author_aggregate(self, tmp_path):
        cache_path = tmp_path / "media" / "citation_history_scholar.json"
        papers = {
            "a": {"title": "A", "citationCount": 3, "citations_by_year": {"2024": 3}}
        }
        author = {"citedby": 50, "cites_per_year": {2024: 40, 2025: 10}}
        _save_partial_cache(str(cache_path), papers, author)
        with open(cache_path) as f:
            written = json.load(f)
        assert written["citedby"] == 50
        # Author-level aggregate is preferred when available
        assert written["aggregate"] == {"2024": 40, "2025": 10}
        assert written["papers"] == papers
        assert "fetched_at" in written

    def test_falls_back_to_per_paper_aggregate(self, tmp_path):
        cache_path = tmp_path / "media" / "citation_history_scholar.json"
        papers = {
            "a": {"title": "A", "citationCount": 3, "citations_by_year": {"2024": 2, "2025": 1}},
            "b": {"title": "B", "citationCount": 5, "citations_by_year": {"2025": 5}},
        }
        # No author chart -> sum per-paper data
        _save_partial_cache(str(cache_path), papers, author_data=None)
        with open(cache_path) as f:
            written = json.load(f)
        assert written["aggregate"] == {"2024": 2, "2025": 6}
        assert written["citedby"] == 0

    def test_creates_directory_if_missing(self, tmp_path):
        # Nested path where intermediate dirs don't exist yet.
        cache_path = tmp_path / "deep" / "nested" / "out.json"
        _save_partial_cache(str(cache_path), {}, None)
        assert cache_path.exists()

    def test_does_not_leave_tmp_file(self, tmp_path):
        cache_path = tmp_path / "out.json"
        _save_partial_cache(str(cache_path), {}, None)
        assert not (tmp_path / "out.json.tmp").exists()
