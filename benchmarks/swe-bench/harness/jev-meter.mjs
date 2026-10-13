import { appendFileSync } from 'node:fs';
const original = globalThis.fetch;
globalThis.fetch = async (...args) => {
  const started = performance.now();
  try {
    const response = await original(...args);
    let body;
    try { body = await response.clone().json(); } catch {}
    appendFileSync('/root/jev-usage.jsonl', JSON.stringify({status: response.status, seconds: (performance.now()-started)/1000, model: body?.model, usage: body?.usage ?? null})+'\n');
    return response;
  } catch (error) {
    appendFileSync('/root/jev-usage.jsonl', JSON.stringify({status: 'network_error', seconds: (performance.now()-started)/1000, usage:null})+'\n');
    throw error;
  }
};
