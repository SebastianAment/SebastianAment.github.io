/**
 * Integration/contract tests for the index.html ⇄ chart.js coupling.
 * Run with: node tests/test_integration.js
 *
 * Background: chart.js and index.html are separate files. index.html's inline
 * script calls functions that live in chart.js (as browser globals). If a
 * function index.html relies on is missing from chart.js — a rename, a dropped
 * export, or a stale cached copy against newer markup — the whole citation
 * section throws and renders nothing (no bars, no toggles). These tests make
 * that failure mode impossible to ship unnoticed:
 *   1. Every chart.js function index.html depends on is actually exported.
 *   2. The sub-resources are cache-busted so browsers can't run a stale copy.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const indexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const chartExports = require('../chart.js');

// The chart.js API that index.html's inline script actually invokes. Keep this
// list in sync with real usage — the reference check below fails if it drifts.
const REQUIRED_CHART_API = ['paperKey', 'urlLabel', 'buildBarModel'];

// Strip HTML comments so a mention in a comment doesn't count as a real call.
const scriptSrc = indexHtml.replace(/<!--[\s\S]*?-->/g, '');

for (const fn of REQUIRED_CHART_API) {
    // (a) chart.js must export it (so it exists as a global in the browser and
    //     is importable for tests). This is what would have caught the
    //     "reconcileToTotal is not defined" class of regression at the code level.
    assert.ok(
        typeof chartExports[fn] === 'function',
        `chart.js must export "${fn}" — index.html calls it and will throw otherwise`
    );
    // (b) index.html must genuinely call it, so this contract list stays honest.
    assert.ok(
        new RegExp(`\\b${fn}\\s*\\(`).test(scriptSrc),
        `index.html is expected to call "${fn}(" — update REQUIRED_CHART_API if usage changed`
    );
}

// Sub-resources must be cache-busted with a ?v= query, so a content change is
// never masked by a browser's cached copy running against newer markup.
for (const asset of ['chart.js', 'styles.css']) {
    const escaped = asset.replace('.', '\\.');
    assert.ok(
        new RegExp(`${escaped}\\?v=`).test(indexHtml),
        `index.html must reference ${asset} with a ?v= cache-busting query`
    );
}

console.log('All integration tests passed ✓');
