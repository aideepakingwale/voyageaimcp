/**
 * Itinerary Card UI Module
 * Builds the full tabbed itinerary card HTML.
 * Calls loyalty + ancillary APIs and delegates to sub-modules.
 */
import { $, $$ }                           from '../utils/dom.js';
import { num, pct, scoreColor, fmtTime,
         providerClass, providerIcon,
         tierIcon }                        from '../utils/format.js';
import { appendCard }                      from './chat.js';
import { buildLoyaltyPanel }               from './loyalty.js';
import { buildAncillariesPanel }           from './ancillaries.js';
import { buildPersonalisedPanel }          from './personalised.js';
import { buildVisaPanel }                  from './visa_panel.js';
import { getCurrentCustomer,
         setCurrentItinerary }             from '../state.js';
import * as api                            from '../api.js';

/**
 * Render a full itinerary card from reasoning engine output.
 * Fetches loyalty + ancillary data if a customer is loaded.
 */
export async function renderItineraryCard(out, conf, actionCheck, meta, rawData = {}) {
  setCurrentItinerary(out);
  const mcp_data = rawData.mcp_data || {};

  const customer = getCurrentCustomer();
  const cid      = customer?.profile?.id;

  const intent = out.intent         || {};
  const recs   = out.recommendations || {};
  const dates  = intent.dates        || {};
  const flight = (recs.flights      || [])[0] || {};
  const hotel  = (recs.hotels       || [])[0] || {};
  const transf = (recs.transfers    || [])[0] || {};
  const exps   = (recs.experiences  || []).slice(0, 3);
  const total  = out.total_cost_gbp  || 0;
  const budget = intent.budget_gbp   || 9999;

  // Fetch loyalty + ancillaries in parallel when customer known
  let loyaltyHTML    = '';
  let ancillaryHTML  = '';
  let personalisedHTML = '';
  let visaHTML = '';

  if (cid) {
    try {
      const [loyRes, ancRes] = await Promise.all([
        api.getLoyalty(cid, total, dates.nights || 7, 1),
        api.getAncillaries({
          city_code:       intent.city_code       || 'LIS',
          departure_date:  dates.departure_date   || '',
          arrival_time:    flight.arrival         || '',
          guests:          intent.guests          || 2,
          adults:          intent.adults          || 2,
          children:        intent.children        || 0,
          trip_type:       intent.trip_type       || 'leisure',
          interests:       customer.interests?.top || [],
          loyalty_tier:    customer.loyalty?.current_tier || 'Blue',
          nights:          dates.nights           || 7,
          hotel_stars:     hotel.stars            || 4,
          budget_gbp:      budget,
          trip_cost_so_far:total,
        }),
      ]);

      loyaltyHTML       = buildLoyaltyPanel(loyRes.data);
      ancillaryHTML     = buildAncillariesPanel(ancRes.data);
      personalisedHTML  = buildPersonalisedPanel(customer);
      visaHTML          = buildVisaPanel(
        mcp_data?.visa?.data || out.recommendations?.visa_full || null,
        customer?.profile?.name?.split(' ')[0] ? 'your' : 'Your',
        intent.destination || 'the destination'
      );
    } catch (e) {
      console.warn('Loyalty/ancillary fetch error:', e.message);
      personalisedHTML = buildPersonalisedPanel(customer);
    }
  }

  const html = _buildCard({
    out, conf, actionCheck, meta,
    intent, recs, dates, flight, hotel, transf, exps,
    total, budget,
    loyaltyHTML, ancillaryHTML, personalisedHTML,
    hasCustomer: !!cid,
  });

  appendCard(html);
}

// ── Tab switching (called from inline onclick) ────────────────

export function switchTab(tabEl, paneId) {
  const card = tabEl.closest('.icard');
  if (!card) return;
  $$('.itab',  card).forEach(t => t.classList.remove('active'));
  $$('.itab-pane', card).forEach(p => p.classList.remove('active'));
  tabEl.classList.add('active');
  card.querySelector(`#${paneId}`)?.classList.add('active');
}

// ── Private card builder ──────────────────────────────────────

function _buildCard(p) {
  const {
    out, conf, actionCheck, meta,
    intent, recs, dates, flight, hotel, transf, exps,
    total, budget,
    loyaltyHTML, ancillaryHTML, personalisedHTML,
    hasCustomer,
  } = p;

  const sc        = scoreColor;
  const isConfirm = actionCheck?.action === 'human_confirm';
  const ok        = total <= budget * 1.10;

  // Confidence signals strip
  const sigHtml = ['intent','rag','gds','hallucination','overall'].map(k => {
    const lb = { intent:'Intent', rag:'Memory', gds:'Booking',
                 hallucination:'Accuracy', overall:'Overall' }[k];
    const v  = conf[k] || 0;
    return `
      <div class="conf-sig">
        <span style="color:var(--muted);font-size:10px">${lb}</span>
        <div class="conf-bar">
          <div class="conf-fill" style="width:${v*100}%;background:${sc(v)}"></div>
        </div>
        <span class="conf-score" style="color:${sc(v)}">${pct(v)}</span>
      </div>`;
  }).join('');

  // Experiences list
  const expRows = exps.map(e => `
    <div style="display:flex;justify-content:space-between;padding:5px 0;
         border-bottom:1px solid var(--border);font-size:12px">
      <span>${e.name || ''}</span>
      <span style="color:var(--teal);font-family:var(--mono)">£${num(e.total_gbp)}</span>
    </div>
  `).join('');

  // Provider tag
  const pCls  = providerClass(meta.p);
  const pIcon = providerIcon(meta.p);
  const ptag  = `
    <div class="ptag ${pCls}">
      ${pIcon} ${(meta.p || 'demo').toUpperCase()}
      ${meta.m ? ` · ${meta.m.split('-').pop()}` : ''}
      ${meta.ms ? ` · ${meta.ms}ms` : ''}
      ${meta.cost > 0 ? ` · $${meta.cost.toFixed(4)}` : (meta.p !== 'demo' ? ' · FREE' : '')}
    </div>`;

  // Cost rows
  const fc = flight.price_gbp       || 0;
  const hc = hotel.total_price_gbp  || 0;
  const tc = transf.price_gbp       || 65;
  const ec = exps.reduce((s, e) => s + (e.total_gbp || 0), 0);

  return `
<div class="icard">
  <!-- Header -->
  <div class="ihead">
    <div>
      <div class="ititle">
        ✈ ${intent.destination || 'Your Trip'} ·
        ${dates.nights || 7} nights ·
        ${intent.guests || 2} guests
      </div>
      <div class="isub">${dates.departure_date || ''} → ${dates.return_date || ''}</div>
      ${ptag}
    </div>
    <div class="ibadge ${isConfirm ? 'confirm' : 'ready'}">
      ${isConfirm ? '⏳ CONFIRM' : '✓ READY'}
    </div>
  </div>

  <!-- Tabs -->
  <div class="itabs">
    <div class="itab active"
         onclick="window.VoyageApp.switchTab(this,'tp-overview')">📋 Overview</div>
    ${hasCustomer ? `<div class="itab"
         onclick="window.VoyageApp.switchTab(this,'tp-loyalty')">⭐ Loyalty</div>` : ''}
    ${hasCustomer ? `<div class="itab"
         onclick="window.VoyageApp.switchTab(this,'tp-extras')">🎁 Smart Extras</div>` : ''}
    ${hasCustomer ? `<div class="itab"
         onclick="window.VoyageApp.switchTab(this,'tp-foryou')">💡 For You</div>` : ''}
    <div class="itab"
         onclick="window.VoyageApp.switchTab(this,'tp-cost')">💷 Costs</div>
  </div>

  <!-- Overview pane -->
  <div class="itab-pane active" id="tp-overview">
    <div class="igrid">
      <div class="isec">
        <div class="slbl">✈ Best Flight</div>
        <div class="sval">
          <span class="hl">${flight.airline || 'TBC'}</span>
          ${flight.flight_number || ''}<br>
          ${flight.origin || 'LHR'} → ${flight.destination || '?'}
          ${flight.stops === 0 ? ' · Direct' : ''}
        </div>
        <div class="ssub">${fmtTime(flight.departure)} · ${flight.duration || ''}</div>
        <div class="ssub hla" style="margin-top:4px">
          £${num(fc)} total · £${num(flight.price_per_adult || fc / Math.max(1, intent.adults || 2))}/person
        </div>
        <div class="ssub">${flight.seats_available || 0} seats available</div>
      </div>

      <div class="isec">
        <div class="slbl">🏨 Hotel</div>
        <div class="sval">
          <span class="hl">${hotel.name || 'TBC'}</span><br>
          ${'⭐'.repeat(hotel.stars || 4)} · ${hotel.area || 'City Centre'}
        </div>
        <div class="tags">
          ${(hotel.amenities || []).map(a => `<span class="tag">${a}</span>`).join('')}
        </div>
        <div class="ssub hla" style="margin-top:6px">
          £${num(hotel.price_per_night)}/night · £${num(hc)} total
        </div>
      </div>

      <div class="isec">
        <div class="slbl">🌤 Travel Info</div>
        <div class="sval" style="font-size:12px;line-height:1.7">
          <strong style="color:var(--teal)">Weather:</strong><br>
          ${recs.weather_advisory || 'Check forecast closer to travel'}<br><br>
          <strong style="color:var(--teal)">Visa:</strong><br>
          ${recs.visa_advisory || 'Verify entry requirements'}<br><br>
          <strong style="color:var(--teal)">Currency:</strong><br>
          ${recs.currency_tip || ''}
        </div>
      </div>

      <div class="isec">
        <div class="slbl">⭐ Experiences</div>
        ${expRows || '<div style="font-size:12px;color:var(--muted)">No experiences found</div>'}
      </div>
    </div>

    <div class="conf-strip">
      <span class="conf-lbl">AI CONFIDENCE</span>
      <div class="conf-signals">${sigHtml}</div>
      <span style="font-size:11px;font-weight:600;color:${conf.overall >= .85 ? 'var(--green)' : 'var(--amber)'}">
        ${conf.overall >= .85 ? '✓ PASS' : '⚠ MARGINAL'}
      </span>
    </div>

    <div style="padding:10px 16px;background:var(--bg2);border-top:1px solid var(--border)">
      <div class="slbl">🧠 AI Reasoning</div>
      <div style="font-size:12px;color:var(--muted);line-height:1.55;margin-top:4px">
        ${out.reasoning || ''}
      </div>
    </div>
  </div>

  <!-- Loyalty pane -->
  ${hasCustomer ? `<div class="itab-pane" id="tp-loyalty">${loyaltyHTML}</div>` : ''}

  <!-- Extras pane -->
  ${hasCustomer ? `<div class="itab-pane" id="tp-extras">${ancillaryHTML}</div>` : ''}

  <!-- For You pane -->
  ${hasCustomer ? `<div class="itab-pane" id="tp-foryou">${personalisedHTML}</div>` : ''}

  <!-- Visa pane -->
  <div class="itab-pane" id="tp-visa">${visaHTML}</div>

  <!-- Cost pane -->
  <div class="itab-pane" id="tp-cost">
    <div style="padding:14px 16px">
      <div class="slbl" style="margin-bottom:9px">💷 Full Cost Breakdown</div>
      <div class="cost-row">
        <span class="cost-lbl">Flights (${intent.guests || 2} guests)</span>
        <span class="cost-val">£${num(fc)}</span>
      </div>
      <div class="cost-row">
        <span class="cost-lbl">Hotel (${dates.nights || 7} nights)</span>
        <span class="cost-val">£${num(hc)}</span>
      </div>
      <div class="cost-row">
        <span class="cost-lbl">Airport Transfer</span>
        <span class="cost-val">£${num(tc)}</span>
      </div>
      ${ec > 0 ? `
      <div class="cost-row">
        <span class="cost-lbl">Experiences (${exps.length})</span>
        <span class="cost-val">£${num(ec)}</span>
      </div>` : ''}
      <div class="cost-row" id="selAncRow-${Date.now()}" style="display:none">
        <span class="cost-lbl">Selected Extras</span>
        <span class="cost-val" id="selAncTotal">£0</span>
      </div>
      <div class="cost-total">
        <span>Total</span>
        <span class="cost-val" id="grandTotal">£${num(total)}</span>
      </div>
      <div style="font-size:12px;margin-top:5px;color:${ok ? 'var(--green)' : 'var(--amber)'}">
        ${ok
          ? `✓ Within your £${num(budget)} budget`
          : `⚠ £${num(total - budget)} over budget`}
      </div>
    </div>
  </div>

  <!-- Confirm section -->
  <div class="confirm-sec">
    ${isConfirm
      ? `<div class="conf-notice">
           ⚡ High-value booking £${num(total)} — your confirmation required
         </div>`
      : ''}
    <button class="btn btn-ok"  onclick="window.VoyageApp.confirmEl('flight')">✓ Confirm Flight</button>
    <button class="btn btn-ok"  onclick="window.VoyageApp.confirmEl('hotel')">✓ Confirm Hotel</button>
    <button class="btn btn-mod" onclick="window.VoyageApp.modifyTrip()">✏ Modify</button>
    <button class="btn btn-no"  onclick="window.VoyageApp.cancelBooking()">✕ Cancel</button>
  </div>
</div>`;
}
