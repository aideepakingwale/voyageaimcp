/**
 * DOM utility helpers — thin wrappers for common operations.
 */

/** querySelector shorthand */
export const $ = (sel, ctx = document) => ctx.querySelector(sel);

/** querySelectorAll shorthand */
export const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

/** Create element with optional class and innerHTML */
export function el(tag, cls = '', html = '') {
  const e = document.createElement(tag);
  if (cls)  e.className = cls;
  if (html) e.innerHTML = html;
  return e;
}

/** Append element and scroll parent to bottom */
export function appendAndScroll(parent, child) {
  parent.appendChild(child);
  parent.scrollTop = parent.scrollHeight;
}

/** Auto-resize a textarea to fit content */
export function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 100)}px`;
}

/** Show/hide an element */
export function show(el, display = 'block') { if (el) el.style.display = display; }
export function hide(el)                    { if (el) el.style.display = 'none';  }

/** Toggle a CSS class */
export function toggle(el, cls, force) {
  if (!el) return;
  if (force !== undefined) el.classList.toggle(cls, force);
  else el.classList.toggle(cls);
}

/** Set element text content safely */
export function setText(sel, text) {
  const e = typeof sel === 'string' ? $(sel) : sel;
  if (e) e.textContent = text ?? '—';
}

/** Set element inner HTML */
export function setHTML(sel, html) {
  const e = typeof sel === 'string' ? $(sel) : sel;
  if (e) e.innerHTML = html ?? '';
}
