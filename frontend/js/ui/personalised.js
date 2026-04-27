/**
 * Personalised Panel UI Module
 * Builds the "For You" tab — AI destination recommendations + travel history.
 * Pure HTML-builder.
 */
import { destIcon, num } from '../utils/format.js';

/**
 * Build personalised recommendations panel.
 * @param {object} customerData — full customer object from API
 * @returns {string}            — HTML string
 */
export function buildPersonalisedPanel(customerData) {
  if (!customerData) {
    return `
      <div style="padding:16px;color:var(--muted)">
        Select a customer profile from the left sidebar to see
        personalised recommendations.
      </div>
    `;
  }

  const recs     = customerData.recommended_destinations || [];
  const patterns = customerData.patterns  || {};
  const interests= customerData.interests || {};
  const history  = customerData.history   || [];

  return `
    ${_interestSummary(interests, patterns, customerData.total_trips)}
    ${_interestTags(interests.top || [])}
    ${_recommendations(recs)}
    ${history.length ? _recentHistory(history) : ''}
  `;
}

// ── Private builders ──────────────────────────────────────────

function _interestSummary(interests, patterns, totalTrips) {
  const avgSpend  = num(patterns.avg_spend_per_trip_gbp || 0);
  const prefMonth = patterns.preferred_travel_month || 'Summer';
  const countries = patterns.total_countries_visited || 0;

  return `
    <div class="slbl">💡 AI Trip Recommendations</div>
    <div style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.6">
      Based on <strong style="color:var(--text)">${totalTrips || 0}</strong> past trips ·
      avg <strong style="color:var(--teal)">£${avgSpend}</strong> per trip ·
      prefers <strong style="color:var(--text)">${prefMonth}</strong> ·
      <strong style="color:var(--text)">${countries}</strong> countries visited
    </div>
  `;
}

function _interestTags(top) {
  if (!top.length) return '';
  const tags = top.slice(0, 8).map(i => `<span class="int-tag">${i}</span>`).join('');
  return `<div class="interest-tags" style="margin-bottom:12px">${tags}</div>`;
}

function _recommendations(recs) {
  if (!recs.length) {
    return '<div style="font-size:12px;color:var(--muted)">No recommendations yet — more trips needed.</div>';
  }
  const cards = recs.map(r => `
    <div class="pers-card" onclick="window.VoyageApp.suggestDest('${r.destination}')">
      <div class="pers-icon">${destIcon(r.destination)}</div>
      <div style="flex:1;min-width:0">
        <div class="pers-dest">${r.destination}</div>
        <div class="pers-reason">${r.reason}</div>
      </div>
      <div class="pers-match">${Math.round(r.match_score * 100)}%</div>
    </div>
  `).join('');
  return `<div class="pers-rec" style="margin-bottom:16px">${cards}</div>`;
}

function _recentHistory(history) {
  const rows = history.slice(0, 5).map(h => {
    const year   = (h.departure_date || '').split('-')[0] || '';
    const rating = '⭐'.repeat(h.rating || 4);
    return `
      <div class="cost-row">
        <span class="cost-lbl">${h.destination} · ${year}</span>
        <span class="cost-val" style="font-size:12px">
          £${num(h.total_spent_gbp)} · ${rating}
        </span>
      </div>
    `;
  }).join('');

  return `
    <div style="margin-top:4px">
      <div class="slbl">📅 Recent Trips</div>
      <div style="margin-top:8px">${rows}</div>
    </div>
  `;
}
