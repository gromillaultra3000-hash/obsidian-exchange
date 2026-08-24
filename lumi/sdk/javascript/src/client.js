const { LumiClientError } = require('./errors');

class LumiClient {
  constructor({ baseUrl = 'http://127.0.0.1:8000', timeout = 30000 } = {}) { this.baseUrl = baseUrl.replace(/\/$/, ''); this.timeout = timeout; }
  async _request(method, path, data = null) {
    const options = { method, headers: { 'Content-Type': 'application/json' } };
    if (data !== null && method !== 'GET') options.body = JSON.stringify(data);
    let controller;
    if (typeof AbortController !== 'undefined') { controller = new AbortController(); options.signal = controller.signal; setTimeout(() => controller.abort(), this.timeout); }
    try {
      const response = await fetch(`${this.baseUrl}${path}`, options);
      const payload = await response.json();
      if (!response.ok) throw new LumiClientError((payload.detail && payload.detail.message) || JSON.stringify(payload), response.status, payload);
      return payload;
    } catch (error) { if (error instanceof LumiClientError) throw error; throw new LumiClientError(`Request error: ${error.message}`); }
  }
  health(){ return this._request('GET','/health'); }
  version(){ return this._request('GET','/version'); }
  runtimeStatus(){ return this._request('GET','/runtime/status'); }
  getIntegrationContract(){ return this._request('GET','/integration/contract'); }
  handshake(manifest){ return this._request('POST','/integration/handshake',{ hostAppId: manifest.hostAppId, manifest, connectorMode: (manifest.allowedModes || ['rest'])[0], clientVersion: '0.7.0' }); }
  registerProvider(providerProfile){ return this._request('POST','/providers', providerProfile); }
  registerAction(actionDefinition){ return this._request('POST','/actions/register', actionDefinition); }
  resolve(payload){ return this._request('POST','/resolve',{ input: payload.input || '', context: payload.context || {}, requirements: payload.requirements || {}, metadata: payload.metadata || {} }); }
  createDialogSession(payload = {}){ return this._request('POST','/dialog/sessions', payload); }
  sendDialogMessage(sessionId, text, metadata = {}){ return this._request('POST',`/dialog/sessions/${encodeURIComponent(sessionId)}/message`,{ text, metadata }); }
  listDecisions(){ return this._request('GET','/history/decisions'); }
  explainDecision(decisionId, mode = 'human'){ return this._request('GET',`/explain/${encodeURIComponent(decisionId)}?mode=${encodeURIComponent(mode)}`); }
  proposeAction(payload){ return this._request('POST','/actions/propose', payload); }
  listApprovals(){ return this._request('GET','/actions/approvals'); }
  approve(promptId, payload = {}){ return this._request('POST',`/actions/approvals/${encodeURIComponent(promptId)}/decision`,{ promptId, decision: 'approve', ...payload }); }
  reject(promptId, payload = {}){ return this._request('POST',`/actions/approvals/${encodeURIComponent(promptId)}/decision`,{ promptId, decision: 'reject', ...payload }); }
  sendHostEvent(event){ return this._request('POST','/integration/events', event); }
}
module.exports = { LumiClient };
