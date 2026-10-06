// Camoufox Proxy Toggle
//
// The button does not touch the browser's proxy settings, and cannot: when
// Playwright configures Firefox's proxy it does so below the WebExtension
// layer, so both browser.proxy.settings and browser.proxy.onRequest were
// measured to have no effect on where the traffic actually goes.
//
// Instead camoufox-pm points the browser at a loopback relay it owns
// (core/local_proxy.py), and that relay decides per connection whether to
// forward to the real upstream proxy or to connect directly. This button
// just asks the manager to flip that relay, which takes effect for the next
// request with no restart.
//
// config.json is written by the launcher on every launch:
//   { profile_id, manager_url, proxy_paused }

let paused = false;
let busy = false;
let config = null;

function updateIcon() {
  browser.browserAction.setTitle({
    title: busy
      ? 'Switching...'
      : paused
        ? 'Proxy: PAUSED - traffic goes direct (click to resume)'
        : 'Proxy: active (click to pause)',
  });
  browser.browserAction.setBadgeText({ text: paused ? 'OFF' : '' });
  try {
    browser.browserAction.setBadgeBackgroundColor({ color: '#ff8c00' });
  } catch (_) {}
  try {
    browser.browserAction.setBadgeTextColor({ color: '#111111' });
  } catch (_) {}
}

function managerUrl(path) {
  const base = (config && config.manager_url) || 'http://127.0.0.1:8000';
  return `${base.replace(/\/+$/, '')}${path}`;
}

async function toggle() {
  if (busy) return;
  if (!config || !config.profile_id) {
    console.error('camoufox-pm proxy-toggle: no profile_id in config.json');
    return;
  }
  busy = true;
  updateIcon();
  try {
    const r = await fetch(
      managerUrl(`/api/v1/profiles/${config.profile_id}/proxy/toggle`),
      { method: 'POST' },
    );
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const body = await r.json();
    // The manager is the source of truth: it just flipped the relay and
    // wrote the flag, so take its answer rather than assuming ours.
    paused = Boolean(body.proxy_paused);
  } catch (e) {
    console.error('camoufox-pm proxy-toggle: toggle failed:', e);
  } finally {
    busy = false;
    updateIcon();
  }
}

browser.browserAction.onClicked.addListener(toggle);

async function start() {
  try {
    const resp = await fetch(browser.runtime.getURL('config.json'));
    config = await resp.json();
    paused = Boolean(config.proxy_paused);
  } catch (e) {
    console.warn('camoufox-pm proxy-toggle: no config.json', e);
    config = {};
  }
  updateIcon();
}

start();
