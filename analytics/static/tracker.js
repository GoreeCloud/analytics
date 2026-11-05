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
  const event = (type, name = '', properties = {}) => {
    if (isOptedOut()) return;
    const data = JSON.stringify({site_id: siteId, type, name, properties,
      url: location.href, referrer: document.referrer});
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
    if (location.href === previousPage) return;
    previousPage = location.href;
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
