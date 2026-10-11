'use strict';
/** V14 runtime regression: the same payment-flow script must never bind twice. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');

const html = read('dist/builder.html');
const media = read('dist/assets/media-fix.js');
const editor = read('dist/assets/workspace-upgrades.js');
const base = read('dist/assets/builder.js');
const payment = read('dist/assets/payment-flow-v2.js');
const readiness = read('dist/assets/readiness-v3.js');
const agent = read('dist/assets/agent-console-v1.js');
const preview = read('dist/assets/preview-email-ui.js');

assert.equal((html.match(/<script[^>]+src="assets\/payment-flow-v2\.js/g) || []).length, 1,
  'Builder must reference exactly one payment flow');
assert.ok(!media.includes('loadPostbuildPaymentFlow()'), 'Media fallback must not inject another controller');
assert.ok(!media.includes("payment-flow-v2.js?v=20260914-1"));
assert.ok(!editor.includes('updatePipeline(p.status)'), 'Legacy editor must not repaint new pipeline');
assert.ok(!editor.includes('activeProjectId=id; updatePipeline'));
assert.ok(base.includes('if (window.PV_PAYMENT_FLOW_V2_LOADED) return;'),
  'Legacy builder must not trigger the obsolete checkout-before-build path');
assert.ok(!payment.includes("const projects = await request('/projects');"),
  'Never select an unrelated unfinished project from server list');
assert.ok(payment.includes('++watcherVersion'), 'New Project must invalidate stale watchers');
assert.ok(payment.includes("currentUrl.searchParams.delete(key)"));
assert.ok(payment.includes('if (myVersion !== watcherVersion || activeProjectId !== id) return;'));
assert.ok(readiness.includes('Pripravljenost briefa'));
assert.ok(readiness.includes('Ne pomeni, da je bila stran izdelana ali objavljena.'));
assert.ok(html.includes('Potek izdelave izbranega projekta'));
assert.ok(agent.includes('lastLoadedSignature'));
assert.ok(agent.includes('Date.now() - lastLoadedAt > 120000'));
assert.ok(!agent.includes('setTimeout(load,80)'), 'Health polling must not trigger preflight repeatedly');
assert.ok(preview.includes('if (activeProjectId && activeProjectId !== id) return;'));
assert.ok(html.includes('assets/agent-console-v1.js?v=20261011-v14'));
assert.ok(html.includes('assets/payment-flow-v2.js?v=20261011-v14'));

const calls = [];
const mk = id => ({
  id,
  textContent: 'Začni izdelavo',
  disabled: false,
  dataset: {},
  style: {},
  setAttribute() {},
  addEventListener(type, listener, capture) {
    calls.push({ id, type, listener, capture });
  }
});
const controls = {generate: mk('generate'), newBuild: mk('newBuild')};
const globals = {
  window: {},
  document: {getElementById: id => controls[id] || null},
  location: {search: '', href: 'http://127.0.0.1:8000/builder.html'},
  URLSearchParams, URL, Set,
  setTimeout() {}, console
};
globals.window.window = globals.window;
const ctx = vm.createContext(globals);
vm.runInContext(payment, ctx, {filename:'payment-flow-v2.js'});
vm.runInContext(payment, ctx, {filename:'payment-flow-v2.js'});
assert.equal(globals.window.PV_PAYMENT_FLOW_V2_LOADED, true);
assert.equal(calls.filter(x => x.id === 'generate' && x.type === 'click').length, 1,
  'Duplicate inclusion must not register a second generate listener');
assert.equal(calls.filter(x => x.id === 'newBuild' && x.type === 'click').length, 1,
  'Duplicate inclusion must not register a second watcher cancellation listener');
console.log('V14 UI SINGLE CONTROLLER: PASS');
