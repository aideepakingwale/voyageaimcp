/**
 * Ancillaries Panel UI Module
 * Builds the Smart Extras tab content — narratives + selectable cards.
 * Emits 'ancillaryToggled' custom event when a card is clicked.
 */
import { catIcon, num } from '../utils/format.js';

/**
 * Build the full ancillaries panel HTML.
 * @param {object} data — response.data from /api/ancillaries
 * @returns {string}    — HTML string
 */
export function buildAncillariesPanel(data) {
  if (!data || !data.ancillaries?.length) {
    return '<div style="padding:16px;color:var(--muted)">No smart extras for this trip context.</div>';
  }

  return `
    <div style="padding-bottom:8px">
      <div class="slbl" style="margin-bottom:8px">🧠 Why We Recommend These</div>
      ${_narratives(data.narratives || [])}
    </div>
    <div class="slbl">🎁 Available Extras</div>
    <div class="anc-grid">${_cards(data.ancillaries.slice(0, 8))}</div>
    <div style="margin-top:12px;font-size:12px;color:var(--muted)">
      Tap any card to add it to your booking total.
    </div>
  `;
}

// ── Private builders ──────────────────────────────────────────

function _narratives(items) {
  if (!items.length) return '';
  return items.map(n => `
    <div class="anc-narrative">
      <div class="anc-n-icon">${n.icon}</div>
      <div>
        <div class="anc-n-title">${n.title}</div>
        <div class="anc-n-text">${n.text}</div>
      </div>
    </div>
  `).join('');
}

function _cards(items) {
  return items.map(a => {
    const reason = (a.reasons || [])[0] || a.description || '';
    return `
      <div class="anc-card ${a.must_have ? 'must-have' : ''}"
           id="anc-${a.id}"
           data-id="${a.id}"
           data-price="${a.price_gbp}"
           data-name="${a.name}"
           onclick="window.VoyageApp.toggleAncillary('${a.id}', '${a.name}', ${a.price_gbp})">
        ${a.must_have ? '<div class="anc-must-label">RECOMMENDED</div>' : ''}
        <div class="anc-icon">${catIcon(a.category)}</div>
        <div class="anc-name">${a.name}</div>
        <div class="anc-reason">${reason}</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <span class="anc-price">£${num(a.price_gbp)}</span>
            ${a.loyalty_discounted
              ? '<span class="anc-discount">⭐ member price</span>'
              : ''}
          </div>
          <div class="anc-check" id="ancc-${a.id}">✓</div>
        </div>
      </div>
    `;
  }).join('');
}
