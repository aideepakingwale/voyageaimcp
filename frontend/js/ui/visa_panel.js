/**
 * Visa & Travel Compliance Panel
 * Renders the AI-generated visa requirements in a structured,
 * easy-to-read format with clear action items.
 */

/**
 * Build full visa compliance panel HTML from AI response data.
 * @param {object} visaData - full visa MCP response data object
 * @param {string} passportName - e.g. "United Kingdom"
 * @param {string} destName - e.g. "Portugal"
 * @returns {string} HTML string
 */
export function buildVisaPanel(visaData, passportName, destName) {
  if (!visaData) {
    return `<div style="padding:16px;color:var(--muted)">
      Visa information not available. 
      <a href="https://www.gov.uk/foreign-travel-advice" target="_blank" 
         style="color:var(--teal)">Check FCDO advice →</a>
    </div>`;
  }

  const entryBadge  = _entryBadge(visaData);
  const reqsList    = _requirementsList(visaData.requirements || []);
  const healthList  = _healthList(visaData.health_requirements || []);
  const warningsList= _warningsList(visaData.travel_warnings || []);
  const actionCard  = _actionCard(visaData);
  const contacts    = _contacts(visaData);

  const confScore = visaData.compliance_score || 0.7;
  const confColor = confScore >= 0.85 ? 'var(--green)'
                  : confScore >= 0.70 ? 'var(--amber)'
                  : 'var(--red)';

  return `
<div style="padding:16px;display:flex;flex-direction:column;gap:12px">

  <!-- AI Badge -->
  <div style="display:flex;align-items:center;gap:8px;
       background:rgba(155,89,182,.1);border:1px solid rgba(155,89,182,.3);
       border-radius:10px;padding:9px 14px">
    <span style="font-size:16px">🤖</span>
    <div>
      <div style="font-size:12px;font-weight:700;color:var(--purple)">
        AI-Powered Compliance Check
      </div>
      <div style="font-size:11px;color:var(--muted)">
        ${passportName} passport → ${destName} ·
        Confidence: <span style="color:${confColor}">${Math.round(confScore*100)}%</span>
      </div>
    </div>
  </div>

  <!-- Entry Status -->
  <div style="background:var(--bg2);border:1px solid var(--border);
       border-radius:10px;padding:14px">
    <div style="display:flex;align-items:center;justify-content:space-between;
         margin-bottom:8px">
      <div class="slbl">Entry Requirement</div>
      ${entryBadge}
    </div>
    <div style="font-size:13px;line-height:1.6;color:var(--text)">
      ${visaData.summary || ''}
    </div>
    ${visaData.max_stay_days ? `
    <div style="margin-top:8px;font-size:12px;color:var(--muted)">
      📅 Maximum stay: <strong style="color:var(--text)">${visaData.max_stay_days} days</strong>
    </div>` : ''}
    ${visaData.passport_validity ? `
    <div style="font-size:12px;color:var(--muted);margin-top:4px">
      📘 Passport validity: <strong style="color:var(--text)">${visaData.passport_validity}</strong>
    </div>` : ''}
  </div>

  <!-- Action card (apply, cost, timing) -->
  ${actionCard}

  <!-- Requirements checklist -->
  ${reqsList}

  <!-- Health requirements -->
  ${healthList}

  <!-- Travel warnings -->
  ${warningsList}

  <!-- Currency tip -->
  ${visaData.currency_tip ? `
  <div style="background:rgba(243,156,18,.08);border:1px solid rgba(243,156,18,.25);
       border-radius:10px;padding:12px 14px;font-size:12px">
    <div style="font-weight:700;color:var(--amber);margin-bottom:4px">💱 Currency & Money</div>
    <div style="color:var(--muted)">${visaData.currency_tip}</div>
  </div>` : ''}

  <!-- Emergency contacts + official links -->
  ${contacts}

  <!-- Disclaimer -->
  <div style="background:rgba(61,90,107,.2);border-radius:10px;
       padding:10px 14px;font-size:11px;color:var(--dim);line-height:1.5">
    ${visaData.disclaimer || '⚠️ Always verify entry requirements with official sources before booking.'}
  </div>

</div>`;
}

// ── Private builders ──────────────────────────────────────────

function _entryBadge(d) {
  const configs = {
    'visa_free':      { icon:'✅', label:'Visa Free',       color:'var(--green)',  bg:'rgba(39,174,96,.15)' },
    'eta_required':   { icon:'⚡', label:'ETA Required',    color:'var(--amber)',  bg:'rgba(243,156,18,.15)' },
    'evisa_required': { icon:'💻', label:'eVisa Required',  color:'var(--amber)',  bg:'rgba(243,156,18,.15)' },
    'visa_on_arrival':{ icon:'✈️', label:'Visa on Arrival', color:'var(--blue)',   bg:'rgba(59,170,219,.15)' },
    'embassy_visa':   { icon:'🏛️', label:'Embassy Visa',   color:'var(--red)',    bg:'rgba(231,76,60,.15)' },
    'unknown':        { icon:'❓', label:'Check Required',  color:'var(--muted)',  bg:'var(--bg3)' },
  };
  const c = configs[d.entry_type] || configs['unknown'];
  return `<span style="font-size:11px;font-weight:700;padding:4px 12px;
    border-radius:20px;background:${c.bg};color:${c.color};border:1px solid ${c.color}">
    ${c.icon} ${c.label}
  </span>`;
}

function _actionCard(d) {
  if (!d.cost && !d.apply_url && !d.processing_time) return '';
  const rows = [];
  if (d.cost)            rows.push(`<div class="v-row"><span>Cost</span><strong>${d.cost}</strong></div>`);
  if (d.processing_time) rows.push(`<div class="v-row"><span>Processing</span><strong>${d.processing_time}</strong></div>`);
  if (d.apply_url) {
    rows.push(`<div class="v-row"><span>Apply at</span>
      <a href="${d.apply_url}" target="_blank" rel="noopener"
         style="color:var(--teal);font-size:12px">Official site →</a></div>`);
  }
  return rows.length ? `
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden">
    <div style="padding:10px 14px;background:rgba(0,201,167,.06);
         border-bottom:1px solid var(--border);font-size:11px;font-weight:700;
         color:var(--teal);letter-spacing:1px">ACTION REQUIRED</div>
    <div style="padding:10px 14px">${rows.join('')}</div>
  </div>` : '';
}

function _requirementsList(reqs) {
  if (!reqs.length) return '';
  const items = reqs.map(r => `
    <div style="display:flex;align-items:flex-start;gap:8px;
         padding:7px 0;border-bottom:1px solid var(--border);font-size:12px">
      <span style="color:var(--teal);flex-shrink:0">✓</span>
      <span style="color:var(--muted)">${r}</span>
    </div>`).join('');
  return `
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden">
    <div style="padding:10px 14px;border-bottom:1px solid var(--border);
         font-size:11px;font-weight:700;color:var(--muted);letter-spacing:1px">
      📋 REQUIREMENTS CHECKLIST
    </div>
    <div style="padding:6px 14px">${items}</div>
  </div>`;
}

function _healthList(health) {
  if (!health.length) return '';
  const items = health.map(h => `
    <div style="display:flex;gap:8px;padding:6px 0;
         border-bottom:1px solid var(--border);font-size:12px">
      <span style="flex-shrink:0">💉</span>
      <span style="color:var(--muted)">${h}</span>
    </div>`).join('');
  return `
  <div style="background:rgba(231,76,60,.06);border:1px solid rgba(231,76,60,.2);
       border-radius:10px;overflow:hidden">
    <div style="padding:10px 14px;border-bottom:1px solid rgba(231,76,60,.2);
         font-size:11px;font-weight:700;color:var(--red);letter-spacing:1px">
      🏥 HEALTH REQUIREMENTS
    </div>
    <div style="padding:6px 14px">${items}</div>
  </div>`;
}

function _warningsList(warnings) {
  if (!warnings.length) return '';
  const items = warnings.map(w => `
    <div style="display:flex;gap:8px;padding:7px 0;
         border-bottom:1px solid rgba(243,156,18,.2);font-size:12px">
      <span style="flex-shrink:0">⚠️</span>
      <span style="color:var(--muted)">${w}</span>
    </div>`).join('');
  return `
  <div style="background:rgba(243,156,18,.08);border:1px solid rgba(243,156,18,.25);
       border-radius:10px;overflow:hidden">
    <div style="padding:10px 14px;border-bottom:1px solid rgba(243,156,18,.25);
         font-size:11px;font-weight:700;color:var(--amber);letter-spacing:1px">
      ⚠️ TRAVEL ADVISORIES
    </div>
    <div style="padding:6px 14px">${items}</div>
  </div>`;
}

function _contacts(d) {
  const links = [];
  if (d.official_advice_url) {
    links.push(`<a href="${d.official_advice_url}" target="_blank" rel="noopener"
      style="color:var(--teal);font-size:12px">🏛️ Official Travel Advice →</a>`);
  }
  if (d.iata_travel_centre) {
    links.push(`<a href="${d.iata_travel_centre}" target="_blank" rel="noopener"
      style="color:var(--blue);font-size:12px">✈️ IATA Travel Centre →</a>`);
  }
  if (d.apply_url) {
    links.push(`<a href="${d.apply_url}" target="_blank" rel="noopener"
      style="color:var(--amber);font-size:12px">📝 Apply for Entry Document →</a>`);
  }
  if (!links.length) return '';
  return `<div style="display:flex;flex-wrap:wrap;gap:10px;padding:4px 0">${links.join('')}</div>`;
}
