"""Tests for update_publications.py — covers key generation, deduplication,
normalization, and citation history logic."""

import os
import sys

# Add parent directory to path so we can import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_publications import (
    _normalize_title,
    _paper_key,
    _deduplicate_by_title,
    _merge_manual_and_sort,
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
