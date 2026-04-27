/**
 * GDS Timer UI Module
 * Shows a 10-minute countdown matching the GDS session window.
 * Turns amber at 2 min, red at 1 min.
 */
import { $, show }                      from '../utils/dom.js';
import { startGdsTimer, getGdsStart,
         setGdsInterval, stopGdsTimer } from '../state.js';
import { Config }                       from '../config.js';

const GDS_WINDOW = Config.GDS_SESSION_TIMEOUT || 600;

/** Start the visible countdown. Call once per session. */
export function startTimer() {
  startGdsTimer();
  show($('#gdsTimer'), 'flex');

  const fill  = $('#gdsFill');
  const label = $('#gdsLabel');

  const iv = setInterval(() => {
    const elapsed   = (Date.now() - getGdsStart()) / 1000;
    const remaining = Math.max(0, GDS_WINDOW - elapsed);
    const fraction  = remaining / GDS_WINDOW;

    if (fill)  {
      fill.style.width      = `${fraction * 100}%`;
      fill.style.background = remaining > 120
        ? 'var(--green)'
        : remaining > 60
          ? 'var(--amber)'
          : 'var(--red)';
    }

    if (label) {
      const m = Math.floor(remaining / 60);
      const s = Math.floor(remaining % 60);
      label.textContent = `${m}:${String(s).padStart(2, '0')}`;
    }

    if (remaining === 0) {
      clearInterval(iv);
      if (label) label.textContent = 'Expired';
    }
  }, 1000);

  setGdsInterval(iv);
}

/** Stop and reset the timer (call after booking confirmed). */
export function stopTimer() {
  stopGdsTimer();
}
