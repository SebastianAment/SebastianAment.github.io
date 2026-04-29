/**
 * Shared logic for citation chart rendering.
 * Extracted for testability — used by both index.html and tests.
 */

/**
 * Generate a paper key matching Python's _paper_key().
 * Must stay in sync with update_publications.py.
 */
function paperKey(title) {
    return title.trim().toLowerCase()
        .replace(/[,\s]+\d{4}\s*$/, '')  // trailing year
        .replace(/[^a-z0-9\s]/g, '')      // punctuation
        .replace(/\s+/g, '_')              // spaces to underscores
        .slice(0, 60);
}

/**
 * Compute year-end projection using blended rate.
 * Returns null if projection criteria not met.
 *
 * @param {Object} byYear - { "2023": 50, "2024": 100, "2025": 40 }
 * @param {string} fetchedAt - ISO date string of when data was fetched
 * @returns {Object|null} - { year, projected } or null
 */
function computeProjection(byYear, fetchedAt) {
    if (!fetchedAt) return null;
    const asOf = new Date(fetchedAt);
    const cy = String(asOf.getFullYear());
    const prevYear = String(asOf.getFullYear() - 1);
    const actual = byYear[cy];
    const prior = byYear[prevYear];

    if (actual === undefined || prior === undefined) return null;

    const day = Math.floor((asOf - new Date(asOf.getFullYear(), 0, 0)) / 86400000);
    const days = (asOf.getFullYear() % 4 === 0) ? 366 : 365;
    if (day <= 0) return null;

    const rateCurrent = actual / day;
    const ratePrior = prior / 365;
    const weight = Math.min(day / 90, 1);
    const blendedRate = weight * rateCurrent + (1 - weight) * ratePrior;
    const projected = Math.max(actual, Math.round(blendedRate * days));

    // Only project if annualized rate >= 12 citations/year
    if (blendedRate * 365 < 12) return null;

    return { year: cy, projected };
}

/**
 * Determine appropriate link label based on URL domain.
 */
function urlLabel(url) {
    if (!url) return '';
    if (url.includes('semanticscholar.org')) return 'Semantic Scholar';
    if (url.includes('arxiv.org')) return 'arXiv';
    if (url.includes('neurips.cc') || url.includes('nips.cc')) return 'NeurIPS';
    if (url.includes('proceedings.mlr.press')) return 'PMLR';
    if (url.includes('openreview.net')) return 'OpenReview';
    if (url.includes('ieeexplore.ieee.org')) return 'IEEE';
    if (url.includes('nature.com/articles/s41524')) return 'npj Comp. Mat.';
    if (url.includes('nature.com/articles/s42256')) return 'Nat. Mach. Intell.';
    if (url.includes('nature.com')) return 'Nature';
    if (url.includes('science.org/doi') && url.includes('sciadv')) return 'Sci. Advances';
    if (url.includes('science.org')) return 'Science';
    if (url.includes('sciencedirect.com')) return 'ScienceDirect';
    if (url.includes('springer.com')) return 'Springer';
    if (url.includes('iopscience.iop.org')) return 'IOP Science';
    if (url.includes('pubs.acs.org')) return 'ACS';
    if (url.includes('cambridge.org')) return 'Cambridge';
    return 'Paper';
}

// Export for Node.js testing; no-op in browser
if (typeof module !== 'undefined') {
    module.exports = { paperKey, computeProjection, urlLabel };
}
