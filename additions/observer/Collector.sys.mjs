export class Collector {
  constructor(maxRequestsPerKey = 500) {
    this._rows = new Map();        // "site|userContextId" → row
    this._subs = new Set();
    this._cap = maxRequestsPerKey;
  }
  _key(site, u) { return `${site}|${u}`; }
  _row(site, u) {
    const k = this._key(site, u);
    let r = this._rows.get(k);
    if (!r) { r = { key: { site, userContextId: u }, surfaces: {}, requests: [] }; this._rows.set(k, r); }
    return r;
  }
  ingestAccess(u, site, surface, ts) {
    const r = this._row(site, u);
    r.surfaces[surface] = (r.surfaces[surface] || 0) + 1;
    r.lastTs = ts; this._emit();
  }
  ingestNet(u, site, host, url, method, ts) {
    const r = this._row(site, u);
    r.requests.push({ host, url, method, ts });
    if (r.requests.length > this._cap) r.requests.shift();  // bounded, memory-only
    r.lastTs = ts; this._emit();
  }
  snapshot() { return [...this._rows.values()]; }
  subscribe(fn) { this._subs.add(fn); return () => this._subs.delete(fn); }
  clear() { this._rows.clear(); this._emit(); }
  _emit() { for (const fn of this._subs) { try { fn(); } catch {} } }
}
