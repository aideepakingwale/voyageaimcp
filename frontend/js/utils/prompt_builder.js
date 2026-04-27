/**
 * Personalised Prompt Builder
 * Constructs rich, contextual prompts for recommendation clicks
 * so every suggested destination gets a genuinely personalised response.
 */

/**
 * Build a rich prompt for a recommended destination.
 * Embeds customer preferences, travel history, loyalty tier,
 * and the specific reason this destination was recommended.
 *
 * @param {string} destination - e.g. "Athens"
 * @param {object} recommendation - { reason, match_score } from API
 * @param {object} customer - full customer state object
 * @returns {string} - complete prompt ready to send to the LLM
 */
export function buildRecommendationPrompt(destination, recommendation, customer) {
  if (!customer?.profile) {
    return `Plan a trip to ${destination} for me.`;
  }

  const profile   = customer.profile;
  const loyalty   = customer.loyalty   || {};
  const interests = customer.interests || {};
  const patterns  = customer.patterns  || {};
  const history   = customer.history   || [];

  // Build context lines
  const lines = [];

  // 1 — Who is travelling
  const adults   = profile.adults_in_family   || 2;
  const children = profile.children_in_family || 0;
  const guestDesc = _guestDescription(adults, children);
  lines.push(`Plan a trip to ${destination} for ${guestDesc}.`);

  // 2 — Why this destination was recommended
  if (recommendation?.reason) {
    lines.push(`This destination was recommended because: ${recommendation.reason}.`);
  }

  // 3 — Budget context from patterns
  if (patterns.avg_spend_per_trip_gbp) {
    const budget = Math.round(patterns.avg_spend_per_trip_gbp);
    lines.push(`My typical trip budget is around £${budget.toLocaleString()}.`);
  }

  // 4 — Travel style and top interests
  const topInterests = (interests.top || []).slice(0, 5);
  if (topInterests.length > 0) {
    lines.push(`My travel interests include: ${topInterests.join(', ')}.`);
  }
  if (profile.travel_style) {
    lines.push(`I am a ${profile.travel_style} traveller.`);
  }

  // 5 — Preferred travel month
  if (patterns.preferred_travel_month) {
    lines.push(`I usually travel in ${patterns.preferred_travel_month} — suggest dates around that time.`);
  }

  // 6 — Hotel preferences from history
  const starPref = _preferredStars(history);
  if (starPref) {
    lines.push(`I prefer ${starPref}★ hotels or above.`);
  }

  // 7 — Ancillary preferences from past trips
  const ancPrefs = _commonAncillaries(history);
  if (ancPrefs.length > 0) {
    lines.push(`In the past I've usually booked: ${ancPrefs.join(', ')}.`);
  }

  // 8 — What NOT to repeat (already visited)
  const visited = history.map(h => h.destination).filter(Boolean);
  if (visited.length > 0 && !visited.includes(destination)) {
    lines.push(`I've already visited: ${visited.slice(0, 5).join(', ')} — so please make this trip feel different.`);
  }

  // 9 — Loyalty benefits reminder
  const tier = loyalty.current_tier || 'Blue';
  if (tier !== 'Blue') {
    lines.push(`I am a ${tier} loyalty member — please include any relevant member benefits or upgrades.`);
  }

  // 10 — Children specific
  if (children > 0) {
    lines.push(`We are travelling with ${children} child${children > 1 ? 'ren' : ''} — please suggest family-friendly hotels, kids activities, and appropriate experiences.`);
  }

  // 11 — Average trip length
  if (patterns.avg_trip_length_nights) {
    const nights = Math.round(patterns.avg_trip_length_nights);
    lines.push(`My typical trip is around ${nights} nights.`);
  }

  lines.push(`Please build me a complete personalised itinerary.`);

  return lines.join(' ');
}

/**
 * Build a simpler contextual prompt when user types a destination manually
 * but we have customer context to enrich it.
 */
export function enrichManualPrompt(message, customer) {
  if (!customer?.profile) return message;

  const children = customer.profile.children_in_family || 0;
  const tier     = customer.loyalty?.current_tier || 'Blue';
  const interests= (customer.interests?.top || []).slice(0, 3);

  const extras = [];
  if (children > 0)         extras.push(`travelling with ${children} child${children > 1 ? 'ren' : ''}`);
  if (tier !== 'Blue')      extras.push(`${tier} loyalty member`);
  if (interests.length > 0) extras.push(`interested in ${interests.join(' and ')}`);

  if (extras.length === 0) return message;
  return `${message} (Context: ${extras.join(', ')})`;
}

// ── Private helpers ───────────────────────────────────────────

function _guestDescription(adults, children) {
  if (adults === 1 && children === 0) return 'myself (solo)';
  if (adults === 2 && children === 0) return '2 adults (couple)';
  if (adults === 2 && children === 1) return '2 adults and 1 child (family of 3)';
  if (adults === 2 && children === 2) return '2 adults and 2 children (family of 4)';
  if (children === 0) return `${adults} adults`;
  return `${adults} adults and ${children} children`;
}

function _preferredStars(history) {
  if (!history.length) return null;
  const stars = history.map(h => h.hotel_stars).filter(Boolean);
  if (!stars.length) return null;
  return Math.round(stars.reduce((a, b) => a + b, 0) / stars.length);
}

function _commonAncillaries(history) {
  const counts = {};
  history.forEach(h => {
    (h.ancillaries || []).forEach(a => {
      const label = a.replace(/_/g, ' ');
      counts[label] = (counts[label] || 0) + 1;
    });
  });
  return Object.entries(counts)
    .filter(([, n]) => n >= 2)               // booked at least twice
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)
    .map(([label]) => label);
}
