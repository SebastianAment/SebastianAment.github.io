/**
 * Tests for analytics.js.
 * Run with: node tests/test_analytics.js
 *
 * The contract these lock in:
 *   - disabled unless explicitly configured (site ships with zero tracking)
 *   - Do Not Track / Global Privacy Control are always honoured
 *   - no personal or free-text data is ever put in an event path
 *   - track() can never throw, whatever the page state
 */

const assert = require('assert');
const {
    ANALYTICS_CONFIG, analyticsOptedOut, analyticsEnabled,
    providerScript, providerEndpoint, eventPath, initAnalytics, track,
} = require('../analytics.js');

// ── Ships disabled ──────────────────────────────────────────────────────────
assert.strictEqual(ANALYTICS_CONFIG.site, '',
    "Analytics must ship disabled — an unset site keeps third-party requests at zero");
assert.strictEqual(analyticsEnabled({ site: '' }, {}), false);
assert.strictEqual(providerScript({ site: '' }), null);
assert.strictEqual(providerEndpoint({ site: '' }), null);

// ── Opt-out signals are honoured ────────────────────────────────────────────
assert.ok(analyticsOptedOut({ globalPrivacyControl: true }), "GPC opts out");
assert.ok(analyticsOptedOut({ doNotTrack: '1' }), "DNT '1' opts out");
assert.ok(analyticsOptedOut({ doNotTrack: 1 }), "DNT numeric opts out");
assert.ok(analyticsOptedOut({ doNotTrack: 'yes' }), "DNT 'yes' opts out");
assert.ok(!analyticsOptedOut({ doNotTrack: '0' }), "DNT '0' does not opt out");
assert.ok(!analyticsOptedOut({}), "No signal means no opt-out");

const CONFIGURED = { provider: 'goatcounter', site: 'example' };
assert.strictEqual(analyticsEnabled(CONFIGURED, {}), true,
    "Configured + no opt-out signal = enabled");
assert.strictEqual(analyticsEnabled(CONFIGURED, { globalPrivacyControl: true }), false,
    "GPC must override configuration");
assert.strictEqual(analyticsEnabled(CONFIGURED, { doNotTrack: '1' }), false,
    "DNT must override configuration");

// ── Provider wiring ─────────────────────────────────────────────────────────
assert.strictEqual(providerScript(CONFIGURED), 'https://gc.zgo.at/count.js');
assert.strictEqual(providerEndpoint(CONFIGURED), 'https://example.goatcounter.com/count');
assert.strictEqual(providerScript({ provider: 'unknown', site: 'x' }), null,
    "Unknown providers must fail closed, not guess a URL");

// ── Event paths carry no free text ──────────────────────────────────────────
assert.strictEqual(eventPath('theme_toggle', 'dark'), 'theme-toggle/dark');
assert.strictEqual(eventPath('pub_search'), 'pub-search');
assert.strictEqual(eventPath('outbound', 'arxiv.org'), 'outbound/arxiv-org');
// Anything unexpected is flattened to a slug — no spaces, quotes, or slashes
// can leak a query string or a paper title into the analytics path.
const dirty = eventPath('evt', 'Bayesian Optimization: "sample-efficient" /x?y=1');
assert.ok(/^evt\/[a-z0-9-]*$/.test(dirty), `Label must be slugified, got "${dirty}"`);
assert.ok(dirty.length <= 4 + 40, "Label is length-capped");
assert.strictEqual(eventPath(''), 'event', "Falls back to a generic name");
assert.strictEqual(eventPath('a', ''), 'a', "Empty label is omitted, not left dangling");

// ── Never throws, never acts when disabled ──────────────────────────────────
assert.strictEqual(track('anything'), false, "Disabled track() is a silent no-op");
assert.strictEqual(track(null, null), false);
assert.strictEqual(track(undefined), false);
assert.doesNotThrow(() => track('x', 'y'), "track() must never throw");

// initAnalytics is inert without a document and without configuration.
assert.strictEqual(initAnalytics(null, CONFIGURED), false, "No document = no-op");
assert.strictEqual(initAnalytics({}, { site: '' }), false, "Unconfigured = no-op");

// ── initAnalytics injects exactly one correctly-wired script ────────────────
function fakeDoc() {
    const head = { children: [], appendChild(el) { this.children.push(el); } };
    return {
        head,
        _byId: {},
        getElementById(id) { return this._byId[id] || null; },
        createElement() {
            const el = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
            return el;
        },
    };
}
const doc = fakeDoc();
assert.strictEqual(initAnalytics(doc, CONFIGURED), true);
assert.strictEqual(doc.head.children.length, 1, "Injects one script");
const injected = doc.head.children[0];
assert.strictEqual(injected.src, 'https://gc.zgo.at/count.js');
assert.strictEqual(injected.async, true, "Script must not block rendering");
assert.strictEqual(injected.attrs['data-goatcounter'], 'https://example.goatcounter.com/count');

// Idempotent: a second call with the script already present does nothing.
doc._byId['analytics-script'] = injected;
assert.strictEqual(initAnalytics(doc, CONFIGURED), false, "Must not double-inject");
assert.strictEqual(doc.head.children.length, 1);

// Opted-out visitors get no script at all, even when configured.
const doc2 = fakeDoc();
const origNav = global.navigator;
global.navigator = { globalPrivacyControl: true };
assert.strictEqual(initAnalytics(doc2, CONFIGURED), false, "GPC visitor gets no script");
assert.strictEqual(doc2.head.children.length, 0);
if (origNav === undefined) delete global.navigator; else global.navigator = origNav;

console.log('All analytics tests passed ✓');
