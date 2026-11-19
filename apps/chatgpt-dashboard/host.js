/* Host adapter: MCP Apps postMessage and the ChatGPT window.openai bridge. */
'use strict';
window.FitnessHost = (() => {
  let serial = 0;
  let mode = null;
  let listener = () => {};
  const pending = new Map();
  const legacy = () => typeof window.openai?.callTool === 'function';
  function notify(method, params) {
    if (mode === 'mcp') window.parent.postMessage({jsonrpc: '2.0', method, params}, '*');
  }
  function rpc(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++serial;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error('Host request timed out'));
      }, 60000);
      pending.set(id, {resolve, reject, timer});
      window.parent.postMessage({jsonrpc: '2.0', id, method, params}, '*');
    });
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== '2.0') return;
    if (pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(request.timer);
      if (message.error) request.reject(new Error('Host request failed'));
      else request.resolve(message.result);
    } else if (message.method === 'ui/notifications/tool-result') listener(message.params);
    else if (message.method === 'ui/notifications/tool-cancelled') listener({isError: true});
  });
  window.addEventListener('openai:set_globals', event => {
    const output = event.detail?.globals?.toolOutput;
    if (output) listener({structuredContent: output});
  });
  return {
    onResult(callback) { listener = callback; },
    async connect() {
      if (legacy()) {
        mode = 'openai';
        if (window.openai.toolOutput) listener({structuredContent: window.openai.toolOutput});
        return;
      }
      await rpc('ui/initialize', {
        appInfo: {name: 'fitness-hq', version: '0.2.0'},
        appCapabilities: {availableDisplayModes: ['inline', 'fullscreen']},
        protocolVersion: '2026-01-26'
      });
      mode = 'mcp';
      notify('ui/notifications/initialized', {});
    },
    call(name, args) {
      if (mode === 'openai') return window.openai.callTool(name, args);
      if (mode !== 'mcp') return Promise.reject(new Error('Host is not connected'));
      return rpc('tools/call', {name, arguments: args});
    },
    notify
  };
})();
