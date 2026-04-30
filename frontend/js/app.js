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
import { initVoiceInput }                from './ui/voice_input.js';
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
  // Build subtitle — guard against undefined values
  const _style  = (auth.travel_style || '').toLowerCase().trim();
  const _origin = getOriginDisplay();
  const _sub    = _style && _style !== 'undefined'
    ? `${auth.name} · ${_style} traveller`
    : `${auth.name}`;
  setText('#headerSub', _sub);

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

  // Voice input — microphone button
  initVoiceInput('#messageInput', '#voiceBtn');

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

  // When origin detected or changed, update subtitle
  window.addEventListener('originChanged', e => {
    const { iata, display } = e.detail;
    if (display && iata && iata !== 'undefined') {
      const style = (auth.travel_style || '').toLowerCase().trim();
      const stylePart = style && style !== 'undefined' ? ` · ${style} traveller` : '';
      setText('#headerSub', `${auth.name}${stylePart} · ✈ ${display}`);
    }
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
  // Guard: always show something, never go blank
  if (!data) { appendAI('No response from server. Please try again.'); return; }

  const status = data.status || '';
  const out    = data.llm_output || {};

  // ── Simple status responses ──────────────────────────────
  if (status === 'clarifying') {
    const icons = {dates:'📅',guests:'👥',hotel:'🏨',flight:'✈️',budget:'💷',destination:'📍'};
    const icon  = icons[data.modification_type] || '✏️';
    appendAI(`${icon} <strong>${data.message || 'Could you give me more details?'}</strong>`);
    return;
  }
  if (status === 'cancelled') {
    appendAI(`🗑️ <strong style="color:var(--amber)">Plan cancelled.</strong><br>
      <span style="color:var(--muted)">Where would you like to go next?</span>`);
    return;
  }
  if (status === 'confirmed') {
    appendAI(`🎉 <strong style="color:var(--teal)">Booking Confirmed!</strong><br>
      Reference: VGI-${state.getSessionId().toUpperCase()}`);
    stopTimer();
    return;
  }
  if (status === 'rejected') {
    appendAI(`🛡️ <strong style="color:var(--amber)">Blocked:</strong> ${data.message || data.reason || ''}`);
    return;
  }
  if (status === 'session_expired') {
    if (data.session_id) state.setSessionId(data.session_id);
    stopTimer();
    appendAI(`⏱️ ${data.message || 'Session expired.'}`);
    return;
  }

  // ── Destination suggestions ──────────────────────────────
  if (status === 'suggestions' || out.is_suggestions) {
    const suggestions = data.suggestions || out.suggestions || [];
    const summary     = data.summary     || out.summary     || 'Here are some options:';
    appendAI(_renderSuggestions(summary, suggestions));
    return;
  }

  // ── Human handoff ────────────────────────────────────────
  if (status === 'human_handoff') {
    appendAI(`🤝 <strong style="color:var(--amber)">Our specialists will assist you.</strong><br>
      <span style="color:var(--muted)">The AI couldn't complete this with enough confidence. 
      Try: <em>"Seychelles 2 adults 1 week October £4000"</em></span>`);
    return;
  }

  // ── Any response with a valid itinerary ──────────────────
  // Covers: ready, awaiting_confirmation, modified, planning
  if (out.intent && out.recommendations) {
    const conf = data.confidence  || { overall: 0.80, passed: true };
    const ac   = data.action_check || { passed: true, action: 'proceed' };
    const meta = {
      p:    data.llm_provider   || 'template',
      m:    data.llm_model      || '',
      ms:   data.elapsed_ms     || 0,
      cost: data.llm_cost_usd   || 0,
    };

    // Show text summary first
    if (out.summary) appendAI(out.summary);

    // Render full card — catch any JS error and show text fallback
    try {
      await renderItineraryCard(out, conf, ac, meta, data);
    } catch (err) {
      console.error('Card render error:', err);
      const i = out.intent || {};
      const d = i.dates   || {};
      const t = out.total_cost_gbp || 0;
      appendAI(`<div style="padding:14px;border:1px solid var(--teal);border-radius:10px;background:var(--bg2)">
        <strong style="color:var(--teal)">✈ ${i.destination || 'Your Trip'}</strong><br>
        <span style="color:var(--muted);font-size:13px">
          ${d.departure_date || ''} → ${d.return_date || ''} &nbsp;·&nbsp;
          ${i.guests || 2} guests &nbsp;·&nbsp; £${Math.round(t).toLocaleString()}<br>
          <em style="color:var(--dim)">Reply "confirm" to book or ask to change anything.</em>
        </span></div>`);
    }

    // Show modification version history
    if (data.is_modification && data.version_history?.length > 1) {
      const hist = data.version_history;
      const tl = hist.map((v,i) =>
        `<span style="color:${i===hist.length-1?'var(--teal)':'var(--dim)'}">
          v${v.version} ${v.modification_type||'initial'} £${Math.round(v.total_cost_gbp||0).toLocaleString()}
        </span>`).join(' → ');
      appendAI(`<small style="color:var(--dim)">History: ${tl}</small>`);
    }
    return;
  }

  // ── Fallback: show whatever we have ─────────────────────
  const msg = out.summary || data.message || data.reason || '';
  if (msg) {
    appendAI(msg);
  } else {
    // Absolute last resort — never go blank
    appendAI(`<span style="color:var(--muted)">I couldn't build that itinerary. 
      Try: <em>"Dubai 2 people 1 week November £3000"</em></span>`);
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

// Direct global fallback so onclick works even during module init
window.toggleAncillary = toggleAncillary;
window.switchTab       = switchTab;
window.confirmEl       = confirmEl;
window.cancelBooking   = cancelBooking;
window.modifyTrip      = modifyTrip;

// ── Start ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);

function _renderSuggestions(text, suggestions) {
  // Build suggestion cards from structured suggestions array when available
  // Fall back to parsing the text string

  let itemsHtml = '';

  if (suggestions && suggestions.length > 0) {
    // Render from structured data — each item is independently clickable
    itemsHtml = suggestions.map((s, i) => {
      const dest     = s.destination || '';
      const country  = s.country     || '';
      const tagline  = s.tagline     || s.why_this_fits || '';
      const budget   = s.budget_pp_gbp;
      const duration = s.duration_suggestion || '7 nights';
      const best     = s.best_time   || '';
      const highlights = (s.highlights || []).slice(0, 3);

      let budgetStr = '';
      if (budget) {
        try {
          const b = parseInt(String(budget).replace(/[^0-9]/g,''));
          budgetStr = isNaN(b) ? '' : ` · ~£${b.toLocaleString()}/pp`;
        } catch(e) {}
      }

      const hlHtml = highlights.length
        ? `<div class="sug-highlights">${highlights.map(h =>
            `<span class="sug-hl">✦ ${h}</span>`).join('')}</div>`
        : '';

      const metaLine = [best ? `📅 ${best}` : '', budgetStr ? `💷${budgetStr}` : '']
        .filter(Boolean).join(' &nbsp;·&nbsp; ');

      return `<div class="sug-item" onclick="window._pickSuggestion(this)"
                   data-destination="${dest}" data-number="${i+1}">
        <div class="sug-num">${i + 1}</div>
        <div class="sug-content">
          <div class="sug-name"><strong>${dest}</strong>${country ? `, <span class="sug-country">${country}</span>` : ''}</div>
          ${tagline ? `<div class="sug-tagline">${tagline}</div>` : ''}
          ${hlHtml}
          ${metaLine ? `<div class="sug-meta">${metaLine}</div>` : ''}
        </div>
        <div class="sug-arrow">→</div>
      </div>`;
    }).join('');
  } else {
    // Fallback: parse the text string into items
    // Split on numbered lines: "1. Dest", "2. Dest", "3. Dest"
    const lines = text.split(/\n/);
    const items = [];
    let current = null;

    for (const line of lines) {
      const numMatch = line.match(/^(\d+)\.\s+[*]*([^*\n]+)/);
      if (numMatch) {
        if (current) items.push(current);
        current = { num: numMatch[1], name: numMatch[2].replace(/[*]/g,'').trim(), rest: [] };
      } else if (current && line.trim()) {
        current.rest.push(line.trim());
      }
    }
    if (current) items.push(current);

    if (items.length > 0) {
      itemsHtml = items.map(item =>
        `<div class="sug-item" onclick="window._pickSuggestion(this)"
              data-destination="${item.name}" data-number="${item.num}">
          <div class="sug-num">${item.num}</div>
          <div class="sug-content">
            <div class="sug-name"><strong>${item.name}</strong></div>
            ${item.rest.length ? `<div class="sug-tagline">${item.rest.slice(0,2).join(' ')}</div>` : ''}
          </div>
          <div class="sug-arrow">→</div>
        </div>`
      ).join('');
    } else {
      // Plain text — no numbered items found
      const escaped = text
        .replace(/[*][*]([^*]+)[*][*]/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
      itemsHtml = `<div style="padding:8px 4px;color:var(--muted)">${escaped}</div>`;
    }
  }

  return `<div class="suggestion-card">
    <div class="sug-header">
      <span>✈ Destination Suggestions</span>
      <span style="font-size:11px;font-weight:400;color:var(--muted)">powered by AI</span>
    </div>
    <div class="sug-body">${itemsHtml}</div>
    <div class="sug-footer">
      <span style="color:var(--dim);font-size:11px">
        Tap any destination to build a full personalised itinerary
      </span>
    </div>
  </div>`;
}

window._pickSuggestion = function(el) {
  // Get destination name and iata from the card
  const dest = el.dataset.destination
             || el.querySelector('.sug-name strong')?.textContent?.trim()
             || el.textContent.trim();
  if (!dest) return;

  // Build a complete, context-rich prompt so no further questions are needed
  const customer  = state.getCurrentCustomer();
  const profile   = customer?.profile || {};
  const patterns  = customer?.patterns || {};
  const loyalty   = customer?.loyalty  || {};
  const interests = (customer?.interests?.top || []).join(', ');

  // Pull typical trip parameters from customer profile
  const nights    = patterns.typical_nights    || profile.typical_nights    || 7;
  const budget    = patterns.typical_budget_gbp|| profile.typical_budget_gbp|| 3000;
  const adults    = profile.adults_in_family   || 2;
  const children  = profile.children_in_family || 0;
  const guests    = adults + children;
  const style     = profile.travel_style       || 'leisure';
  const tier      = loyalty.current_tier       || 'Blue';

  // Build guest string
  const guestStr  = children > 0
    ? `${adults} adults and ${children} children (family of ${guests})`
    : `${guests} adults`;

  // Build interest phrase
  const interestStr = interests
    ? `My travel interests include: ${interests}.`
    : '';

  // Build complete prompt — no clarifying questions needed
  const parts = [
    `Plan a trip to ${dest} for ${guestStr}.`,
    budget  ? `My typical trip budget is around £${budget.toLocaleString()}.` : '',
    nights  ? `My typical trip is around ${nights} nights.` : '',
    style   ? `I am a ${style} traveller.` : '',
    interestStr,
    tier !== 'Blue' ? `I am a ${tier} loyalty member — please include any relevant member benefits.` : '',
    children > 0  ? `We are travelling with ${children} children — please suggest family-friendly hotels and activities.` : '',
    'Please build me a complete personalised itinerary.',
  ].filter(Boolean).join(' ');

  const ta = document.getElementById('messageInput');
  if (ta) {
    ta.value = parts;
    ta.dispatchEvent(new Event('input'));
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }

  // Auto-send immediately — all context is in the prompt
  setTimeout(() => {
    const sendBtn = document.getElementById('sendBtn');
    if (sendBtn) sendBtn.click();
  }, 80);
};

