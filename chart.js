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
 * Scale a per-year citation histogram so its values sum exactly to `total`,
 * using largest-remainder (Hamilton) rounding.
 *
 * The per-year breakdown is an incomplete view of the authoritative total:
 * citing works whose publication year is unknown are absent from the
 * histogram, so its sum is a lower bound on the real citation count. To
 * reconcile the two — so the cumulative chart ends at the reported total and
 * the projection sits above it — the dated years are scaled up in proportion,
 * which is the least-biased placement of the undated citations (they are
 * assumed to follow the same yearly distribution as the dated ones).
 *
 * Returns a new object. If `total` is falsy or not greater than the current
 * sum (nothing to reconcile), returns an unscaled copy.
 *
 * @param {Object} byYear - { "2023": 50, "2024": 100 }
 * @param {number} total  - authoritative citation count to scale up to
 * @returns {Object} scaled histogram summing exactly to `total`
 */
function reconcileToTotal(byYear, total) {
    const years = Object.keys(byYear);
    const sum = years.reduce((s, y) => s + byYear[y], 0);
    const copy = {};
    years.forEach(y => { copy[y] = byYear[y]; });
    if (!total || total <= sum || sum <= 0) return copy;

    const result = {};
    const remainders = [];
    let allocated = 0;
    years.forEach(y => {
        const exact = byYear[y] * total / sum;
        const floor = Math.floor(exact);
        result[y] = floor;
        allocated += floor;
        remainders.push({ y, frac: exact - floor });
    });
    // Hand the remaining units to the years with the largest fractional parts
    // so the scaled histogram sums to exactly `total`.
    remainders.sort((a, b) => b.frac - a.frac);
    let leftover = total - allocated;
    for (let i = 0; i < remainders.length && leftover > 0; i++, leftover--) {
        result[remainders[i].y] += 1;
    }
    return result;
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

/**
 * Build the display model for a citation bar chart. This is the single source
 * of truth for the chart math — reconciliation to the authoritative total,
 * per-year vs. cumulative, year-end projection, and pixel heights — kept here
 * (rather than in the DOM renderer) so it is unit-testable without a browser.
 *
 * @param {Object} byYear - raw per-year histogram, e.g. { "2024": 100, "2025": 60 }
 * @param {Object} opts
 * @param {number} [opts.barHeight=90] - pixel height of the tallest bar
 * @param {boolean} [opts.cumulative=false] - render cumulative running totals
 * @param {boolean} [opts.showProjection] - include a year-end projection bar
 * @param {string}  [opts.fetchedAt] - ISO date used by the projection
 * @param {number}  [opts.total] - authoritative total to scale the bars up to
 * @returns {{bars: Array, maxVal: number, barHeight: number}}
 *   Each bar: { year, count, proj|null, isStack, barPx, actualPx|null }.
 *   `bars` is empty only when `byYear` has no entries.
 */
function buildBarModel(byYear, opts = {}) {
    opts = opts || {};
    const barHeight = opts.barHeight || 90;
    const cumulative = !!opts.cumulative;

    // Scale the dated histogram up to the authoritative total (no-op when
    // opts.total is absent or not greater than the current sum).
    const reconciled = reconcileToTotal(byYear || {}, opts.total || 0);
    const years = Object.keys(reconciled).sort();
    if (years.length === 0) return { bars: [], maxVal: 0, barHeight };

    // Projection is computed on the reconciled per-year data so it stays
    // consistent with the bars actually displayed.
    let projResult = null;
    if (opts.showProjection && opts.fetchedAt) {
        projResult = computeProjection(reconciled, opts.fetchedAt);
    }

    // Per-year or cumulative display values, carrying the projection forward
    // (in cumulative mode the projected year-end becomes the running total).
    let displayByYear = reconciled;
    const projected = {};
    if (cumulative) {
        displayByYear = {};
        let running = 0;
        years.forEach(y => { running += reconciled[y]; displayByYear[y] = running; });
        if (projResult) {
            const extra = projResult.projected - reconciled[projResult.year];
            projected[projResult.year] = displayByYear[projResult.year] + extra;
        }
    } else if (projResult) {
        projected[projResult.year] = projResult.projected;
    }

    let maxVal = Math.max(...years.map(y => displayByYear[y]));
    if (projResult) maxVal = Math.max(maxVal, projected[projResult.year]);

    const bars = years.map(year => {
        const count = displayByYear[year];
        const proj = projected[year];
        if (proj && proj > count) {
            const actualPx = maxVal > 0 ? Math.max(2, (count / maxVal) * barHeight) : 2;
            const projPx = maxVal > 0 ? (proj / maxVal) * barHeight : 2;
            return { year, count, proj, isStack: true, barPx: projPx, actualPx };
        }
        const px = maxVal > 0 ? Math.max(2, (count / maxVal) * barHeight) : 2;
        return { year, count, proj: null, isStack: false, barPx: px, actualPx: null };
    });

    return { bars, maxVal, barHeight };
}

// Export for Node.js testing; no-op in browser
if (typeof module !== 'undefined') {
    module.exports = { paperKey, computeProjection, urlLabel, reconcileToTotal, buildBarModel };
}
