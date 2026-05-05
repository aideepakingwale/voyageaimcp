/**
 * Ancillaries Panel UI Module
 * Builds the Smart Extras content with selectable cards.
 */
import { catIcon, num } from '../utils/format.js';
import { getSelectedAncillaries } from '../state.js';

export function buildAncillariesPanel(data) {
  if (!data || !data.ancillaries?.length) {
    return '<div style="padding:16px;color:var(--muted)">No smart extras for this trip context.</div>';
  }

  return `
    <div style="padding-bottom:8px">
      <div class="slbl" style="margin-bottom:8px">Why We Recommend These</div>
      ${buildNarratives(data.narratives || [])}
    </div>
    <div class="slbl">Available Extras</div>
    <div class="anc-grid">${buildCards(data.ancillaries.slice(0, 8))}</div>
    <div style="margin-top:12px;font-size:12px;color:var(--muted)">
      Tap any card to add it to your booking total and package confirmation.
    </div>
  `;
}

function buildNarratives(items) {
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

function buildCards(items) {
  const selected = getSelectedAncillaries();
  return items.map(a => {
    const reason = (a.reasons || [])[0] || a.description || '';
    const isSelected = selected.has(a.id);
    return `
      <div class="anc-card ${a.must_have ? 'must-have' : ''} ${isSelected ? 'selected' : ''}"
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
            <span class="anc-price">GBP ${num(a.price_gbp)}</span>
            ${a.loyalty_discounted ? '<span class="anc-discount">member price</span>' : ''}
          </div>
          <div class="anc-check" id="ancc-${a.id}" style="${isSelected ? 'background:var(--teal);' : ''}">OK</div>
        </div>
      </div>
    `;
  }).join('');
}
