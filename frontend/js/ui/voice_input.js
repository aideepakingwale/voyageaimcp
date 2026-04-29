/**
 * VoyageAI Voice Input
 * ====================
 * Uses the Web Speech API (SpeechRecognition) to record audio from the
 * system microphone and transcribe it into text.
 *
 * Browser support: Chrome, Edge, Safari 14.1+
 * Firefox: not supported natively (shows a graceful fallback message)
 *
 * Usage:
 *   import { initVoiceInput } from './ui/voice_input.js';
 *   initVoiceInput('#chatInput', '#voiceBtn');
 *
 * The transcript is inserted into the input field and can be submitted
 * by the user or auto-submitted after a silence pause.
 */

let _recognition = null;
let _isListening = false;
let _silenceTimer = null;
const SILENCE_TIMEOUT_MS = 2200;   // auto-stop after 2.2s of silence
const MAX_LISTEN_MS      = 30000;  // hard stop after 30s

export function initVoiceInput(inputSelector, btnSelector) {
  const input  = document.querySelector(inputSelector);
  const btn    = document.querySelector(btnSelector);
  if (!input || !btn) return;

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    // Hide button gracefully on unsupported browsers
    btn.style.display = 'none';
    btn.title = 'Voice input not supported in this browser';
    return;
  }

  // ── Set up recognition ────────────────────────────────────
  _recognition = new SpeechRecognition();
  _recognition.continuous      = false;   // single utterance mode
  _recognition.interimResults  = true;    // show interim transcript
  _recognition.lang             = 'en-GB';
  _recognition.maxAlternatives  = 1;

  // ── Events ───────────────────────────────────────────────

  _recognition.onstart = () => {
    _isListening = true;
    _setBtn(btn, 'listening');
    _showHint(input, '🎤 Listening… speak now');
    // Hard stop after MAX_LISTEN_MS
    setTimeout(() => { if (_isListening) _stop(); }, MAX_LISTEN_MS);
  };

  _recognition.onresult = (e) => {
    // Collect transcript from all results
    let interim = '';
    let final_  = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final_ += t;
      else                       interim += t;
    }

    // Show interim in the input field with a dim style
    if (interim) {
      input.value = final_ + interim;
      input.style.color = 'var(--muted)';
      _autoResize(input);
    }
    if (final_) {
      input.value = final_;
      input.style.color = '';
      _autoResize(input);
      input.dispatchEvent(new Event('input'));

      // Reset silence timer on each final result
      clearTimeout(_silenceTimer);
      _silenceTimer = setTimeout(_stop, SILENCE_TIMEOUT_MS);
    }
  };

  _recognition.onspeechend = () => {
    clearTimeout(_silenceTimer);
    _silenceTimer = setTimeout(_stop, 400);
  };

  _recognition.onend = () => {
    _isListening = false;
    _setBtn(btn, 'idle');
    clearTimeout(_silenceTimer);
    input.style.color = '';
    // Remove hint
    document.getElementById('_voiceHint')?.remove();

    // If there is text, focus the input for review/edit before submit
    if (input.value.trim()) {
      input.focus();
      // Move cursor to end
      const len = input.value.length;
      input.setSelectionRange(len, len);
    }
  };

  _recognition.onerror = (e) => {
    _isListening = false;
    _setBtn(btn, 'idle');
    clearTimeout(_silenceTimer);
    document.getElementById('_voiceHint')?.remove();

    const msgs = {
      'not-allowed':     '🎤 Microphone access denied. Allow mic in browser settings.',
      'no-speech':       '🎤 No speech detected. Try again.',
      'network':         '🎤 Network error during recognition.',
      'audio-capture':   '🎤 No microphone found.',
      'service-not-allowed':'🎤 Speech service blocked.',
    };
    const msg = msgs[e.error] || `🎤 Voice error: ${e.error}`;
    _showToast(msg, 3000);
  };

  // ── Button click ─────────────────────────────────────────

  btn.addEventListener('click', (ev) => {
    ev.preventDefault();
    if (_isListening) {
      _stop();
    } else {
      _start();
    }
  });

  // ── Also allow keyboard shortcut: Alt+M ──────────────────
  document.addEventListener('keydown', (e) => {
    if (e.altKey && e.key === 'm') {
      e.preventDefault();
      if (_isListening) _stop();
      else _start();
    }
  });
}

function _start() {
  if (!_recognition || _isListening) return;
  try {
    _recognition.start();
  } catch (err) {
    // Already started
    console.warn('Voice recognition start error:', err);
  }
}

function _stop() {
  if (!_recognition || !_isListening) return;
  try {
    _recognition.stop();
  } catch { /* ignore */ }
}

function _setBtn(btn, state) {
  btn.classList.remove('voice-idle', 'voice-listening', 'voice-processing');
  btn.classList.add(`voice-${state}`);

  if (state === 'listening') {
    btn.innerHTML = `
      <span class="voice-wave">
        <span></span><span></span><span></span><span></span>
      </span>`;
    btn.title = 'Click to stop recording (Alt+M)';
    btn.setAttribute('aria-label', 'Stop voice recording');
  } else {
    btn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
        <line x1="12" y1="19" x2="12" y2="23"/>
        <line x1="8"  y1="23" x2="16" y2="23"/>
      </svg>`;
    btn.title = 'Voice input (Alt+M)';
    btn.setAttribute('aria-label', 'Start voice input');
  }
}

function _showHint(input, text) {
  document.getElementById('_voiceHint')?.remove();
  const hint = document.createElement('div');
  hint.id = '_voiceHint';
  hint.style.cssText = [
    'position:absolute','bottom:calc(100% + 8px)','left:50%',
    'transform:translateX(-50%)','background:var(--bg3)',
    'border:1px solid var(--teal)','border-radius:8px',
    'padding:6px 14px','font-size:12px','color:var(--teal)',
    'white-space:nowrap','pointer-events:none','z-index:100',
    'box-shadow:0 4px 20px rgba(0,201,167,.2)',
    'animation:fadeIn .2s ease',
  ].join(';');
  hint.textContent = text;
  // Position relative to input's parent
  const wrap = input.closest('.chat-input-wrap') || input.parentElement;
  if (wrap) {
    wrap.style.position = 'relative';
    wrap.appendChild(hint);
  }
}

function _showToast(message, duration = 3000) {
  const toast = document.createElement('div');
  toast.style.cssText = [
    'position:fixed','bottom:80px','left:50%',
    'transform:translateX(-50%)',
    'background:var(--bg2)','border:1px solid var(--amber)',
    'border-radius:8px','padding:10px 20px',
    'font-size:13px','color:var(--amber)',
    'z-index:9999','pointer-events:none',
    'box-shadow:0 4px 20px rgba(0,0,0,.4)',
    'animation:fadeIn .2s ease',
  ].join(';');
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

function _autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}
