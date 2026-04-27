/**
 * VoyageAI API Client
 * All HTTP calls live here. Routes, error handling, headers — one place.
 * Change API_BASE to point at a different backend.
 */

export const API_BASE = window.VOYAGE_API || 'http://localhost:5000/api';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function post(path, body = {}) {
  const r = await fetch(`${API_BASE}${path}`, {
    method:  'POST',
    headers: JSON_HEADERS,
    body:    JSON.stringify(body),
  });
  return r.json();
}

async function get(path) {
  const r = await fetch(`${API_BASE}${path}`);
  return r.json();
}

// ── Session ───────────────────────────────────────────────────

export const createSession = () => post('/session');

export const getSession    = (sid) => get(`/session/${sid}`);

export const confirmElement = (sid, element, data, action = 'confirm') =>
  post('/confirm', { session_id: sid, element, data, action });

// ── Chat ──────────────────────────────────────────────────────

export const sendChat = (message, sessionId, customerContext = null, originIata = null) =>
  post('/chat', { message, session_id: sessionId, customer_context: customerContext, origin_iata: originIata });

export const sendDemo = (message, sessionId) =>
  post('/demo', { message, session_id: sessionId });

// ── Customer ─────────────────────────────────────────────────

export const listCustomers = () => get('/customers');

export const getCustomer   = (lookup) => get(`/customer/${lookup}`);

// ── Loyalty ──────────────────────────────────────────────────

export const getLoyalty = (customerId, tripCostGbp, nights, flights) =>
  post(`/loyalty/${customerId}`, {
    trip_cost_gbp: tripCostGbp,
    nights,
    flights,
  });

// ── Ancillaries ───────────────────────────────────────────────

export const getAncillaries = (context) => post('/ancillaries', context);

// ── Waterfall / Health ────────────────────────────────────────

export const getWaterfallStatus = () => get('/waterfall');

export const getHealth          = () => get('/health');

// ── MCP direct ───────────────────────────────────────────────

export const callMcp = (serverName, params) =>
  post(`/mcp/${serverName}`, params);

// ── Auth ──────────────────────────────────────────────────────

export const login = (email, memberId) =>
  post('/auth/login', { email, member_id: memberId });

export const logout = (token, sessionId) =>
  post('/auth/logout', { token, session_id: sessionId });

export const getMe = (token) =>
  fetch(`${API_BASE}/auth/me`, { headers: { 'X-Auth-Token': token } })
    .then(r => r.json());

export const getDemoCredentials = () => get('/auth/demo-credentials');
