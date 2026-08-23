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
const REQUIRED_CHART_API = [
    'paperKey', 'urlLabel', 'buildBarModel',
    'escapeHtml', 'formatAuthors', 'badgeFor', 'isNoisePublication',
    'dedupePublications', 'equalContributionCount',
];

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


// ─────────────────────────────────────────────────────────────────────────────
// Regression guards for the site-improvements batch.
// Each block below locks in a fix that is invisible in unit tests because it
// lives in markup, CSS, or the coupling between them.
// ─────────────────────────────────────────────────────────────────────────────

const stylesCss = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');

// ── No third-party requests before interaction ──────────────────────────────

assert.ok(!/fonts\.googleapis\.com|fonts\.gstatic\.com/.test(indexHtml),
    "Google Fonts must not be referenced — Montserrat is self-hosted so no visitor IP reaches a third party");
for (const f of ['media/fonts/montserrat-latin.woff2', 'media/fonts/montserrat-latin-ext.woff2']) {
    assert.ok(fs.existsSync(path.join(root, f)), `Self-hosted font missing: ${f}`);
    assert.ok(fs.statSync(path.join(root, f)).size > 1000, `${f} looks truncated`);
}
assert.ok(/@font-face/.test(stylesCss) && /montserrat-latin\.woff2/.test(stylesCss),
    "styles.css must declare @font-face for the self-hosted font");
assert.ok(/unicode-range/.test(stylesCss),
    "unicode-range keeps latin-ext from downloading unnecessarily");

// Videos: nothing may reach YouTube until the visitor presses play.
assert.ok(!/youtube\.com\/embed/.test(indexHtml),
    "Use youtube-nocookie.com for embeds, never youtube.com/embed");
assert.ok(/youtube-nocookie\.com\/embed/.test(indexHtml),
    "Video embeds should use the nocookie domain");
assert.ok(!/<iframe[^>]*\bdata-src=/.test(indexHtml),
    "No pre-placed iframes: every video must be a click-to-play facade");
assert.ok(!/videoObserver/.test(indexHtml),
    "The scroll-triggered video auto-loader must be gone — it loaded YouTube without consent");
assert.ok(!/i\.ytimg\.com|img\.youtube\.com/.test(indexHtml),
    "Do not use YouTube thumbnails — they are themselves a third-party request");
// Facades must be real buttons so they are keyboard-operable.
const facadeCount = (indexHtml.match(/class="video-poster"/g) || []).length;
assert.strictEqual(facadeCount, 3, `Expected 3 click-to-play videos, found ${facadeCount}`);
for (const m of indexHtml.match(/<[a-z]+[^>]*class="video-poster"/g) || []) {
    assert.ok(m.startsWith('<button'), `Video facade must be a <button>, got: ${m.slice(0, 60)}`);
}

// Every video shows a real thumbnail, and every thumbnail is hosted locally.
const posterImgs = [...indexHtml.matchAll(/class="video-poster"[\s\S]{0,400}?<img src="([^"]+)"/g)]
    .map(m => m[1]);
assert.strictEqual(posterImgs.length, 3, "Each video needs a poster image");
for (const src of posterImgs) {
    assert.ok(!/^https?:/.test(src), `Poster must be self-hosted, got: ${src}`);
    assert.ok(fs.existsSync(path.join(root, src)), `Missing poster image: ${src}`);
    assert.ok(fs.statSync(path.join(root, src)).size > 5000, `Poster looks empty: ${src}`);
}

// One press must start playback, including for videos that ignore autoplay=1
// (typically ones with a pre-roll). Two mechanisms, in order:
assert.ok(/autoplay=1/.test(indexHtml), "Videos must request autoplay on click");
assert.ok(/onReady/.test(indexHtml) && /playVideo\(\)/.test(indexHtml),
    "The player API must explicitly start playback when autoplay is ignored");
// The old failure mode: posting playVideo blindly on iframe load, before the
// player was listening, which left it paused and cost a second click.
assert.ok(!/func:\s*'playVideo'/.test(indexHtml),
    "No blind postMessage handshake — use the API's onReady instead");

// A single onReady->playVideo() call regressed to needing a second click when
// autoplay was silently blocked (ad insertion / extensions / policy
// heuristics) even after a genuine click. activateVideo must retry via
// onStateChange, gated by the shared shouldRetryVideoPlay() decision — not
// just fire once and hope.
const activateFn = indexHtml.match(/function activateVideo\(el\)[\s\S]*?\n        \}\n\n/);
assert.ok(activateFn, "activateVideo not found");
assert.ok(/onStateChange/.test(activateFn[0]),
    "activateVideo must listen for state changes, not just onReady, to catch playback that never actually started");
assert.ok(/shouldRetryVideoPlay\(/.test(activateFn[0]),
    "The retry must go through the shared, tested shouldRetryVideoPlay() decision — not ad-hoc logic here");
// Retries must be capped (both count and time are enforced inside
// shouldRetryVideoPlay, but the caller has to actually track and pass them).
assert.ok(/attempts/.test(activateFn[0]) && /Date\.now\(\)\s*-\s*startedAt/.test(activateFn[0]),
    "Caller must track attempt count and elapsed time and pass both to shouldRetryVideoPlay");
// The API script must only ever be fetched from inside the click path.
const apiIdx = indexHtml.indexOf('youtube.com/iframe_api');
assert.ok(apiIdx > -1, "iframe API should be referenced");
const loaderIdx = indexHtml.indexOf('function loadYouTubeApi');
assert.ok(loaderIdx > -1 && apiIdx > loaderIdx,
    "The API URL must live inside the lazy loader, not in a top-level tag");
assert.ok(!/<script[^>]+youtube\.com\/iframe_api/.test(indexHtml),
    "The YouTube API must never be a static <script> tag — that would fetch it on load");

// ── Theme preference persists across tabs and visits ────────────────────────

assert.ok(!/sessionStorage/.test(indexHtml),
    "Theme must use localStorage — sessionStorage resets the choice on every new tab");
assert.ok(/localStorage\.getItem\('theme'\)/.test(indexHtml), "Theme is read from localStorage");
assert.ok(/localStorage\.setItem\('theme'/.test(indexHtml), "Theme is written to localStorage");

// ── Page renders without (or before) JavaScript ─────────────────────────────

// .fade-in must NOT be unconditionally hidden; the hidden state is opt-in via
// .js-anim, so a blocked or broken script cannot leave the page blank forever.
const fadeBase = stylesCss.match(/(^|\n)\.fade-in\s*\{[^}]*\}/);
assert.ok(fadeBase, ".fade-in base rule not found");
assert.ok(!/opacity:\s*0/.test(fadeBase[0]),
    "Base .fade-in must not set opacity:0 — content has to survive a JS failure");
assert.ok(/\.js-anim\s+\.fade-in\s*\{[^}]*opacity:\s*0/.test(stylesCss),
    "The hidden start-state must be scoped to .js-anim");
assert.ok(/documentElement\.classList\.add\('js-anim'\)/.test(indexHtml),
    "js-anim must be set by script so the animation only runs when JS is alive");

// The reveal must not be chained to data loading.
assert.ok(/setupFadeIn/.test(indexHtml), "Fade-in setup should be its own function");
const finallyBlock = indexHtml.match(/\}\)\.finally\(\(\) => \{([\s\S]*?)\n        \}\);/);
assert.ok(finallyBlock, ".finally() block not found");
assert.ok(!/IntersectionObserver/.test(finallyBlock[1]),
    "The fade-in observer must NOT live inside the fetch chain's .finally() — that kept the whole page at opacity 0 until three JSON fetches settled");

// An IntersectionObserver only fires when something can actually intersect,
// which needs a laid-out, visible viewport. In a prerendered or background tab,
// an embedded/zero-size viewport, or a headless renderer, it may never fire —
// and every section would sit at opacity 0 forever. There must be a failsafe.
const fadeFn = indexHtml.match(/function setupFadeIn\(\)[\s\S]*?\n        \}\)\(\);/);
assert.ok(fadeFn, "setupFadeIn not found");
assert.ok(/'IntersectionObserver' in window/.test(fadeFn[0]),
    "Must handle browsers with no IntersectionObserver at all");
// Two distinct guards, asserted separately so removing either one fails:
// (a) an unconditional timer armed at load,
assert.ok(/setTimeout\(failsafe,\s*\d+\);/.test(
        fadeFn[0].replace(/document\.addEventListener\('visibilitychange'[\s\S]*$/, '')),
    "A load-time timeout failsafe must reveal content if the observer never fires");
// (b) a re-check when a hidden tab becomes visible and finally lays out.
const visBlock = fadeFn[0].match(/visibilitychange'[\s\S]*?\}\);/);
assert.ok(visBlock, "A hidden tab may only lay out when shown — re-check on visibilitychange");
assert.ok(/failsafe/.test(visBlock[0]), "visibilitychange handler must run the failsafe");
// The failsafe must only kick in when NOTHING was revealed, so normal
// scroll-triggered behaviour is preserved on a healthy page.
assert.ok(/!all\.some\(el => el\.classList\.contains\('visible'\)\)/.test(fadeFn[0]),
    "Failsafe must trigger only when no section was revealed at all");

// ── A failed fetch must not wipe the server-rendered publications ───────────

assert.ok(/if \(!publications\.length\)/.test(indexHtml),
    "updatePublications must bail out when no live data loaded, preserving the static list");
assert.ok(/id="pub-notice"/.test(indexHtml), "A non-destructive fallback notice must exist");
assert.ok(/id="pub-empty"/.test(indexHtml), "Zero-result filter state must exist");
// The guard has to run before the list is cleared.
const updIdx = indexHtml.indexOf('function updatePublications');
const guardIdx = indexHtml.indexOf('if (!publications.length)', updIdx);
const renderIdx = indexHtml.indexOf('renderPublications(sorted)', updIdx);
assert.ok(guardIdx > -1 && guardIdx < renderIdx,
    "The empty-data guard must precede renderPublications()");

// ── Print stylesheet ────────────────────────────────────────────────────────

const printBlock = stylesCss.match(/@media print\s*\{[\s\S]*?\n\}/);
assert.ok(printBlock, "A print stylesheet must exist — printing is the de-facto CV path");
assert.ok(/opacity:\s*1\s*!important/.test(printBlock[0]),
    "Print must force .fade-in visible, or unscrolled sections print blank");
assert.ok(/#gp-background/.test(printBlock[0]), "Print should drop the animated background");
assert.ok(/\.publication\s*\{[^}]*break-inside:\s*avoid/.test(printBlock[0]),
    "Short publication entries should stay whole");
// Long project blocks must be allowed to split. Combining break-after:avoid on
// h2 with break-inside:avoid on a tall .project strands up to half a page of
// whitespace under the section heading.
assert.ok(/\.project\s*\{[^}]*break-inside:\s*auto/.test(printBlock[0]),
    "Projects must be allowed to break across pages, or headings strand whitespace");
assert.ok(/orphans/.test(printBlock[0]) && /widows/.test(printBlock[0]),
    "orphans/widows should keep splits from stranding single lines");
// Flex containers resist page breaks in several engines (Safari in particular),
// stranding whitespace under a heading. They serve no purpose in print.
assert.ok(/\.project-body[\s\S]{0,120}display:\s*block/.test(printBlock[0]),
    "print must drop .project-body out of flex layout");
assert.ok(/\.about-content/.test(printBlock[0]),
    "print must drop .about-content out of flex layout");

// ── Publication presentation ────────────────────────────────────────────────

assert.ok(/formatAuthors\(pub\.authors/.test(indexHtml),
    "Author lists must go through formatAuthors so the site owner's name is emphasised");
assert.ok(/class="author-self"/.test(indexHtml),
    "The server-rendered list must contain emphasised own-name markup");
assert.ok(/class="pub-badge"/.test(indexHtml), "Award badges must render");
assert.ok(/\.author-self/.test(stylesCss) && /\.pub-badge/.test(stylesCss),
    "author-self and pub-badge need styling");
// Keep the own-name signal gentle: full opacity plus a medium weight, not bold.
// At 700 it competed visually with the publication title.
const selfRule = stylesCss.match(/\.author-self\s*\{[^}]*\}/)[0];
const selfWeight = Number((selfRule.match(/font-weight:\s*(\d+)/) || [])[1]);
assert.ok(selfWeight && selfWeight < 700,
    `Own-name emphasis must stay below bold, got font-weight ${selfWeight}`);
// The name must stay in the author list's type scale. `.publication strong`
// (title styling) would otherwise capture the nested own-name <strong> and
// render it at the title's 15px.
assert.ok(/font-size:\s*inherit/.test(selfRule),
    "author-self must inherit the author list's font-size, not the title's");
assert.ok(/\.publication\s*>\s*strong/.test(stylesCss),
    "The title rule must use a child combinator so it cannot style nested <strong>");
assert.ok(/isNoisePublication\(p\.title\)/.test(indexHtml),
    "The client-side list must filter Scholar noise too");
// Joint first authorship must be shown, and explained.
assert.ok(/formatAuthors\(pub\.authors,\s*pub\.title\)/.test(indexHtml),
    "formatAuthors needs the title to look up joint first authorship");
assert.ok(/class="author-eq"/.test(indexHtml), "Joint first authors must be marked");
assert.ok(/equal contribution/.test(indexHtml), "The asterisk must be explained");
assert.ok(/\.author-eq/.test(stylesCss) && /\.pub-equal-note/.test(stylesCss),
    "author-eq and pub-equal-note need styling");

// The committed static list must be clean.
const seo = indexHtml.slice(indexHtml.indexOf('<!-- PUBLICATIONS_SEO -->'),
                            indexHtml.indexOf('<!-- /PUBLICATIONS_SEO -->'));
assert.ok(seo.length > 500, "SEO block looks empty");
for (const [pattern, label] of [
    [/<strong><a[^>]*>Data from:/i, 'dataset stub'],
    [/Supplementary Materials<\/a>/i, 'supplementary-material entry'],
    [/>[^<]*\.\s*(?:19|20)\d{2}\.\s/, 'citation-string-as-title'],
]) {
    assert.ok(!pattern.test(seo), `Server-rendered list still contains a ${label}`);
}
assert.ok(/author-self/.test(seo), "Static list should emphasise the owner's name");

// ── 404 page ────────────────────────────────────────────────────────────────

const notFound = fs.readFileSync(path.join(root, '404.html'), 'utf8');
assert.ok(/<h1/.test(notFound), "404 needs an h1");
assert.ok(/noindex/.test(notFound), "404 must not be indexed");
assert.ok(/href="\/"/.test(notFound), "404 must link home");
// Assets must be root-absolute: a 404 can be served from any depth.
for (const m of notFound.match(/(?:href|src)="(?!https?:|#|mailto:)([^"]+)"/g) || []) {
    assert.ok(/="\//.test(m), `404 asset must use a root-absolute path: ${m}`);
}
assert.ok(/localStorage\.getItem\('theme'\)/.test(notFound),
    "404 should apply the same persisted theme");

// Every local asset the 404 references must actually exist.
for (const rel of [...notFound.matchAll(/(?:href|src)="\/([^"?#]+)(?:\?[^"]*)?"/g)].map(m => m[1])) {
    assert.ok(fs.existsSync(path.join(root, rel)), `404 references missing asset: ${rel}`);
}

console.log('All integration tests passed ✓');
