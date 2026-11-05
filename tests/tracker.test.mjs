import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../analytics/static/tracker.js', import.meta.url), 'utf8');

function instantiate({doNotTrack = '0', gpc = false, optedOut = false} = {}) {
  const calls = [];
  const preferences = new Map(optedOut ? [['goreecloud-analytics-opt-out', '1']] : []);
  const location = {href: 'https://www.example.com/home'};
  const navigator = {doNotTrack, globalPrivacyControl: gpc,
    sendBeacon: (endpoint, data) => { calls.push({endpoint, data}); return true; }};
  const history = {pushState() {}, replaceState() {}};
  const context = {
    document: {currentScript: {dataset: {siteId: 'site-test'},
        src: 'https://analytics.example.net/assets/tracker.js'},
      referrer: '', addEventListener() {}},
    location, history, navigator,
    localStorage: {getItem: (key) => preferences.get(key) || null,
      setItem: (key, val) => preferences.set(key, val),
      removeItem: (key) => preferences.delete(key)},
    window: {}, URL, Blob, queueMicrotask,
    addEventListener() {},
  };
  vm.runInNewContext(source, context);
  return {calls, preferences, context};
}

test('anonymous tracking and manual privacy opt-out', () => {
  const {calls, preferences, context} = instantiate();
  assert.equal(calls.length, 1);
  context.window.goreecloudAnalytics.track('signup');
  assert.equal(calls.length, 2);
  context.window.goreecloudAnalytics.optOut();
  assert.equal(preferences.get('goreecloud-analytics-opt-out'), '1');
  assert.equal(context.window.goreecloudAnalytics.isOptedOut(), true);
  context.window.goreecloudAnalytics.track('signup');
  assert.equal(calls.length, 2);
  context.window.goreecloudAnalytics.optIn();
  context.window.goreecloudAnalytics.track('signup');
  assert.equal(calls.length, 3);
});

test('existing preference or browser privacy signal prevents collection', () => {
  for (const setting of [{optedOut:true}, {doNotTrack:'1'}, {gpc:true}]) {
    const {calls, context} = instantiate(setting);
    assert.equal(calls.length, 0);
    context.window.goreecloudAnalytics.track('click');
    assert.equal(calls.length, 0);
    context.window.goreecloudAnalytics.optIn();
    context.window.goreecloudAnalytics.track('click');
    assert.equal(calls.length, setting.optedOut ? 1 : 0);
  }
});

test('same-URL SPA transitions do not inflate pageviews', async () => {
  const {calls, context} = instantiate();
  assert.equal(calls.length, 1);
  context.history.replaceState({}, '', '/home');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 1);
  context.location.href = 'https://www.example.com/about';
  context.history.pushState({}, '', '/about');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 2);
});
