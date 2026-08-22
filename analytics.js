/**
 * Privacy-preserving, cookieless analytics.
 *
 * Answers two questions: how much traffic the site gets, and which features
 * people actually use (source/mode toggles, per-paper charts, BibTeX copies,
 * video plays, outbound paper links).
 *
 * Design constraints, in priority order:
 *   1. No cookies, no cross-site identifiers, no personal data. Nothing here
 *      requires a consent banner under GDPR/ePrivacy.
 *   2. Honours Do Not Track and Global Privacy Control — if a visitor has opted
 *      out, no request is made at all.
 *   3. Disabled by default. Until CONFIG.site is filled in, every entry point is
 *      an inert no-op, so the site ships with zero third-party requests.
 *   4. Never throws. Analytics must not be able to break the page.
 *
 * To enable: create a free site at https://www.goatcounter.com (cookieless,
 * open-source, EU-hosted) and set CONFIG.site to your code — for
 * `sebastianament.goatcounter.com`, that is 'sebastianament'.
 *
 * To switch providers, change CONFIG.provider and add a branch in
 * providerScript()/sendEvent(). The call sites (track(...)) stay unchanged.
 */

const ANALYTICS_CONFIG = {
    provider: 'goatcounter',
    site: '',           // '' = analytics disabled (default)
    trackOutbound: true,
};

/** True when the visitor has signalled they do not want to be tracked. */
function analyticsOptedOut(nav) {
    const n = nav || (typeof navigator !== 'undefined' ? navigator : {});
    if (n.globalPrivacyControl === true) return true;
    const dnt = n.doNotTrack || (typeof window !== 'undefined' && window.doNotTrack);
    return dnt === '1' || dnt === 1 || dnt === 'yes';
}

/** Analytics runs only when configured AND the visitor has not opted out. */
function analyticsEnabled(cfg, nav) {
    const c = cfg || ANALYTICS_CONFIG;
    if (!c.site) return false;
    return !analyticsOptedOut(nav);
}

/** URL of the provider's script tag, or null when disabled/unknown. */
function providerScript(cfg) {
    const c = cfg || ANALYTICS_CONFIG;
    if (!analyticsEnabled(c)) return null;
    if (c.provider === 'goatcounter') return 'https://gc.zgo.at/count.js';
    return null;
}

/** The endpoint the provider reports to (used for the data-goatcounter attr). */
function providerEndpoint(cfg) {
    const c = cfg || ANALYTICS_CONFIG;
    if (!analyticsEnabled(c)) return null;
    if (c.provider === 'goatcounter') return `https://${c.site}.goatcounter.com/count`;
    return null;
}

/**
 * Normalise an event into a stable, low-cardinality path.
 * Free-text detail (paper titles, search terms) is deliberately NOT sent —
 * only the event name and an optional short, sanitised label.
 */
function eventPath(name, label) {
    const clean = v => String(v || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 40);
    const n = clean(name) || 'event';
    const l = clean(label);
    return l ? `${n}/${l}` : n;
}

/** Inject the provider script. Idempotent; safe to call before DOM ready. */
function initAnalytics(doc, cfg) {
    const d = doc || (typeof document !== 'undefined' ? document : null);
    const c = cfg || ANALYTICS_CONFIG;
    if (!d || !analyticsEnabled(c)) return false;
    if (d.getElementById('analytics-script')) return false;
    const src = providerScript(c);
    const endpoint = providerEndpoint(c);
    if (!src || !endpoint) return false;
    const el = d.createElement('script');
    el.id = 'analytics-script';
    el.async = true;
    el.src = src;
    el.setAttribute('data-goatcounter', endpoint);
    (d.head || d.body || d.documentElement).appendChild(el);
    return true;
}

/**
 * Record a feature interaction. No-op when analytics is disabled or the
 * provider has not loaded. Never throws.
 */
function track(name, label) {
    try {
        if (!analyticsEnabled()) return false;
        const gc = typeof window !== 'undefined' && window.goatcounter;
        if (!gc || typeof gc.count !== 'function') return false;
        gc.count({ path: eventPath(name, label), title: name, event: true });
        return true;
    } catch (_) {
        return false;   // analytics must never break the page
    }
}

// Export for Node.js testing; no-op in browser
if (typeof module !== 'undefined') {
    module.exports = {
        ANALYTICS_CONFIG, analyticsOptedOut, analyticsEnabled,
        providerScript, providerEndpoint, eventPath, initAnalytics, track,
    };
}
