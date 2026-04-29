/**
 * Origin Airport Selector
 *
 * Flow:
 *   1. App load → call /api/locate (IP geolocation)
 *   2a. Success → show detected airport pill in header ("✈ London Heathrow (LHR)")
 *   2b. Fail    → show "📍 Set your departure airport" prompt
 *   3. User can click the pill to change it at any time
 *   4. Typing triggers autocomplete from /api/locate/airports
 *   5. Confirmed origin is stored in sessionStorage + sent with every chat request
 */

import { API_BASE } from '../api.js';

let _origin = null; // { iata, city, country, display, source }

// ── Public API ────────────────────────────────────────────────

/** Current origin IATA code (e.g. "LHR"), or null. */
export function getOriginIata()    { return _origin?.iata || null; }
export function getOriginDisplay() { return _origin?.display || 'Unknown origin'; }

/** Set origin programmatically (e.g. after login). */
export function setOrigin(iata, display, source = 'manual') {
  _origin = { iata: iata.toUpperCase(), display, source };
  sessionStorage.setItem('voyage_origin', JSON.stringify(_origin));
  _renderPill();
}

/**
 * Detect origin from IP, or load from sessionStorage if already set.
 * Renders the origin pill in the header.
 * Call once on app init.
 */
export async function initOrigin() {
  // Restore from sessionStorage first (survives page refresh)
  const saved = sessionStorage.getItem('voyage_origin');
  if (saved) {
    try {
      _origin = JSON.parse(saved);
      _renderPill();
      return;
    } catch { /* fall through */ }
  }

  // Auto-detect from IP
  _renderPill('detecting');
  try {
    const r = await fetch(`${API_BASE}/locate`);
    const d = await r.json();
    if (d.detected && d.iata) {
      if (d.iata && d.city && d.iata !== 'undefined' && d.city !== 'undefined') {
        _origin = {
          iata:    d.iata,
          city:    d.city,
          country: d.country || '',
          display: `${d.city} (${d.iata})`,
          source:  'ip_detected',
        };
        sessionStorage.setItem('voyage_origin', JSON.stringify(_origin));
        _renderPill('detected');
        window.dispatchEvent(new CustomEvent('originChanged', {
          detail: { iata: d.iata, display: _origin.display }
        }));
        return;
      }
    }
  } catch { /* network error */ }

  // Could not detect — ask user
  _origin = null;
  _renderPill('ask');
}

// ── Pill rendering ────────────────────────────────────────────

function _renderPill(state = 'set') {
  const container = document.getElementById('originPill');
  if (!container) return;

  if (state === 'detecting') {
    container.innerHTML = `
      <div class="origin-pill detecting" title="Detecting your location…">
        <span class="op-icon">📡</span>
        <span class="op-text">Detecting…</span>
      </div>`;
    return;
  }

  if (state === 'ask' || !_origin?.iata) {
    container.innerHTML = `
      <div class="origin-pill ask" onclick="window._openOriginModal()" title="Set your departure airport">
        <span class="op-icon">📍</span>
        <span class="op-text">Set departure airport</span>
      </div>`;
    return;
  }

  const srcIcon = _origin.source === 'ip_detected' ? '📡'
                : _origin.source === 'manual'       ? '✏️' : '✈️';
  const srcTip  = _origin.source === 'ip_detected'
                ? 'Auto-detected from your IP address'
                : 'Set manually';

  container.innerHTML = `
    <div class="origin-pill set" onclick="window._openOriginModal()" title="${srcTip} — click to change">
      <span class="op-icon">${srcIcon}</span>
      <span class="op-iata">${_origin.iata}</span>
      <span class="op-text">${_origin.display}</span>
      <span class="op-change">✎</span>
    </div>`;
}

// ── Modal ─────────────────────────────────────────────────────

window._openOriginModal = function () {
  // Remove any existing modal
  document.getElementById('originModal')?.remove();

  const modal = document.createElement('div');
  modal.id = 'originModal';
  modal.innerHTML = `
    <div class="om-backdrop" onclick="_closeOriginModal()"></div>
    <div class="om-card">
      <div class="om-header">
        <div class="om-title">✈ Departure Airport</div>
        <button class="om-close" onclick="_closeOriginModal()">✕</button>
      </div>
      <div class="om-body">
        <div class="om-current">
          ${_origin?.iata
            ? `Current: <strong>${_origin.display}</strong>`
            : 'Where are you flying from?'}
        </div>
        <input id="originInput" class="om-input" type="text"
          placeholder="Type a city, airport or IATA code…"
          value="${_origin?.city || ''}"
          autocomplete="off" autofocus>
        <div id="originSuggestions" class="om-suggestions"></div>
        <div class="om-tips">
          <span>Popular: </span>
          ${['London (LHR)','Manchester (MAN)','Edinburgh (EDI)','Dublin (DUB)',
             'Amsterdam (AMS)','New York (JFK)','Dubai (DXB)','Singapore (SIN)']
            .map(a => `<span class="om-chip" onclick="_selectOriginChip('${a}')">${a}</span>`)
            .join('')}
        </div>
      </div>
    </div>`;

  document.body.appendChild(modal);
  setTimeout(() => document.getElementById('originInput')?.focus(), 50);

  // Autocomplete
  let debounce;
  document.getElementById('originInput').addEventListener('input', e => {
    clearTimeout(debounce);
    debounce = setTimeout(() => _fetchSuggestions(e.target.value), 200);
  });

  document.getElementById('originInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') _resolveAndSave(e.target.value);
    if (e.key === 'Escape') window._closeOriginModal();
  });
};

window._closeOriginModal = function () {
  document.getElementById('originModal')?.remove();
};

async function _fetchSuggestions(q) {
  const box = document.getElementById('originSuggestions');
  if (!box || q.length < 2) { if (box) box.innerHTML = ''; return; }
  try {
    const r = await fetch(`${API_BASE}/locate/airports?q=${encodeURIComponent(q)}`);
    const { results = [] } = await r.json();
    box.innerHTML = results.map(s => `
      <div class="om-sug" onclick="_confirmOrigin('${s.iata}','${s.display}')">
        <span class="om-sug-iata">${s.iata}</span>
        <span class="om-sug-city">${s.city}</span>
      </div>`).join('') || '<div class="om-sug-none">No matches — try a different city</div>';
  } catch { /* silent */ }
}

async function _resolveAndSave(text) {
  if (!text.trim()) return;
  // Direct 3-letter IATA code
  if (/^[A-Za-z]{3}$/.test(text.trim())) {
    _confirmOrigin(text.trim().toUpperCase(), text.trim().toUpperCase());
    return;
  }
  // API resolve
  try {
    const r = await fetch(`${API_BASE}/locate/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.trim() }),
    });
    const d = await r.json();
    if (d.iata) {
      _confirmOrigin(d.iata, `${d.city} (${d.iata})`);
    } else {
      document.getElementById('originSuggestions').innerHTML =
        `<div class="om-sug-none">⚠ Could not find airport for "${text}". Try a major nearby city.</div>`;
    }
  } catch { /* silent */ }
}

function _confirmOrigin(iata, display) {
  if (!iata || iata === 'undefined') return;
  const safeDisplay = display || iata;
  setOrigin(iata, safeDisplay, 'manual');
  window._closeOriginModal();
  window.dispatchEvent(new CustomEvent('originChanged', { detail: { iata, display: safeDisplay } }));
}

window._selectOriginChip = function (label) {
  // "London (LHR)" → iata=LHR, display=London (LHR)
  const match = label.match(/\(([A-Z]{3})\)/);
  if (match) _confirmOrigin(match[1], label);
};

window._confirmOrigin = _confirmOrigin;
