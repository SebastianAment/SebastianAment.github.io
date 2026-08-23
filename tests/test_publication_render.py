"""Tests for publication-list hygiene and rendering in update_publications.py.

These lock in three things:
  1. Scholar noise (dataset stubs, supplementary PDFs, mangled citation-strings)
     never reaches the rendered list.
  2. The site owner's name is emphasised in author lists, across every spelling
     variant the upstream sources use.
  3. Third-party publication metadata is escaped before it is written into
     index.html, and URLs are restricted to http(s).

They also assert the Python and JavaScript implementations agree, since the
same rules are applied server-side (SEO block) and client-side (live list).
"""

import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import update_publications as up  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


# ── Noise filtering ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Data from: Autonomous synthesis of metastable materials",
    "Data from: Probabilistic Phase Labeling and Lattice Refinement",
    "data from: lowercase variant",
    "Sparse Bayesian Learning via Stepwise Regression: Supplementary Materials",
    "Some Paper: supplementary material",
    "Shufeng Kong, Santosh K. Suram, R. Bruce van Dover, and John M. Gregoire. 2019. "
    "CRYSTAL: A multi-agent AI system for automated mapping",
    "",
    None,
])
def test_noise_is_dropped(title):
    assert up.is_noise_publication(title) is True


@pytest.mark.parametrize("title", [
    "Unexpected improvements to expected improvement for bayesian optimization",
    "Autonomous materials synthesis via hierarchical active learning of "
    "nonequilibrium phase diagrams",
    "CRYSTAL: a multi-agent AI system for automated mapping of materials' "
    "crystal structures",
    "Advances in Sparse and Bayesian Optimization for Autonomous Scientific Discovery",
    "Robust Gaussian processes via relevance pursuit",
    "Accurate and efficient numerical calculation of stable densities",
])
def test_real_papers_are_kept(title):
    """Guards against an over-eager filter deleting genuine work."""
    assert up.is_noise_publication(title) is False


def test_filter_preserves_order_and_drops_only_noise():
    items = [
        {"title": "Real paper one"},
        {"title": "Data from: a dataset"},
        {"title": "Real paper two"},
    ]
    out = up.filter_noise_publications(items)
    assert [p["title"] for p in out] == ["Real paper one", "Real paper two"]


def test_real_scholar_data_loses_exactly_the_known_noise():
    """The live Scholar export must lose only the four known artifacts."""
    path = os.path.join(ROOT, "media", "publications_scholar.json")
    if not os.path.exists(path):
        pytest.skip("Scholar export not present")
    with open(path) as f:
        pubs = json.load(f)
    kept = up.filter_noise_publications(pubs)
    dropped = [p["title"] for p in pubs if p not in kept]
    # Every dropped entry must match a known-noise shape, not a real paper.
    for title in dropped:
        assert up.is_noise_publication(title)
    assert len(kept) == len(pubs) - len(dropped)
    assert len(kept) > 25, "Filter removed far too much — likely a bad pattern"


# ── Author emphasis ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Sebastian Ament", "Sebastian E Ament", "Sebastian E. Ament",
    "Sebastian Eduard Ament", "S Ament", "S. Ament", "SE Ament", "sebastian ament",
])
def test_self_author_variants(name):
    assert up.is_self_author(name) is True


@pytest.mark.parametrize("name", [
    "Carla Gomes", "Maximilian Balandat", "David Eriksson",
    "Ament", "", None, "John Ament",
])
def test_non_self_authors(name):
    assert up.is_self_author(name) is False


def test_format_authors_emphasises_only_self():
    out = up.format_authors(["Sebastian Ament", "Carla Gomes"])
    assert '<strong class="author-self">Sebastian Ament</strong>' in out
    assert "Carla Gomes" in out
    assert '<strong class="author-self">Carla Gomes' not in out


def test_format_authors_escapes_names():
    out = up.format_authors(['<img src=x onerror="alert(1)">'])
    assert "<img" not in out
    assert "&lt;img" in out


def test_format_authors_handles_empty():
    assert up.format_authors([]) == ""
    assert up.format_authors(None) == ""


# ── Equal contribution ──────────────────────────────────────────────────────

def test_equal_contribution_count():
    assert up.equal_contribution_count("Empirical Gaussian Processes") == 2
    assert up.equal_contribution_count("Robust Gaussian processes via relevance pursuit") == 0
    assert up.equal_contribution_count("") == 0
    assert up.equal_contribution_count(None) == 0


@pytest.mark.parametrize("names", [
    ["Jihao Andreas Lin", "Sebastian Ament", "Louis C Tiao", "David Eriksson"],
    ["J. Lin", "S. Ament", "Louis C. Tiao", "David Eriksson"],
])
def test_joint_first_authors_marked_regardless_of_spelling(names):
    """Sources spell the same people differently; position-keying must survive it."""
    out = up.format_authors(names, "Empirical Gaussian Processes")
    assert out.count('class="author-eq"') == 2
    assert "Eriksson<sup" not in out
    assert 'class="author-self"' in out


def test_no_markers_without_joint_authorship():
    out = up.format_authors(["Sebastian Ament", "Carla Gomes"], "Some Other Paper")
    assert "author-eq" not in out
    # Backwards compatible when no title is supplied.
    assert "author-eq" not in up.format_authors(["Sebastian Ament"])


def test_rendered_page_marks_the_joint_paper_once():
    with open(os.path.join(ROOT, "index.html")) as f:
        page = f.read()
    seo = page[page.index("<!-- PUBLICATIONS_SEO -->"):
               page.index("<!-- /PUBLICATIONS_SEO -->")]
    line = [l for l in seo.split("\n") if "Empirical Gaussian Processes" in l]
    assert line, "Joint-authored paper missing from the rendered list"
    assert line[0].count('class="author-eq"') == 2
    assert "equal contribution" in line[0]
    # No other publication should have picked up the marker.
    assert seo.count('class="pub-equal-note"') == 1


# ── Badges ──────────────────────────────────────────────────────────────────

def test_badge_lookup_is_title_normalised():
    t = "Unexpected improvements to expected improvement for bayesian optimization"
    assert up.badge_for(t) == "NeurIPS 2023 Spotlight"
    assert up.badge_for(t.upper()) == "NeurIPS 2023 Spotlight"


def test_unbadged_paper_has_no_badge():
    assert up.badge_for("Some other paper") == ""
    assert up.badge_for("") == ""
    assert up.badge_for(None) == ""


# ── URL safety ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "  ",
    "",
    None,
])
def test_unsafe_urls_render_as_no_link(bad):
    assert up._safe_url(bad) == ""


def test_safe_urls_pass_through_escaped():
    assert up._safe_url("https://arxiv.org/abs/2310.20708") == \
        "https://arxiv.org/abs/2310.20708"
    # Quotes must be escaped so an href cannot be broken out of.
    assert '"' not in up._safe_url('https://x.com/a"onmouseover="alert(1)')


# ── Rendered output ─────────────────────────────────────────────────────────

def test_committed_seo_block_is_clean_and_formatted():
    """The static list shipped in index.html must already reflect these rules."""
    with open(os.path.join(ROOT, "index.html")) as f:
        page = f.read()
    seo = page[page.index("<!-- PUBLICATIONS_SEO -->"):
               page.index("<!-- /PUBLICATIONS_SEO -->")]
    assert len(seo) > 500
    assert "author-self" in seo, "Owner's name should be emphasised"
    assert not re.search(r"<strong><a[^>]*>Data from:", seo, re.I)
    assert not re.search(r"Supplementary Materials</a>", seo, re.I)
    assert not re.search(r">[^<]*\.\s*(?:19|20)\d{2}\.\s", seo)
    # No raw javascript: hrefs may ever appear in committed markup.
    assert "javascript:" not in seo.lower()


# ── Duplicate collapsing ────────────────────────────────────────────────────

def test_parenthesised_year_normalises_to_same_key():
    """Scholar appends the year to one of two duplicate records."""
    a = "Unexpected improvements to expected improvement for bayesian optimization"
    assert up._normalize_title(f"{a} (2024)") == up._normalize_title(a)
    assert up._paper_key(f"{a} (2024)") == up._paper_key(a)


def test_bare_trailing_year_still_normalises():
    assert up._normalize_title("Some Paper, 2019") == up._normalize_title("Some Paper")


def test_year_inside_title_is_preserved():
    """Only a trailing parenthesised year is stripped."""
    assert "2024" in up._normalize_title("NeurIPS (2024) retrospective study")


def test_dedupe_keeps_best_cited_copy():
    items = [
        {"title": "A Paper", "citationCount": 10},
        {"title": "A Paper (2024)", "citationCount": 42},
        {"title": "Another Paper", "citationCount": 5},
    ]
    out = up._deduplicate_by_title(items)
    assert len(out) == 2
    best = [p for p in out if up._paper_key(p["title"]) == up._paper_key("A Paper")][0]
    assert best["citationCount"] == 42


def test_rendered_list_has_no_duplicate_titles_or_badges():
    """The committed static list must contain each paper, and each badge, once."""
    with open(os.path.join(ROOT, "index.html")) as f:
        page = f.read()
    seo = page[page.index("<!-- PUBLICATIONS_SEO -->"):
               page.index("<!-- /PUBLICATIONS_SEO -->")]
    keys = [up._paper_key(t) for t in re.findall(r"<strong>(?:<a[^>]*>)?([^<]+)", seo)]
    assert len(keys) == len(set(keys)), "Duplicate publication in the rendered list"
    assert seo.count('class="pub-badge"') == len(set(
        k for k in keys if up.PUBLICATION_BADGES.get(k))), "Badge rendered the wrong number of times"


# ── Cross-language consistency ──────────────────────────────────────────────
# The same rules run server-side (Python) and client-side (chart.js). If they
# drift, crawlers and visitors see different publication lists.

def _node(expr):
    out = subprocess.run(
        ["node", "-e", f"const c=require('./chart.js');process.stdout.write(String({expr}))"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return out.stdout


def test_equal_contribution_maps_match_between_python_and_js():
    js = json.loads(_node("JSON.stringify(c.EQUAL_CONTRIBUTION)"))
    assert js == up.EQUAL_CONTRIBUTION, (
        "chart.js EQUAL_CONTRIBUTION and update_publications.py EQUAL_CONTRIBUTION "
        "have drifted — the static and live lists would disagree"
    )


def test_badge_maps_match_between_python_and_js():
    js = json.loads(_node("JSON.stringify(c.PUBLICATION_BADGES)"))
    assert js == up.PUBLICATION_BADGES, (
        "chart.js PUBLICATION_BADGES and update_publications.py PUBLICATION_BADGES "
        "have drifted — the SEO list and the live list would show different badges"
    )


@pytest.mark.parametrize("title", [
    "Data from: something",
    "Paper: Supplementary Materials",
    "Authors A, B. 2019. Real Title Here",
    "Unexpected improvements to expected improvement for bayesian optimization",
    "CRYSTAL: a multi-agent AI system for automated mapping",
    "Robust Gaussian processes via relevance pursuit",
])
def test_noise_rules_match_between_python_and_js(title):
    js = _node(f"c.isNoisePublication({json.dumps(title)})").strip() == "true"
    assert js == up.is_noise_publication(title), (
        f"Python and JS disagree on whether this is noise: {title!r}"
    )


@pytest.mark.parametrize("title", [
    "A Paper (2024)", "A Paper, 2019", "A Paper",
    "Unexpected improvements to expected improvement for bayesian optimization (2024)",
    "NeurIPS (2024) retrospective study",
])
def test_paper_key_matches_between_python_and_js(title):
    """paperKey drives dedupe and badge lookup on both sides; it must agree."""
    js = _node(f"c.paperKey({json.dumps(title)})").strip()
    assert js == up._paper_key(title), f"paperKey drift on {title!r}"


@pytest.mark.parametrize("name", [
    "Sebastian Ament", "Sebastian E Ament", "S. Ament",
    "Sebastian Eduard Ament", "Carla Gomes", "John Ament",
])
def test_self_author_rules_match_between_python_and_js(name):
    js = _node(f"c.isSelfAuthor({json.dumps(name)})").strip() == "true"
    assert js == up.is_self_author(name), (
        f"Python and JS disagree on author identity: {name!r}"
    )
