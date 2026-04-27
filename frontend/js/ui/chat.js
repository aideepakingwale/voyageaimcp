/**
 * Chat UI Module
 * Responsible for: appending messages, typing indicator, scrolling.
 * Does NOT fetch data or manage state.
 */
import { $, appendAndScroll, el } from '../utils/dom.js';
import { esc }                    from '../utils/format.js';

const getWindow = () => $('#cwin');

/** Append a user bubble to the chat window. */
export function appendUser(text) {
  const wrap = el('div', 'msg user', `
    <div class="av">👤</div>
    <div class="bubble">${esc(text)}</div>
  `);
  appendAndScroll(getWindow(), wrap);
}

/** Append an AI bubble (accepts raw HTML). */
export function appendAI(html) {
  const wrap = el('div', 'msg ai', `
    <div class="av">🤖</div>
    <div class="bubble">${html}</div>
  `);
  appendAndScroll(getWindow(), wrap);
}

/** Append a full-width AI card (itinerary, etc). */
export function appendCard(cardHTML) {
  const wrap = el('div', 'msg ai', `
    <div class="av">🤖</div>
    <div style="flex:1;min-width:0">${cardHTML}</div>
  `);
  appendAndScroll(getWindow(), wrap);
}

/** Show the animated typing indicator. Returns the element so it can be removed. */
export function showTyping() {
  const wrap = el('div', 'msg ai');
  wrap.id    = 'typing-indicator';
  wrap.innerHTML = `
    <div class="av">🤖</div>
    <div class="bubble">
      <div class="typing">
        <span></span><span></span><span></span>
      </div>
    </div>`;
  appendAndScroll(getWindow(), wrap);
  return wrap;
}

/** Remove the typing indicator. */
export function hideTyping() {
  $('#typing-indicator')?.remove();
}

/** Scroll chat to bottom. */
export function scrollToBottom() {
  const w = getWindow();
  if (w) w.scrollTop = w.scrollHeight;
}

/** Hide suggestion chips after first message. */
export function hideSuggestions() {
  const el = $('#suggs');
  if (el) el.style.display = 'none';
}
