/**
 * VoyageAI Application — Main Orchestrator
 * Auth-gated: reads sessionStorage for logged-in user.
 * Redirects to /login if no valid auth found.
 */
import { Config }                          from './config.js';
import * as api                            from './api.js';
import * as state                          from './state.js';
import { appendUser, appendAI, showTyping,
         hideTyping, hideSuggestions }     from './ui/chat.js';
import { renderItineraryCard, switchTab }  from './ui/itinerary.js';
import { startTimer, stopTimer }           from './ui/gds_timer.js';
import { startMcpAnimation, settleMcpChips,
         highlightProvider,
         applyWaterfallStatus }            from './ui/waterfall.js';
import { initOrigin, getOriginIata,
         getOriginDisplay }               from './ui/origin_selector.js';
import { $, setText, autoResize, show,
         hide, setHTML }                   from './utils/dom.js';
import { tierIcon, destIcon }              from './utils/format.js';
import { saveContextToLocalStorage, loadContextFromLocalStorage,
         clearLocalStorage }             from './state.js';
import { toggleAncillary as _toggleAnc,
         getAncillaryTotal }               from './state.js';
import { buildRecommendationPrompt,
         enrichManualPrompt }              from './utils/prompt_builder.js';

// ── Auth guard ────────────────────────────────────────────────

function getAuth() {
  try {
    const raw = sessionStorage.getItem('voyage_auth');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function redirectToLogin() {
  sessionStorage.removeItem('voyage_auth');
  clearLocalStorage();
  window.location.href = '/login';
}

// ── Boot ──────────────────────────────────────────────────────

async function init() {
  const auth = getAuth();
  if (!auth?.token || !auth?.session_id) {
    redirectToLogin();
    return;
  }

  // Store in state
  state.setSessionId(auth.session_id);
  saveContextToLocalStorage();
  state.setCurrentCustomer({
    profile: {
      id:                  auth.customer_id,
      name:                auth.name,
      email:               auth.email,
      travel_style:        auth.travel_style,
      adults_in_family:    auth.adults,
      children_in_family:  auth.children,
    },
    loyalty: {
      current_tier: auth.tier,
      member_id:    auth.member_id,
      points_balance: auth.points,
    },
  });

  // Render user panel
  _renderUserPanel(auth);

  // Welcome message personalised to the customer
  const greeting = _greeting(auth.name);
  appendAI(`
    <strong style="color:var(--teal)">${greeting}</strong><br><br>
    ${_tierWelcome(auth.tier, auth.points)}
    <br><br>
    Where would you like to go? I'll find the best flights, hotels, and experiences
    — with your loyalty benefits automatically applied.
  `);

  // Update header
  setText('#headerSub', `${auth.name} · ${auth.travel_style || 'leisure'} traveller`);

  // Create fresh session for this login
  state.setSessionId(auth.session_id);

  // Init origin airport detection
  initOrigin();

  // Load full customer profile (interests + recommendations)
  _loadCustomerProfile(auth.customer_id);

  // Waterfall status
  try {
    const status = await api.getWaterfallStatus();
    applyWaterfallStatus(status, null);
  } catch { /* silent */ }

  // DOM events
  _bindEvents(auth);
}

// ── Render user panel ─────────────────────────────────────────

function _renderUserPanel(auth) {
  // Avatar — first letter of first name
  const initials = (auth.name || '?').charAt(0).toUpperCase();
  setText('#userAvatar',  initials);
  setText('#userName',    auth.name);
  setText('#userEmail',   auth.email);
  setText('#ccPts',       (auth.points || 0).toLocaleString());
  setText('#ccMemberId',  auth.member_id || '—');
  setText('#ccSince',     auth.member_since || '—');

  const tierEl = $('#userTier');
  if (tierEl) {
    tierEl.textContent = `${tierIcon(auth.tier)} ${auth.tier}`;
    tierEl.className   = `tier-badge t-${auth.tier}`;
  }

  // Fetch loyalty for cliff-edge widget
  api.getLoyalty(auth.customer_id, 0, 0, 0)
    .then(r => _renderCliffEdge(r.data))
    .catch(() => {});
}

function _renderCliffEdge(data) {
  if (!data) return;
  const ce = data.cliff_edge || {};
  if (!ce.is_cliff_edge || ce.at_max_tier) return;

  show($('#cliffWidget'));
  setText('#cliffTitle',     `🎯 Close to ${ce.next_tier}!`);
  setText('#cliffPtsPct',    ce.points_pct  + '%');
  setText('#cliffNightsPct', ce.nights_pct  + '%');
  setText('#cliffMsg',       ce.message || '');

  const pb = $('#cliffPtsBar');
  const nb = $('#cliffNightsBar');
  if (pb) pb.style.width = Math.min(ce.points_pct, 100)  + '%';
  if (nb) nb.style.width = Math.min(ce.nights_pct, 100) + '%';
}

async function _loadCustomerProfile(customerId) {
  try {
    const data = await api.getCustomer(customerId);
    if (!data.found) return;

    // Enrich state
    const current = state.getCurrentCustomer();
    state.setCurrentCustomer({
      ...current,
      interests: data.interests,
      patterns:  data.patterns,
      history:   data.history,
      recommended_destinations: data.recommended_destinations,
      total_trips: data.total_trips,
    });

    // Render interests + recommendations in sidebar
    _renderInterestsSidebar(data);

  } catch (e) {
    console.warn('Profile load error:', e.message);
  }
}

function _renderInterestsSidebar(data) {
  const interests = data.interests?.top || [];
  const patterns  = data.patterns       || {};
  const recs      = data.recommended_destinations || [];

  const line = $('#interestLine');
  if (line && patterns.primary_trip_type) {
    line.textContent =
      `${patterns.primary_trip_type} traveller · avg £${Math.round(patterns.avg_spend_per_trip_gbp || 0)}/trip · prefers ${patterns.preferred_travel_month || 'summer'}`;
  }

  setHTML('#interestTags',
    interests.slice(0, 6)
      .map(i => `<span class="int-tag">${i}</span>`)
      .join('')
  );

  const rcards = $('#recCards');
  if (rcards) {
    rcards.innerHTML = recs.map(r => `
      <div class="rec-card"
           data-dest="${r.destination}"
           data-reason="${(r.reason || '').replace(/"/g, '&quot;')}"
           data-score="${r.match_score || 0}">
        <span class="rec-match">${Math.round(r.match_score * 100)}% match</span>
        <div class="rec-dest">${destIcon(r.destination)} ${r.destination}</div>
        <div class="rec-reason">${r.reason}</div>
      </div>
    `).join('');

    rcards.querySelectorAll('.rec-card').forEach(card => {
      card.addEventListener('click', () => {
        const dest    = card.dataset.dest;
        const reason  = card.dataset.reason  || '';
        const score   = card.dataset.score   || '0';
        const customer = state.getCurrentCustomer();

        // Build rich personalised prompt from customer context
        const prompt = buildRecommendationPrompt(
          dest,
          { reason, match_score: parseFloat(score) },
          customer
        );

        const ta = $('#messageInput');
        if (ta) { ta.value = prompt; autoResize(ta); }
        send();
      });
    });
  }

  if (recs.length > 0) show($('#recSection'));
}

// ── DOM events ────────────────────────────────────────────────

function _bindEvents(auth) {
  // Send button
  $('#sendBtn')?.addEventListener('click', send);

  // Textarea
  const ta = $('#messageInput');
  if (ta) {
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    ta.addEventListener('input', () => autoResize(ta));
  }

  // Suggestion chips
  document.querySelectorAll('.sugg').forEach(chip => {
    chip.addEventListener('click', () => {
      const ta = $('#messageInput');
      if (ta) { ta.value = chip.dataset.msg || chip.textContent.trim(); autoResize(ta); send(); }
    });
  });

  // Sign out
  $('#signoutBtn')?.addEventListener('click', () => doLogout(auth));

  // When user changes origin airport, update state
  window.addEventListener('originChanged', e => {
    const { iata, display } = e.detail;
    setText('#headerSub', `${auth.name} · Flying from ${display}`);
  });
}

// ── Sign out ──────────────────────────────────────────────────

async function doLogout(auth) {
  try {
    await api.logout(auth.token, auth.session_id);
  } catch { /* best effort */ }
  sessionStorage.removeItem('voyage_auth');
  window.location.href = '/login';
}

// ── Send ──────────────────────────────────────────────────────

async function send() {
  const ta  = $('#messageInput');
  const msg = ta?.value?.trim();
  if (!msg || state.isLoading()) return;

  ta.value = '';
  autoResize(ta);
  hideSuggestions();
  appendUser(msg);
  _setLoading(true);
  startMcpAnimation();

  if (!state.getGdsStart()) startTimer();

  const customer = state.getCurrentCustomer();

  // Silently enrich short manual prompts with customer context
  // (recommendations already arrive pre-enriched from prompt_builder)
  const enrichedMsg = (msg.length < 120 && customer?.profile)
    ? enrichManualPrompt(msg, customer)
    : msg;

  const ctx = customer?.profile ? {
    name:         customer.profile.name,
    travel_style: customer.profile.travel_style,
    interests:    customer.interests?.top || [],
    loyalty_tier: customer.loyalty?.current_tier || '',
    children:     customer.profile.children_in_family || 0,
    adults:       customer.profile.adults_in_family   || 2,
  } : null;

  try {
    const originIata = getOriginIata();
    const data = Config.USE_DEMO
      ? await api.sendDemo(enrichedMsg, state.getSessionId())
      : await api.sendChat(enrichedMsg, state.getSessionId(), ctx, originIata);

    if (data.session_id) state.setSessionId(data.session_id);
    if (data.llm_provider) highlightProvider(data.llm_provider, 'ok');
    await _handleResponse(data);
  } catch (err) {
    appendAI(`⚠️ Server error: ${err.message}`);
  }

  _setLoading(false);
  settleMcpChips();
}

// ── Response handler ──────────────────────────────────────────

async function _handleResponse(data) {
  if (!data) { appendAI('⚠️ Empty response.'); return; }

  const state_val = data.conversation_state || data.status;

  // ── Clarification question ────────────────────────────────
  if (data.status === 'clarifying') {
    const modType = data.modification_type || '';
    const icon    = { dates:'📅', guests:'👥', hotel:'🏨', flight:'✈️', budget:'💷' }[modType] || '✏️';
    appendAI(`${icon} <strong>${data.message}</strong>`);
    return;
  }

  // ── Plan cancelled ────────────────────────────────────────
  if (data.status === 'cancelled') {
    appendAI(`🗑️ <strong style="color:var(--amber)">Plan cancelled.</strong><br>
      <span style="color:var(--muted)">Where would you like to go?</span>`);
    return;
  }

  // ── Plan confirmed ────────────────────────────────────────
  if (data.status === 'confirmed') {
    appendAI(`🎉 <strong style="color:var(--teal)">Booking Confirmed!</strong><br>
      Reference: VGI-${state.getSessionId().toUpperCase()}<br>
      <span style="color:var(--muted)">You'll receive a confirmation email shortly.</span>`);
    stopTimer();
    return;
  }

  // ── Rejected ──────────────────────────────────────────────
  if (data.status === 'rejected') {
    appendAI(`🛡️ <strong style="color:var(--amber)">Blocked:</strong> ${data.message || data.reason}`);
    return;
  }

  // ── Session expired ───────────────────────────────────────
  if (data.status === 'session_expired') {
    state.setSessionId(data.session_id);
    stopTimer();
    appendAI(`⏱️ ${data.message}`);
    return;
  }

  // ── Human handoff ─────────────────────────────────────────
  if (data.status === 'human_handoff') {
    appendAI(`🤝 <strong style="color:var(--amber)">Connecting to a specialist</strong><br>
      <span style="color:var(--muted)">${data.message || 'AI could not complete this with sufficient confidence.'}</span><br><br>
      💡 <em style="color:var(--dim)">Tip: Try being more specific — e.g. "Seychelles for 4 people, 2 weeks in October, £5000 budget"</em>`);
    return;
  }

  // ── Modification result ───────────────────────────────────
  if ((data.is_modification || data.conversation_state === 'modified') && data.llm_output) {
    const out  = data.llm_output;
    const conf = data.confidence || { overall: 0.88, passed: true };
    const ac   = data.action_check || { passed: true, action: 'proceed' };
    const meta = { p: data.llm_provider || 'conversation_engine',
                   m: '', ms: data.elapsed_ms || 0, cost: 0 };

    const modType = data.modification_type || 'plan';
    const icons   = { dates:'📅', guests:'👥', hotel:'🏨', flight:'✈️',
                      budget:'💷', destination:'📍' };
    const labels  = { dates:'Dates Updated', guests:'Guests Updated',
                      hotel:'Hotel Updated', flight:'Flights Updated',
                      budget:'Budget Updated', destination:'Destination Changed' };
    const icon    = icons[modType]  || '✏️';
    const label   = labels[modType] || 'Plan Updated';

    // Show the summary message from backend
    const summary = out.summary || `${icon} ${label}`;
    appendAI(summary);

    // Always re-render the full itinerary card with updated data
    await renderItineraryCard(out, conf, ac, meta, data);

    // Show version history if available
    if (data.version_history && data.version_history.length > 1) {
      const hist = data.version_history;
      const timeline = hist.map((v, i) =>
        `<span style="color:${i===hist.length-1 ? 'var(--teal)' : 'var(--dim)'}">
          v${v.version} ${v.modification_type || 'initial'} £${Math.round(v.total_cost_gbp||0).toLocaleString()}
         </span>`
      ).join(' → ');
      appendAI(`<small style="color:var(--dim)">Version history: ${timeline}</small>`);
    }
    return;
  }

  // ── Normal itinerary ──────────────────────────────────────
  const out  = data.llm_output  || {};
  const conf = data.confidence  || {};
  const ac   = data.action_check || {};
  const meta = { p: data.llm_provider || 'demo', m: data.llm_model || '',
                 ms: data.elapsed_ms || 0, cost: data.llm_cost_usd || 0 };

  if (out.intent && out.recommendations) {
    await renderItineraryCard(out, conf, ac, meta, data);
  } else if (out.summary) {
    appendAI(out.summary);
  } else {
    appendAI('<em style="color:var(--muted)">No itinerary found — try being more specific:</em><br>' +
             '<em style="color:var(--dim)">e.g. "Seychelles 4 people 2 weeks October £4000"</em>');
  }
}

// ── Booking flow ──────────────────────────────────────────────

async function confirmEl(element) {
  appendAI(`<span style="color:var(--teal)">✓ <strong>${_cap(element)}</strong> confirmed…</span>`);
  try {
    const r = await api.confirmElement(state.getSessionId(), element, {});
    if (r.status === 'confirmed') {
      appendAI(`🎉 <strong style="color:var(--teal)">Booking Complete!</strong><br>Reference: VGI-${state.getSessionId().toUpperCase()}`);
      stopTimer();
    } else {
      appendAI(`✓ ${_cap(element)} confirmed.${r.next_step ? ` Confirm <strong>${r.next_step}</strong> next.` : ''}`);
    }
  } catch { appendAI('Confirmation failed — please retry.'); }
}

async function cancelBooking() {
  await api.confirmElement(state.getSessionId(), 'booking', {}, 'reject').catch(() => {});
  appendAI('Booking cancelled. How can I help you?');
}

function modifyTrip() {
  const ta = $('#messageInput');
  if (ta) { ta.value = 'I want to change '; ta.focus(); }
}

function toggleAncillary(id, name, price) {
  const selected = _toggleAnc(id, name, parseFloat(price));
  document.getElementById(`anc-${id}`)?.classList.toggle('selected', selected);
  const check = document.getElementById(`ancc-${id}`);
  if (check) check.style.background = selected ? 'var(--teal)' : '';
  const el = document.getElementById('selAncTotal');
  if (el) el.textContent = `£${getAncillaryTotal().toFixed(0)}`;
}

// ── Helpers ───────────────────────────────────────────────────

function _setLoading(on) {
  state.setLoading(on);
  if (on) saveContextToLocalStorage();
  const btn = $('#sendBtn');
  if (btn) btn.disabled = on;
  setText('#statusText', on ? 'Reasoning…' : 'Ready');
  if (on) showTyping(); else hideTyping();
}

function _cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }

function _greeting(name) {
  const h = new Date().getHours();
  const first = (name || '').split(' ')[0];
  if (h < 12) return `Good morning, ${first}!`;
  if (h < 17) return `Good afternoon, ${first}!`;
  return `Good evening, ${first}!`;
}

function _tierWelcome(tier, points) {
  const map = {
    Platinum: `As a 💎 <strong>Platinum</strong> member with <strong>${(points||0).toLocaleString()} points</strong>, you have access to our most exclusive benefits — private transfers, guaranteed suite upgrades, and a personal travel manager.`,
    Gold:     `As a 🥇 <strong>Gold</strong> member with <strong>${(points||0).toLocaleString()} points</strong>, enjoy airport lounge access, complimentary room upgrades, and a 20% hotel discount on your next trip.`,
    Silver:   `As a 🥈 <strong>Silver</strong> member with <strong>${(points||0).toLocaleString()} points</strong>, you receive priority check-in, 10% hotel discounts, and earn 1.5× points on every booking.`,
    Blue:     `Welcome! You have <strong>${(points||0).toLocaleString()} points</strong> in your account. Every trip earns you more points — keep travelling to unlock Silver, Gold, and Platinum benefits.`,
  };
  return map[tier] || '';
}

// ── Window API for inline onclick handlers ────────────────────

window.VoyageApp = { send, confirmEl, cancelBooking, modifyTrip, switchTab, toggleAncillary };

// ── Start ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
