/**
 * Sidebar UI Module
 * Manages: customer profile card, loyalty cliff-edge widget,
 * interest tags, and AI destination recommendations.
 */
import { $, $$, setText, setHTML, show, hide } from '../utils/dom.js';
import { tierIcon, destIcon, pct, num }        from '../utils/format.js';
import { setCurrentCustomer }                  from '../state.js';
import * as api                                from '../api.js';

// ── Customer selector ─────────────────────────────────────────

/** Populate the customer dropdown with all demo customers. */
export async function loadCustomerList() {
  const sel = $('#custSelect');
  if (!sel) return;

  try {
    const { customers = [] } = await api.listCustomers();
    customers.forEach(c => {
      const opt  = document.createElement('option');
      opt.value  = c.id;
      const icon = { Blue:'🔵', Silver:'🥈', Gold:'🥇', Platinum:'💎' }[c.tier] || '🔵';
      const pts  = (c.points_balance || 0).toLocaleString();
      opt.textContent = `${icon} ${c.name} — ${c.tier || 'Blue'} (${pts} pts)`;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.warn('Could not load customer list:', e.message);
  }
}

/**
 * Load and render a customer profile when selected from the dropdown.
 * Returns the resolved customer data for use by the chat module.
 */
export async function loadCustomer(customerId) {
  if (!customerId) {
    hide($('#custCard'));
    hide($('#recSection'));
    setCurrentCustomer(null);
    setText('#headerSub', "Tell me where you'd like to go");
    return null;
  }

  try {
    const data = await api.getCustomer(customerId);
    if (!data.found || !data.profile) return null;

    setCurrentCustomer(data);
    _renderProfile(data);
    _renderInterests(data);
    _renderRecommendations(data);
    await _fetchAndRenderLoyaltyPanel(data.profile.id);

    setText('#headerSub',
      `${data.profile.name} · ${data.profile.travel_style || 'leisure'} traveller · ${data.total_trips || 0} trips`
    );

    return data;
  } catch (e) {
    console.warn('Customer load error:', e.message);
    return null;
  }
}

// ── Private renderers ─────────────────────────────────────────

function _renderProfile(data) {
  const { profile } = data;
  setText('#ccName',  profile.name  || '—');
  setText('#ccEmail', profile.email || '—');
  show($('#custCard'));
}

function _renderInterests(data) {
  const interests = data.interests || {};
  const top       = (interests.top || []).slice(0, 6);
  setHTML('#interestTags', top.map(i => `<span class="int-tag">${i}</span>`).join(''));
}

function _renderRecommendations(data) {
  const recs = data.recommended_destinations || [];
  if (!recs.length) return;

  setHTML('#recCards', recs.map(r => `
    <div class="rec-card" onclick="window.VoyageApp.suggestDest('${r.destination}')">
      <span class="rec-match">${Math.round(r.match_score * 100)}%</span>
      <div class="rec-dest">${destIcon(r.destination)} ${r.destination}</div>
      <div class="rec-reason">${r.reason}</div>
    </div>
  `).join(''));

  show($('#recSection'));
}

async function _fetchAndRenderLoyaltyPanel(customerId) {
  try {
    const result = await api.getLoyalty(customerId, 0, 0, 0);
    const data   = result.data;
    if (!data) return;

    // Tier badge
    const badge = $('#ccTier');
    if (badge) {
      badge.textContent = `${tierIcon(data.current_tier)} ${data.current_tier}`;
      badge.className   = `tier-badge t-${data.current_tier}`;
    }

    setText('#ccPts',    (data.points_balance || 0).toLocaleString());
    setText('#ccNights', `${data.nights_ytd || 0} this year`);
    setText('#ccSince',  data.member_since || '—');

    _renderCliffEdge(data.cliff_edge || {}, data.current_tier);
  } catch (e) {
    console.warn('Loyalty sidebar error:', e.message);
  }
}

function _renderCliffEdge(ce, currentTier) {
  const widget = $('#cliffWidget');
  if (!widget) return;

  if (!ce.is_cliff_edge || ce.at_max_tier) {
    hide(widget);
    return;
  }

  show(widget);
  setText('#cliffTitle', `🎯 Close to ${ce.next_tier}!`);

  const ptsBar    = $('#cliffPtsBar');
  const nightsBar = $('#cliffNightsBar');
  if (ptsBar)    ptsBar.style.width    = `${Math.min(ce.points_pct, 100)}%`;
  if (nightsBar) nightsBar.style.width = `${Math.min(ce.nights_pct, 100)}%`;

  setText('#cliffPtsPct',    `${ce.points_pct}%`);
  setText('#cliffNightsPct', `${ce.nights_pct}%`);
  setText('#cliffMsg',       ce.message || '');
}
