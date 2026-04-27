/**
 * Formatting utilities — pure functions, no DOM side-effects.
 * Import these into any module that needs display formatting.
 */

/** Format a number as integer with £ prefix */
export function money(v) {
  return `£${v ? parseFloat(v).toFixed(0) : '0'}`;
}

/** Format a raw number to integer string */
export function num(v) {
  return v ? parseFloat(v).toFixed(0) : '0';
}

/** Format a float as percentage string */
export function pct(v) {
  return `${Math.round((v || 0) * 100)}%`;
}

/** Capitalise first letter */
export function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

/** HTML-escape a string */
export function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Format ISO datetime to HH:MM */
export function fmtTime(dt) {
  if (!dt) return '';
  try {
    return new Date(dt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return dt;
  }
}

/** Return colour for a 0–1 confidence score */
export function scoreColor(v) {
  if (v >= 0.85) return 'var(--green)';
  if (v >= 0.70) return 'var(--amber)';
  return 'var(--red)';
}

/** Return emoji icon for a loyalty tier */
export function tierIcon(tier) {
  return { Blue: '🔵', Silver: '🥈', Gold: '🥇', Platinum: '💎' }[tier] || '🔵';
}

/** Return emoji icon for an ancillary category */
export function catIcon(cat) {
  return {
    room_upgrade: '🏨',
    transfer:     '🚗',
    insurance:    '🛡️',
    experience:   '🎭',
    equipment:    '🎒',
  }[cat] || '🎁';
}

/** Return emoji icon for a destination name */
export function destIcon(dest) {
  const map = {
    Maldives: '🏝️', Lisbon: '🏰', Barcelona: '🎨', Paris: '🗼',
    Rome: '🏛️', Tokyo: '⛩️', Bali: '🌴', Dubai: '🌆',
    'New York': '🗽', Santorini: '💎', Florence: '🎭',
    'Amalfi Coast': '🚢', Tuscany: '🍷', Iceland: '❄️',
    'Costa Rica': '🦜', Seychelles: '🐠', Mauritius: '🌊',
    Athens: '🏛️', Kyoto: '⛩️', Istanbul: '🕌', Prague: '🏰',
  };
  return map[dest] || '✈️';
}

/** Return CSS class suffix for an LLM provider name */
export function providerClass(provider) {
  return `pt-${(provider || 'demo').toLowerCase()}`;
}

/** Return emoji for a provider */
export function providerIcon(provider) {
  return { groq: '⚡', gemini: '🔷', anthropic: '🟣', template: '🔧', demo: '🎭' }[provider] || '🤖';
}
