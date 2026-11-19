const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../apps/chatgpt-dashboard/host.js'), 'utf8');
function host(openai) {
  const listeners = {}, messages = [], timers = new Map();
  let serial = 0;
  const window = {openai, parent: {postMessage: message => messages.push(message)},
    addEventListener: (name, callback) => listeners[name] = callback};
  vm.runInNewContext(source, {window, setTimeout: fn => {timers.set(++serial, fn); return serial;}, clearTimeout: id => timers.delete(id)});
  return {api: window.FitnessHost, messages, timers,
    deliver: (data, valid=true) => listeners.message({source: valid ? window.parent : {}, data}),
    globals: toolOutput => listeners['openai:set_globals']({detail: {globals: {toolOutput}}})};
}
test('ChatGPT initial and asynchronously delivered tool results both render', async () => {
  const calls = [], output = {dashboard: {date: '2020-01-01'}};
  const h = host({toolOutput: output, callTool: async (...args) => {calls.push(args); return {structuredContent: output};}});
  const seen = []; h.api.onResult(result => seen.push(result));
  await h.api.connect();
  h.globals(output);
  assert.equal(seen.length, 2);
  assert.deepEqual(seen[0].structuredContent, output);
  assert.equal((await h.api.call('get_fitness_hq_dashboard', {})).structuredContent, output);
  assert.equal(calls.length, 1);
  assert.equal(h.messages.length, 0);
});
test('MCP initializes before calls and accepts responses only from its parent', async () => {
  const h = host(); const connecting = h.api.connect();
  assert.equal(h.messages[0].method, 'ui/initialize');
  h.deliver({jsonrpc: '2.0', id: 1, result: {}});
  await connecting;
  assert.equal(h.messages[1].method, 'ui/notifications/initialized');
  const call = h.api.call('get_fitness_hq_dashboard', {});
  h.deliver({jsonrpc: '2.0', id: 2, result: 'spoofed'}, false);
  assert.equal(h.timers.size, 1);
  h.deliver({jsonrpc: '2.0', id: 2, result: 'correct'});
  assert.equal(await call, 'correct'); assert.equal(h.timers.size, 0);
});
test('timeout and host errors reject without leaking pending calls', async () => {
  const h = host(); const connecting = h.api.connect();
  const failure = assert.rejects(connecting, /timed out/);
  [...h.timers.values()][0](); await failure;
  const retry = h.api.connect();
  const rejected = assert.rejects(retry, /Host request failed/);
  h.deliver({jsonrpc: '2.0', id: 2, error: {code: -1}}); await rejected;
});
test('cancellation and tool result notifications are delivered', async () => {
  const h = host(), seen = []; h.api.onResult(value => seen.push(value));
  h.deliver({jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: {structuredContent: {dashboard: {}}}});
  h.deliver({jsonrpc: '2.0', method: 'ui/notifications/tool-cancelled'});
  assert.equal(seen.length, 2); assert.equal(seen[1].isError, true);
});
