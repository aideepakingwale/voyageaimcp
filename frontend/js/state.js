/**
 * VoyageAI Application State
 * Single source of truth. Mutate only via the exported setters.
 * UI modules read from here; they do NOT own state.
 */

const _state = {
  sessionId:        null,
  isLoading:        false,
  currentCustomer:  null,   // full customer object from API
  currentItinerary: null,   // current llm_output
  selectedAncillaries: new Map(),  // id → { name, price }
  gdsStartTime:     null,
  gdsInterval:      null,
};

// ── Readers ───────────────────────────────────────────────────

export const getSessionId        = ()  => _state.sessionId;
export const isLoading           = ()  => _state.isLoading;
export const getCurrentCustomer  = ()  => _state.currentCustomer;
export const getCurrentItinerary = ()  => _state.currentItinerary;
export const getSelectedAncillaries = () => _state.selectedAncillaries;

// ── Setters ───────────────────────────────────────────────────

export function setSessionId(id)        { _state.sessionId       = id; }
export function setLoading(flag)        { _state.isLoading       = flag; }
export function setCurrentCustomer(c)   { _state.currentCustomer = c; }
export function setCurrentItinerary(i)  { _state.currentItinerary = i; }

// ── Ancillaries ───────────────────────────────────────────────

export function toggleAncillary(id, name, price) {
  if (_state.selectedAncillaries.has(id)) {
    _state.selectedAncillaries.delete(id);
    return false;
  }
  _state.selectedAncillaries.set(id, { name, price });
  return true;
}

export function clearAncillaries() {
  _state.selectedAncillaries.clear();
}

export function getAncillaryTotal() {
  let total = 0;
  for (const { price } of _state.selectedAncillaries.values()) total += price;
  return total;
}

// ── GDS Timer ─────────────────────────────────────────────────

export function startGdsTimer() { _state.gdsStartTime = Date.now(); }
export function getGdsStart()   { return _state.gdsStartTime; }

export function setGdsInterval(iv) {
  clearInterval(_state.gdsInterval);
  _state.gdsInterval = iv;
}
export function stopGdsTimer() {
  clearInterval(_state.gdsInterval);
  _state.gdsInterval = null;
}
