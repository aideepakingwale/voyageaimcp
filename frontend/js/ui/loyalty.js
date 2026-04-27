/**
 * Loyalty Panel UI Module
 * Builds the HTML for the Loyalty tab inside an itinerary card.
 * Pure HTML-builder — no DOM mutations, no fetch calls.
 */
import { tierIcon, num, pct } from '../utils/format.js';

/**
 * Build the full loyalty panel HTML from API data.
 * @param {object} data  — response from /api/loyalty/<id>
 * @returns {string}     — HTML string ready for innerHTML
 */
export function buildLoyaltyPanel(data) {
  if (!data) {
    return '<div style="padding:16px;color:var(--muted)">No loyalty data available.</div>';
  }

  const ce     = data.cliff_edge     || {};
  const earn   = data.trip_earnings  || {};
  const perks  = data.applicable_benefits || [];
  const redeem = data.redemption_options  || [];

  return `
    ${_memberHeader(data)}
    ${_perksSection(perks)}
    ${_earnBox(earn, data.current_tier)}
    ${ce.is_cliff_edge && !ce.at_max_tier ? _cliffMessage(ce) : ''}
    ${earn.will_tier_up ? _tierUpBanner(data.next_tier, earn) : ''}
    ${redeem.length ? _redemptionSection(redeem) : ''}
  `;
}

// ── Private builders ─────────────────────────────────────────

function _memberHeader(data) {
  return `
    <div class="loyalty-panel">
      <div class="lp-header">
        <div>
          <div class="lp-title">
            ${tierIcon(data.current_tier)} ${data.current_tier} Member — ${data.member_id || ''}
          </div>
          <div style="font-size:12px;color:var(--muted)">
            Member since ${data.member_since} · Expires ${data.tier_expiry}
          </div>
        </div>
      </div>
  `;  // <-- loyalty-panel closed at end of _earnBox
}

function _perksSection(perks) {
  if (!perks.length) return '<div class="lp-perks"></div>';
  const rows = perks.map(p => `
    <div class="lp-perk">
      <div class="lp-perk-icon">${p.icon}</div>
      <div>
        <div class="lp-perk-title">${p.title}</div>
        <div class="lp-perk-desc">${p.desc}</div>
      </div>
      <div class="lp-perk-val">${p.value}</div>
    </div>
  `).join('');
  return `<div class="lp-perks">${rows}</div>`;
}

function _earnBox(earn, tier) {
  const pts = (earn.points_to_earn || 0).toLocaleString();
  const bal = (earn.new_balance    || 0).toLocaleString();
  return `
    <div class="earn-box">
      <div>
        <div class="earn-label">Points earned on this trip</div>
      </div>
      <div style="text-align:right">
        <div class="earn-pts">+${pts}</div>
        <div class="earn-label">
          ${earn.multiplier || 1}× multiplier · New balance: ${bal}
        </div>
      </div>
    </div>
  </div>`; // closes loyalty-panel div from _memberHeader
}

function _cliffMessage(ce) {
  return `
    <div class="cliff-msg" style="margin-top:8px;padding:0 14px 10px">
      ${ce.message || ''}
    </div>
  `;
}

function _tierUpBanner(nextTier, earn) {
  return `
    <div class="tier-up-banner">
      🎉 This trip qualifies you for <strong>${nextTier}</strong> tier!
      You'll earn ${(earn.points_to_earn || 0).toLocaleString()} points,
      reaching ${earn.nights_after || 0} nights — above the threshold.
    </div>
  `;
}

function _redemptionSection(options) {
  const rows = options.map(r => `
    <div class="cost-row">
      <span class="cost-lbl">${r.icon} ${r.reward}</span>
      <span class="cost-val" style="font-size:12px">
        ${r.points.toLocaleString()} pts
      </span>
    </div>
  `).join('');

  return `
    <div style="margin-top:12px">
      <div class="slbl">🎁 Redeem Your Points</div>
      <div style="margin-top:8px">${rows}</div>
    </div>
  `;
}
