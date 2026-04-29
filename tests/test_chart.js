/**
 * Tests for chart.js — covers paperKey generation and projection logic.
 * Run with: node tests/test_chart.js
 */

const assert = require('assert');
const { paperKey, computeProjection } = require('../chart.js');

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
