/* GoreeCloud Analytics — cookie-free browser tracker.
 * Use data-site-id on the script tag. Opt-out stores only a privacy preference
 * in first-party localStorage, never a visitor identity or tracking cookie.
 */
(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || !script.dataset.siteId) return;
  const siteId = script.dataset.siteId;
  const endpoint = new URL('/api/v1/collect', script.src).toString();
  const preferenceKey = 'goreecloud-analytics-opt-out';
  let optedOut = false;
  try { optedOut = localStorage.getItem(preferenceKey) === '1'; }
  catch (_) { /* Private browsing may disallow storage. */ }
  const hasGlobalPrivacySignal = () =>
    navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true;
  const isOptedOut = () => optedOut || hasGlobalPrivacySignal();
  // Minimize values BEFORE transmission: server-side redaction is defense-in-depth,
  // not permission to send arbitrary query strings or detailed referrer URLs.
  const decodedForPrivacy = (value) => {
    for (let count = 0; count < 6; count++) {
      try {
        const next = decodeURIComponent(value);
        if (next === value) break;
        value = next;
      } catch (_) { break; }
    }
    return value;
  };
  const sensitive = (value) => {
    const decoded = decodedForPrivacy(value);
    return decoded.length > 32 || /@|[0-9]{5,}|(?:bearer|secret|token|apikey|accesskey|password)[_=-]|(?:[0-9]{1,3}\.){3}[0-9]{1,3}|[0-9]{3}[-. ]?[0-9]{3}[-. ]?[0-9]{4}/i.test(decoded);
  };
  const minimizedPageUrl = () => {
    let url;
    try { url = new URL(location.href); } catch (_) { return null; }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    // A pathname can contain an email address, order ID, access token, etc.
    const path = url.pathname.split('/').map(part => sensitive(part) ? ':redacted' : part);
    url.pathname = path.join('/');
    const campaign = new URLSearchParams();
    for (const name of ['utm_source', 'utm_medium', 'utm_campaign']) {
      const value = url.searchParams.get(name);
      if (value && /^[A-Za-z0-9_.~-]{1,100}$/.test(value) && !sensitive(value)) {
        campaign.set(name, value);
      }
    }
    url.search = campaign.toString();
    url.hash = '';
    return url.toString();
  };
  const minimizedReferrer = () => {
    try {
      const referrer = new URL(document.referrer);
      return ['http:', 'https:'].includes(referrer.protocol) ? referrer.origin : '';
    } catch (_) { return ''; }
  };
  const event = (type, name = '', properties = {}) => {
    if (isOptedOut()) return;
    const url = minimizedPageUrl();
    if (!url) return;
    const data = JSON.stringify({site_id: siteId, type, name, properties,
      url, referrer: minimizedReferrer()});
    if (navigator.sendBeacon) {
      navigator.sendBeacon(endpoint, new Blob([data], {type: 'text/plain'}));
    } else {
      fetch(endpoint, {method:'POST', body:data, mode:'cors', keepalive:true,
        headers:{'Content-Type':'text/plain'}}).catch(() => {});
    }
  };
  // The host site can expose opt-out/opt-in buttons with this API. Opt-in never
  // overrides DNT or Global Privacy Control supplied by the browser.
  window.goreecloudAnalytics = Object.freeze({
    track: (name, properties = {}) => event('event', name, properties),
    isOptedOut,
    optOut: () => { optedOut = true;
      try { localStorage.setItem(preferenceKey, '1'); } catch (_) { /* memory-only */ }
    },
    optIn: () => { optedOut = false;
      try { localStorage.removeItem(preferenceKey); } catch (_) { /* memory-only */ }
    },
  });
  let previousPage = '';
  const page = () => {
    const url = minimizedPageUrl();
    if (!url || url === previousPage) return;
    previousPage = url;
    event('pageview');
  };
  page();
  // Navigation instrumentation for SPA clients. Deduplicate unchanged URLs.
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      queueMicrotask(page);
      return result;
    };
  }
  addEventListener('popstate', page);
  document.addEventListener('click', (e) => {
    const target = e.target.closest?.('[data-gc-event]');
    if (target) event('event', target.getAttribute('data-gc-event') || 'click');
  });
})();
