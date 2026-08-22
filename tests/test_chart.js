/**
 * Tests for chart.js — covers paperKey generation and projection logic.
 * Run with: node tests/test_chart.js
 */

const assert = require('assert');
const {
    paperKey, computeProjection, reconcileToTotal, buildBarModel,
    escapeHtml, isSelfAuthor, formatAuthors, badgeFor, isNoisePublication,
    dedupePublications, equalContributionCount,
} = require('../chart.js');

// ── paperKey tests ──────────────────────────────────────────────────────────

assert.strictEqual(paperKey("Hello World"), "hello_world");

assert.strictEqual(
    paperKey("A".repeat(100)).length, 60,
    "Should truncate to 60 chars"
);

// Trailing year stripped
assert.strictEqual(
    paperKey("Unexpected improvements to expected improvement for bayesian optimization, 2025"),
    paperKey("Unexpected improvements to expected improvement for bayesian optimization"),
    "Trailing year should be stripped"
);

// Case insensitive
assert.strictEqual(
    paperKey("CRYSTAL: a multi-agent AI system"),
    paperKey("crystal: a multi-agent ai system"),
);

// Must match Python's output exactly
assert.strictEqual(
    paperKey("Unexpected improvements to expected improvement for bayesian optimization"),
    "unexpected_improvements_to_expected_improvement_for_bayesian"
);

assert.strictEqual(
    paperKey("CRYSTAL: a multi-agent AI system for automated mapping of materials' crystal structures"),
    "crystal_a_multiagent_ai_system_for_automated_mapping_of_mate"
);

assert.strictEqual(
    paperKey("Accurate and efficient numerical calculation of stable densities via optimized quadrature and asymptotics"),
    "accurate_and_efficient_numerical_calculation_of_stable_densi"
);

// ── computeProjection tests ─────────────────────────────────────────────────

// Basic projection: mid-year with prior data
const result = computeProjection(
    { "2024": 100, "2025": 60 },
    "2025-06-30T00:00:00Z"  // day 181 of 365
);
assert.ok(result !== null, "Should produce a projection");
assert.strictEqual(result.year, "2025");
assert.ok(result.projected >= 60, "Projection must be >= actual");
assert.ok(result.projected > 100, "With 60 citations by mid-year, should project > last year's 100");

// No prior year → no projection
assert.strictEqual(
    computeProjection({ "2025": 50 }, "2025-06-15T00:00:00Z"),
    null,
    "Should return null without prior year"
);

// No current year data → no projection
assert.strictEqual(
    computeProjection({ "2024": 100 }, "2025-06-15T00:00:00Z"),
    null,
    "Should return null without current year data"
);

// Below rate threshold (< 12/year) → no projection
assert.strictEqual(
    computeProjection({ "2024": 2, "2025": 1 }, "2025-06-15T00:00:00Z"),
    null,
    "Should return null for low-rate papers"
);

// Early in year: prior dominates the blend
const earlyResult = computeProjection(
    { "2024": 120, "2025": 5 },
    "2025-01-15T00:00:00Z"  // day 15, weight = 15/90 ≈ 0.17
);
assert.ok(earlyResult !== null);
// With prior=120 and only 5 in 15 days, blend should be closer to prior rate
assert.ok(
    earlyResult.projected > 50 && earlyResult.projected < 200,
    `Early year projection should be moderate, got ${earlyResult.projected}`
);

// Clamp: projected >= actual even if rate is declining
const clampResult = computeProjection(
    { "2024": 200, "2025": 150 },
    "2025-11-01T00:00:00Z"  // day 305, weight = 1.0
);
assert.ok(clampResult !== null);
assert.ok(
    clampResult.projected >= 150,
    "Projection must never be below actual"
);

// No fetchedAt → no projection
assert.strictEqual(computeProjection({ "2024": 50, "2025": 20 }, null), null);
assert.strictEqual(computeProjection({ "2024": 50, "2025": 20 }, ""), null);

// ── reconcileToTotal tests ──────────────────────────────────────────────────

const sumVals = obj => Object.values(obj).reduce((s, v) => s + v, 0);

// Scales up to exactly the reported total
const rec = reconcileToTotal({ "2024": 100, "2025": 60 }, 200);
assert.strictEqual(sumVals(rec), 200, "Scaled histogram must sum to the total");
assert.ok(rec["2024"] >= 100 && rec["2025"] >= 60, "Every year scales up, none down");

// Real S2-like case: dated sum 637, reported total 782
const s2agg = { "2017": 2, "2018": 4, "2019": 8, "2020": 28, "2021": 49,
                "2022": 66, "2023": 83, "2024": 81, "2025": 156, "2026": 160 };
const s2rec = reconcileToTotal(s2agg, 782);
assert.strictEqual(sumVals(s2rec), 782, "S2 aggregate must reconcile to 782 exactly");
// Proportional bias: recent (larger) years absorb more of the residual
assert.ok(s2rec["2026"] - 160 >= s2rec["2017"] - 2, "Larger years absorb more residual");

// All integers
assert.ok(Object.values(s2rec).every(v => Number.isInteger(v)), "All bars must be integers");

// No total, or total not exceeding the sum → unchanged copy (never scales down)
assert.deepStrictEqual(reconcileToTotal({ "2024": 50, "2025": 20 }, 0), { "2024": 50, "2025": 20 });
assert.deepStrictEqual(reconcileToTotal({ "2024": 50, "2025": 20 }, 40), { "2024": 50, "2025": 20 });
assert.deepStrictEqual(reconcileToTotal({ "2024": 50, "2025": 20 }, 70), { "2024": 50, "2025": 20 });

// Returns a new object (no mutation of the input)
const orig = { "2024": 10 };
const out = reconcileToTotal(orig, 20);
assert.strictEqual(orig["2024"], 10, "Input must not be mutated");
assert.strictEqual(out["2024"], 20);

// Monotonic input stays monotonic after scaling (cumulative safety)
const mono = reconcileToTotal({ "2023": 10, "2024": 20, "2025": 30 }, 90);
assert.ok(mono["2023"] <= mono["2024"] && mono["2024"] <= mono["2025"], "Order preserved");

// ── buildBarModel tests ─────────────────────────────────────────────────────
// This is the exact pipeline the chart renderer runs. These tests guard against
// the "no bars render" regression: if the model ever comes back empty for real
// data — or a helper it depends on (reconcileToTotal / computeProjection) goes
// missing or throws — these fail instead of the page silently blanking.

// Non-empty input must always produce one bar per year
const perYear = buildBarModel({ "2023": 10, "2024": 20 }, {});
assert.strictEqual(perYear.bars.length, 2, "One bar per year");
assert.deepStrictEqual(perYear.bars.map(b => b.count), [10, 20], "Per-year counts are raw");
assert.strictEqual(perYear.maxVal, 20);
assert.ok(perYear.bars.every(b => b.barPx >= 2 && Number.isFinite(b.barPx)), "Finite, visible heights");
assert.ok(perYear.bars.every(b => !b.isStack), "No projection → no stacked bars");

// Empty input is the ONLY case that yields no bars
assert.deepStrictEqual(buildBarModel({}, {}).bars, [], "Empty histogram → no bars");
assert.deepStrictEqual(buildBarModel(undefined, {}).bars, [], "Missing histogram → no bars, no throw");

// Cumulative mode: running totals, monotonic, last = sum
const cum = buildBarModel({ "2023": 10, "2024": 20, "2025": 30 }, { cumulative: true });
assert.deepStrictEqual(cum.bars.map(b => b.count), [10, 30, 60], "Cumulative running totals");

// Reconciliation: per-year bars scale up to the reported total exactly
const recModel = buildBarModel({ "2024": 100, "2025": 60 }, { total: 200 });
assert.strictEqual(recModel.bars.reduce((s, b) => s + b.count, 0), 200, "Bars sum to the total");

// Cumulative + reconciliation: last cumulative bar equals the total
const cumRec = buildBarModel({ "2024": 100, "2025": 60 }, { cumulative: true, total: 200 });
assert.strictEqual(cumRec.bars[cumRec.bars.length - 1].count, 200, "Cumulative ends at total");

// Projection: the current year becomes a stacked bar with proj > actual
const proj = buildBarModel(
    { "2024": 100, "2025": 60 },
    { showProjection: true, fetchedAt: "2025-06-30T00:00:00Z" }
);
const lastBar = proj.bars[proj.bars.length - 1];
assert.strictEqual(lastBar.isStack, true, "Projected year is a stacked bar");
assert.ok(lastBar.proj > lastBar.count, "Projection exceeds actual");
assert.strictEqual(proj.bars[0].isStack, false, "Non-current years are not stacked");
assert.ok(proj.maxVal >= lastBar.proj, "maxVal accounts for the projection");

// ── escapeHtml tests ────────────────────────────────────────────────────────
// Publication metadata is third-party data interpolated into innerHTML.

assert.strictEqual(escapeHtml('<script>alert(1)</script>'),
    '&lt;script&gt;alert(1)&lt;/script&gt;', "Tags must be neutralised");
assert.strictEqual(escapeHtml('Tom & Jerry'), 'Tom &amp; Jerry');
assert.strictEqual(escapeHtml('a"b\'c'), 'a&quot;b&#39;c', "Both quote styles escaped");
assert.strictEqual(escapeHtml(null), '', "null renders as empty, not 'null'");
assert.strictEqual(escapeHtml(undefined), '');
// Ampersand must be escaped first or escapes get double-encoded.
assert.strictEqual(escapeHtml('&lt;'), '&amp;lt;');

// ── isSelfAuthor / formatAuthors tests ──────────────────────────────────────
// Sources spell the same person several ways; all must be recognised.

for (const n of ['Sebastian Ament', 'Sebastian E Ament', 'Sebastian E. Ament',
                 'Sebastian Eduard Ament', 'S Ament', 'S. Ament', 'SE Ament',
                 'sebastian ament']) {
    assert.ok(isSelfAuthor(n), `Should recognise "${n}" as the site owner`);
}
for (const n of ['Carla Gomes', 'Maximilian Balandat', 'David Eriksson',
                 'Ament', '', null, undefined, 'John Ament']) {
    assert.ok(!isSelfAuthor(n), `Should NOT match "${n}"`);
}

const fa = formatAuthors(['Sebastian Ament', 'Carla Gomes']);
assert.ok(fa.includes('<strong class="author-self">Sebastian Ament</strong>'),
    "Own name is emphasised");
assert.ok(fa.includes('Carla Gomes') && !fa.includes('<strong class="author-self">Carla Gomes'),
    "Co-authors are not emphasised");
assert.strictEqual(formatAuthors([]), '');
assert.strictEqual(formatAuthors(null), '', "Missing author list must not throw");
// Co-author names are escaped, and injected markup cannot survive.
assert.ok(formatAuthors(['<img onerror=x>']).includes('&lt;img'),
    "Author names must be escaped");

// ── Equal-contribution tests ────────────────────────────────────────────────
// Joint first authorship is not exposed by Scholar or Semantic Scholar, so it
// is curated. Keyed by position, because the two sources spell names
// differently — that spelling-independence is the property worth locking in.

assert.strictEqual(equalContributionCount('Empirical Gaussian Processes'), 2);
assert.strictEqual(equalContributionCount('Robust Gaussian processes via relevance pursuit'), 0);
assert.strictEqual(equalContributionCount(''), 0);
assert.strictEqual(equalContributionCount(null), 0);

const EQ_TITLE = 'Empirical Gaussian Processes';
// Scholar spelling and Semantic Scholar spelling must both mark two authors.
for (const names of [
    ['Jihao Andreas Lin', 'Sebastian Ament', 'Louis C Tiao', 'David Eriksson'],
    ['J. Lin', 'S. Ament', 'Louis C. Tiao', 'David Eriksson'],
]) {
    const out = formatAuthors(names, EQ_TITLE);
    assert.strictEqual((out.match(/class="author-eq"/g) || []).length, 2,
        `Exactly the two joint first authors are marked, got: ${out}`);
    // The marker sits on the first two names, not on later co-authors.
    assert.ok(out.indexOf('author-eq') < out.indexOf('Tiao'),
        "Markers must precede the non-first authors");
    assert.ok(!/Eriksson<sup/.test(out), "Later authors carry no marker");
    // Own name stays emphasised as well as marked.
    assert.ok(/class="author-self"/.test(out), "Own name still emphasised");
}

// Papers without joint first authorship get no markers at all.
assert.ok(!/author-eq/.test(formatAuthors(['Sebastian Ament', 'Carla Gomes'], 'Some Other Paper')));
// And formatAuthors stays backwards compatible when no title is passed.
assert.ok(!/author-eq/.test(formatAuthors(['Sebastian Ament', 'Carla Gomes'])));

// ── badgeFor tests ──────────────────────────────────────────────────────────

assert.strictEqual(
    badgeFor('Unexpected improvements to expected improvement for bayesian optimization'),
    'NeurIPS 2023 Spotlight');
// Badge lookup is title-normalised, so casing/punctuation variants still hit.
assert.strictEqual(
    badgeFor('UNEXPECTED IMPROVEMENTS TO EXPECTED IMPROVEMENT FOR BAYESIAN OPTIMIZATION'),
    'NeurIPS 2023 Spotlight');
assert.strictEqual(badgeFor('Some other paper'), '', "Unbadged papers get no badge");
assert.strictEqual(badgeFor(''), '');
assert.strictEqual(badgeFor(null), '');

// ── isNoisePublication tests ────────────────────────────────────────────────
// Guards the exact Scholar artifacts that were diluting the list.

const NOISE = [
    'Data from: Autonomous synthesis of metastable materials',
    'Data from: Probabilistic Phase Labeling and Lattice Refinement',
    'data from: lowercase variant',
    'Sparse Bayesian Learning via Stepwise Regression: Supplementary Materials',
    'Shufeng Kong, Santosh K. Suram, R. Bruce van Dover, and John M. Gregoire. 2019. CRYSTAL: A multi-agent AI system',
    '', null, undefined,
];
for (const t of NOISE) assert.ok(isNoisePublication(t), `Should drop: "${t}"`);

const KEEP = [
    'Unexpected improvements to expected improvement for bayesian optimization',
    'Autonomous materials synthesis via hierarchical active learning of nonequilibrium phase diagrams',
    'CRYSTAL: a multi-agent AI system for automated mapping of materials\' crystal structures',
    'Advances in Sparse and Bayesian Optimization for Autonomous Scientific Discovery',
    'Robust Gaussian processes via relevance pursuit',
    'Efficient projection algorithms onto the weighted \u21131 ball',
];
for (const t of KEEP) assert.ok(!isNoisePublication(t), `Should KEEP: "${t}"`);

// ── Duplicate collapsing tests ──────────────────────────────────────────────
// Scholar lists the same paper twice, sometimes with the year appended to one
// copy. Both spellings must normalise to a single key, or the list shows the
// paper twice and any award badge renders twice with it.

assert.strictEqual(
    paperKey('Unexpected improvements to expected improvement for bayesian optimization (2024)'),
    paperKey('Unexpected improvements to expected improvement for bayesian optimization'),
    "A parenthesised trailing year must not create a second key");
assert.strictEqual(paperKey('Some Paper (2019)'), paperKey('Some Paper'));
assert.strictEqual(paperKey('Some Paper, 2019'), paperKey('Some Paper'),
    "Bare trailing year still normalises (existing behaviour)");
// A year that is part of the actual title must survive.
assert.ok(paperKey('NeurIPS (2024) retrospective study').includes('2024'),
    "Only a TRAILING parenthesised year is stripped");

const dupes = [
    { title: 'A Paper', citationCount: 10 },
    { title: 'A Paper (2024)', citationCount: 42 },
    { title: 'Another Paper', citationCount: 5 },
];
const deduped = dedupePublications(dupes);
assert.strictEqual(deduped.length, 2, "Duplicate titles collapse to one entry");
assert.strictEqual(deduped.find(p => paperKey(p.title) === paperKey('A Paper')).citationCount, 42,
    "The better-cited copy wins");
assert.deepStrictEqual(dedupePublications([]), []);
assert.deepStrictEqual(dedupePublications(null), [], "Must not throw on missing input");

// Exactly one badge may survive dedupe for the badged paper.
const badgeDupes = dedupePublications([
    { title: 'Unexpected improvements to expected improvement for bayesian optimization', citationCount: 300 },
    { title: 'Unexpected improvements to expected improvement for bayesian optimization (2024)', citationCount: 10 },
]);
assert.strictEqual(badgeDupes.filter(p => badgeFor(p.title)).length, 1,
    "A badged paper must not render its badge twice");

// ── urlLabel tests ──────────────────────────────────────────────────────────

const { urlLabel } = require('../chart.js');

assert.strictEqual(urlLabel('https://www.semanticscholar.org/paper/abc123'), 'Semantic Scholar');
assert.strictEqual(urlLabel('https://arxiv.org/abs/2310.20708'), 'arXiv');
assert.strictEqual(urlLabel('https://proceedings.neurips.cc/paper/2023/hash/abc-Conference.html'), 'NeurIPS');
assert.strictEqual(urlLabel('https://proceedings.mlr.press/v162/ament22a.html'), 'PMLR');
assert.strictEqual(urlLabel('https://www.science.org/doi/abs/10.1126/sciadv.abg4930'), 'Sci. Advances');
assert.strictEqual(urlLabel('https://www.nature.com/articles/s42256-021-00384-1'), 'Nat. Mach. Intell.');
assert.strictEqual(urlLabel('https://www.nature.com/articles/s41524-019-0213-0'), 'npj Comp. Mat.');
assert.strictEqual(urlLabel('https://ieeexplore.ieee.org/abstract/document/9747510/'), 'IEEE');
assert.strictEqual(urlLabel('https://link.springer.com/article/10.1007/s11222-017-9725-y'), 'Springer');
assert.strictEqual(urlLabel('https://openreview.net/forum?id=U1f6wHtG1g'), 'OpenReview');
assert.strictEqual(urlLabel('https://some-unknown-site.com/paper'), 'Paper');
assert.strictEqual(urlLabel(''), '');
assert.strictEqual(urlLabel(null), '');

console.log("All JS tests passed ✓");
