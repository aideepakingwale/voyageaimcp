/**
 * Itinerary Card UI Module
 * Builds the tabbed itinerary card HTML and enriches it with loyalty,
 * ancillaries, and provider/source visibility.
 */
import { $$ }                             from '../utils/dom.js';
import {
  num, pct, scoreColor, fmtTime,
  providerClass, providerIcon,
}                                          from '../utils/format.js';
import { appendCard }                      from './chat.js';
import { buildLoyaltyPanel }               from './loyalty.js';
import { buildAncillariesPanel }           from './ancillaries.js';
import { buildPersonalisedPanel }          from './personalised.js';
import { buildVisaPanel }                  from './visa_panel.js';
import { clearAncillaries, getCurrentCustomer, setCurrentItinerary } from '../state.js';
import * as api                            from '../api.js';

export async function renderItineraryCard(out, conf, actionCheck, meta, rawData = {}) {
  clearAncillaries();
  setCurrentItinerary(out);
  const mcpData = rawData.mcp_data || {};

  const customer = getCurrentCustomer();
  const cid = customer?.profile?.id;
  const intent = out.intent || {};
  const recs = out.recommendations || {};
  const dates = intent.dates || {};

  const liveFlights = mcpData?.flights?.data?.flights || [];
  const liveHotels = mcpData?.hotels?.data?.hotels || [];
  const flight = pickRichestOption((recs.flights || [])[0], liveFlights[0]);
  const hotel = pickRichestOption((recs.hotels || [])[0], liveHotels[0]);
  const transf = (recs.transfers || [])[0] || {};
  const exps = (recs.experiences || []).slice(0, 3);
  const total = out.total_cost_gbp || 0;
  const budget = intent.budget_gbp || 9999;

  let loyaltyHTML = '';
  let ancillaryHTML = '';
  let personalisedHTML = '';
  let visaHTML = '';

  if (cid) {
    try {
      const [loyRes, ancRes] = await Promise.all([
        api.getLoyalty(cid, total, dates.nights || 7, 1),
        api.getAncillaries({
          city_code: intent.city_code || 'LIS',
          departure_date: dates.departure_date || '',
          arrival_time: flight?.outbound?.arrival || flight?.arrival || '',
          guests: intent.guests || 2,
          adults: intent.adults || 2,
          children: intent.children || 0,
          trip_type: intent.trip_type || 'leisure',
          interests: customer.interests?.top || [],
          loyalty_tier: customer.loyalty?.current_tier || 'Blue',
          nights: dates.nights || 7,
          hotel_stars: hotel.stars || 4,
          budget_gbp: budget,
          trip_cost_so_far: total,
        }),
      ]);

      loyaltyHTML = buildLoyaltyPanel(loyRes.data);
      ancillaryHTML = buildAncillariesPanel(ancRes.data);
      personalisedHTML = buildPersonalisedPanel(customer);
    } catch (e) {
      console.warn('Loyalty/ancillary fetch error:', e.message);
      personalisedHTML = buildPersonalisedPanel(customer);
    }
  }

  try {
    const visaSource = mcpData?.visa?.data ?? null;
    const visaPassport = customer?.profile?.name
      ? `${customer.profile.name.split(' ')[0]}'s passport`
      : 'Your passport';
    visaHTML = buildVisaPanel(
      visaSource,
      visaPassport,
      intent.destination || 'your destination'
    );
  } catch {
    visaHTML = '';
  }

  if (!out.loyalty_benefits) out.loyalty_benefits = [];
  if (!out.recommendations) out.recommendations = {};
  if (!out.recommendations.flights) out.recommendations.flights = [];
  if (!out.recommendations.hotels) out.recommendations.hotels = [];
  if (!out.recommendations.experiences) out.recommendations.experiences = [];

  appendCard(buildCard({
    out, conf, actionCheck, meta,
    intent, recs, dates, flight, hotel, transf, exps,
    total, budget,
    loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML,
    rawData, hasCustomer: !!cid,
  }));
}

export function switchTab(tabEl, paneId) {
  const card = tabEl.closest('.icard');
  if (!card) return;
  $$('.itab', card).forEach(t => t.classList.remove('active'));
  $$('.itab-pane', card).forEach(p => p.classList.remove('active'));
  tabEl.classList.add('active');
  card.querySelector(`#${paneId}`)?.classList.add('active');
}

function buildCard(p) {
  const {
    out, conf, actionCheck, meta,
    intent, recs, dates, flight, hotel, exps,
    total, budget,
    loyaltyHTML, ancillaryHTML, personalisedHTML,
    visaHTML = '', rawData = {}, hasCustomer,
  } = p;

  const isConfirm = actionCheck?.action === 'human_confirm';
  const withinBudget = total <= budget * 1.1;
  const flightCost = flight.price_gbp || 0;
  const hotelCost = hotel.total_price_gbp || 0;
  const transferCost = (recs.transfers || [])[0]?.price_gbp || 65;
  const expCost = exps.reduce((sum, e) => sum + (e.total_gbp || 0), 0);
  const sourceStrip = buildSourceStrip(rawData?.mcp_data || {}, flight, hotel);

  const sigHtml = ['intent', 'rag', 'gds', 'hallucination', 'overall'].map(key => {
    const label = {
      intent: 'Intent',
      rag: 'Memory',
      gds: 'Booking',
      hallucination: 'Accuracy',
      overall: 'Overall',
    }[key];
    const v = conf[key] || 0;
    return `
      <div class="conf-sig">
        <span style="color:var(--muted);font-size:10px">${label}</span>
        <div class="conf-bar">
          <div class="conf-fill" style="width:${v * 100}%;background:${scoreColor(v)}"></div>
        </div>
        <span class="conf-score" style="color:${scoreColor(v)}">${pct(v)}</span>
      </div>`;
  }).join('');

  const expRows = exps.map(e => `
    <div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px">
      <span>${e.name || ''}</span>
      <span style="color:var(--teal);font-family:var(--mono)}">GBP ${num(e.total_gbp)}</span>
    </div>
  `).join('');

  const pCls = providerClass(meta.p);
  const pIcon = providerIcon(meta.p);
  const providerTag = `
    <div class="ptag ${pCls}">
      ${pIcon} ${(meta.p || 'demo').toUpperCase()}
      ${meta.m ? ` · ${meta.m.split('-').pop()}` : ''}
      ${meta.ms ? ` · ${meta.ms}ms` : ''}
      ${meta.cost > 0 ? ` · $${meta.cost.toFixed(4)}` : (meta.p !== 'demo' ? ' · FREE' : '')}
    </div>`;

  return `
<div class="icard">
  <div class="ihead">
    <div>
      <div class="ititle">
        Flight package · ${intent.destination || 'Your Trip'} · ${dates.nights || 7} nights · ${intent.guests || 2} guests
      </div>
      <div class="isub">${dates.departure_date || ''} → ${dates.return_date || ''}</div>
      ${providerTag}
      ${sourceStrip}
    </div>
    <div class="ibadge ${isConfirm ? 'confirm' : 'ready'}">
      ${isConfirm ? 'PENDING CONFIRMATION' : 'READY'}
    </div>
  </div>

  <div class="itabs">
    <div class="itab active" onclick="window.VoyageApp.switchTab(this,'tp-overview')">Overview</div>
    ${hasCustomer ? `<div class="itab" onclick="window.VoyageApp.switchTab(this,'tp-loyalty')">Loyalty</div>` : ''}
    ${hasCustomer ? `<div class="itab" onclick="window.VoyageApp.switchTab(this,'tp-extras')">Smart Extras</div>` : ''}
    ${hasCustomer ? `<div class="itab" onclick="window.VoyageApp.switchTab(this,'tp-foryou')">For You</div>` : ''}
    <div class="itab" onclick="window.VoyageApp.switchTab(this,'tp-visa')">Visa</div>
    <div class="itab" onclick="window.VoyageApp.switchTab(this,'tp-cost')">Costs</div>
  </div>

  <div class="itab-pane active" id="tp-overview">
    <div class="igrid">
      <div class="isec">
        <div class="slbl">Best Flight</div>
        ${buildFlightPanel(flight, intent)}
        <div class="ssub hla" style="margin-top:8px">
          GBP ${num(flightCost)} total · GBP ${num(flight.price_per_adult || flightCost / Math.max(1, intent.adults || 2))}/person
        </div>
        <div class="ssub">${flight.seats_available || 0} seats available</div>
      </div>

      <div class="isec">
        <div class="slbl">Hotel</div>
        <div class="sval">
          <span class="hl">${hotel.name || 'TBC'}</span><br>
          ${'★'.repeat(hotel.stars || 4)} · ${hotel.area || hotel.location || 'City centre'}
        </div>
        <div class="tags">
          ${(hotel.amenities || []).map(a => `<span class="tag">${a}</span>`).join('')}
        </div>
        ${sourceBadge(hotel.source || rawData?.mcp_data?.hotels?.data?.source || '', 'Hotel')}
        <div class="ssub hla" style="margin-top:6px">
          GBP ${num(hotel.price_per_night)} / night · GBP ${num(hotelCost)} total
        </div>
      </div>

      <div class="isec">
        <div class="slbl">Travel Info</div>
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
        <div class="slbl">Experiences</div>
        ${expRows || '<div style="font-size:12px;color:var(--muted)">No experiences found</div>'}
      </div>
    </div>

    <div class="conf-strip">
      <span class="conf-lbl">AI CONFIDENCE</span>
      <div class="conf-signals">${sigHtml}</div>
      <span style="font-size:11px;font-weight:600;color:${conf.overall >= 0.85 ? 'var(--green)' : 'var(--amber)'}">
        ${conf.overall >= 0.85 ? 'PASS' : 'MARGINAL'}
      </span>
    </div>

    <div style="padding:10px 16px;background:var(--bg2);border-top:1px solid var(--border)">
      <div class="slbl">AI Reasoning</div>
      <div style="font-size:12px;color:var(--muted);line-height:1.55;margin-top:4px">
        ${out.reasoning || ''}
      </div>
    </div>
  </div>

  ${hasCustomer ? `<div class="itab-pane" id="tp-loyalty">${loyaltyHTML}</div>` : ''}
  ${hasCustomer ? `<div class="itab-pane" id="tp-extras">${ancillaryHTML}</div>` : ''}
  ${hasCustomer ? `<div class="itab-pane" id="tp-foryou">${personalisedHTML}</div>` : ''}
  <div class="itab-pane" id="tp-visa">${visaHTML}</div>

  <div class="itab-pane" id="tp-cost">
    <div style="padding:14px 16px">
      <div class="slbl" style="margin-bottom:9px">Full Cost Breakdown</div>
      <div class="cost-row">
        <span class="cost-lbl">Flights (${intent.guests || 2} guests)</span>
        <span class="cost-val">GBP ${num(flightCost)}</span>
      </div>
      <div class="cost-row">
        <span class="cost-lbl">Hotel (${dates.nights || 7} nights)</span>
        <span class="cost-val">GBP ${num(hotelCost)}</span>
      </div>
      <div class="cost-row">
        <span class="cost-lbl">Airport Transfer</span>
        <span class="cost-val">GBP ${num(transferCost)}</span>
      </div>
      ${expCost > 0 ? `
      <div class="cost-row">
        <span class="cost-lbl">Experiences (${exps.length})</span>
        <span class="cost-val">GBP ${num(expCost)}</span>
      </div>` : ''}
      <div class="cost-row" data-selected-anc-row style="display:none">
        <span class="cost-lbl">Selected Extras</span>
        <span class="cost-val" data-selected-anc-total>GBP 0</span>
      </div>
      <div class="cost-total">
        <span>Total</span>
        <span class="cost-val" data-grand-total data-base-total="${Number(total) || 0}">GBP ${num(total)}</span>
      </div>
      <div style="font-size:12px;margin-top:5px;color:${withinBudget ? 'var(--green)' : 'var(--amber)'}">
        ${withinBudget ? `Within your GBP ${num(budget)} budget` : `GBP ${num(total - budget)} over budget`}
      </div>
    </div>
  </div>

  <div class="confirm-sec">
    ${isConfirm ? `<div class="conf-notice">High-value booking GBP ${num(total)} - your confirmation required</div>` : ''}
    <button class="btn btn-ok" onclick="window.VoyageApp.confirmPackage()">Confirm Package</button>
    <button class="btn btn-ok" onclick="window.VoyageApp.confirmEl('flight')">Confirm Flight</button>
    <button class="btn btn-ok" onclick="window.VoyageApp.confirmEl('hotel')">Confirm Hotel</button>
    <button class="btn btn-mod" onclick="window.VoyageApp.modifyTrip()">Modify</button>
    <button class="btn btn-no" onclick="window.VoyageApp.cancelBooking()">Cancel</button>
  </div>
</div>`;
}

function pickRichestOption(primary = {}, fallback = {}) {
  const p = primary || {};
  const f = fallback || {};
  const pScore = Object.keys(p).length + (p.outbound ? 4 : 0) + (p.inbound ? 4 : 0);
  const fScore = Object.keys(f).length + (f.outbound ? 4 : 0) + (f.inbound ? 4 : 0);
  return fScore > pScore ? f : p;
}

function buildSourceStrip(mcpData, flight, hotel) {
  const items = [
    ['Flights', flight?.source || mcpData?.flights?.data?.source || ''],
    ['Hotels', hotel?.source || mcpData?.hotels?.data?.source || ''],
    ['Weather', mcpData?.weather?.data?.source || ''],
    ['Currency', mcpData?.currency?.data?.source || ''],
  ].filter(([, source]) => source);

  if (!items.length) return '';

  return `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
    ${items.map(([label, source]) => sourceBadge(source, label)).join('')}
  </div>`;
}

function sourceBadge(source, label = '') {
  if (!source) return '';
  const isLive = /live/i.test(source);
  const tone = isLive ? 'var(--green)' : 'var(--amber)';
  const text = isLive ? 'Live API' : 'Fallback/dummy';
  return `<span style="display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:999px;border:1px solid ${tone};color:${tone};font-size:11px;margin-top:6px">
    ${label ? `${label}: ` : ''}${text}
  </span>`;
}

function buildFlightPanel(flight) {
  if (!flight || !Object.keys(flight).length) {
    return `<div class="sval"><span class="hl">TBC</span></div>`;
  }

  const outbound = flight.outbound || buildLegacyLeg(flight);
  const inbound = flight.inbound || null;
  const routeLabel = inbound ? 'Return flight included' : 'Outbound only';

  return `
    <div class="sval">
      <span class="hl">${flight.airline || outbound.primary_airline || 'TBC'}</span>
      ${flight.flight_number || outbound.primary_flight_number || ''}<br>
      <span style="font-size:12px;color:var(--muted)">${routeLabel}</span>
    </div>
    <div style="margin-top:8px">${buildFlightLeg('Outbound', outbound)}</div>
    ${inbound ? `<div style="margin-top:10px">${buildFlightLeg('Inbound', inbound)}</div>` : ''}
    ${sourceBadge(flight.source || '', 'Flight')}
  `;
}

function buildLegacyLeg(flight) {
  return {
    origin: flight.origin || 'LHR',
    destination: flight.destination || '?',
    departure: flight.departure || '',
    arrival: flight.arrival || '',
    duration: flight.duration || '',
    stops: Number.isFinite(flight.stops) ? flight.stops : 0,
    is_direct: (flight.stops || 0) === 0,
    layovers: flight.layovers || [],
    segments: flight.segments || [],
    primary_airline: flight.airline || '',
    primary_flight_number: flight.flight_number || '',
  };
}

function buildFlightLeg(label, leg) {
  const stops = Number(leg?.stops || 0);
  const stopLabel = stops === 0 ? 'Direct' : `${stops} stop${stops > 1 ? 's' : ''}`;
  const segmentLines = (leg?.segments || []).slice(0, 4).map(seg => `
    <div class="ssub">${seg.origin} → ${seg.destination} · ${seg.flight_number || seg.airline || ''} · ${fmtTime(seg.departure)}-${fmtTime(seg.arrival)}</div>
  `).join('');
  const layovers = (leg?.layovers || []).map(item => `
    <div class="ssub">Wait at ${item.airport}: ${item.duration}</div>
  `).join('');

  return `
    <div style="padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg2)">
      <div class="slbl" style="margin-bottom:4px">${label}</div>
      <div class="ssub"><strong>${leg.origin || '?'} → ${leg.destination || '?'}</strong> · ${stopLabel}</div>
      <div class="ssub">${fmtTime(leg.departure)} → ${fmtTime(leg.arrival)} · ${leg.duration || ''}</div>
      ${segmentLines}
      ${layovers}
    </div>
  `;
}
