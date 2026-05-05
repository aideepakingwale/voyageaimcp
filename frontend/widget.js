(function () {
  if (window.VoyageAIWidget) return;

  const script = document.currentScript || document.querySelector('script[data-voyage-widget]');
  const baseUrl = (script?.dataset?.voyageBase || window.VOYAGE_WIDGET_BASE || window.location.origin).replace(/\/$/, '');
  const position = (script?.dataset?.position || 'bottom-right').toLowerCase();
  const title = script?.dataset?.title || 'VoyageAI';
  const launcherLabel = script?.dataset?.launcherLabel || 'Travel Planner';
  const accent = script?.dataset?.accent || '#00C9A7';
  const width = script?.dataset?.width || '420px';
  const height = script?.dataset?.height || '720px';

  const style = document.createElement('style');
  style.textContent = `
    .voyage-widget-root {
      position: fixed;
      z-index: 2147483000;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .voyage-widget-root.bottom-right { right: 24px; bottom: 24px; }
    .voyage-widget-root.bottom-left { left: 24px; bottom: 24px; }
    .voyage-widget-root.top-right { right: 24px; top: 24px; }
    .voyage-widget-root.top-left { left: 24px; top: 24px; }
    .voyage-widget-launcher {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      border: 0;
      border-radius: 999px;
      background: ${accent};
      color: #04121c;
      font-size: 14px;
      font-weight: 700;
      box-shadow: 0 18px 40px rgba(4, 18, 28, .28);
      cursor: pointer;
    }
    .voyage-widget-launcher:hover {
      filter: brightness(1.03);
    }
    .voyage-widget-panel {
      position: absolute;
      width: min(${width}, calc(100vw - 24px));
      height: min(${height}, calc(100vh - 88px));
      border-radius: 20px;
      overflow: hidden;
      background: #071830;
      box-shadow: 0 24px 70px rgba(4, 18, 28, .38);
      border: 1px solid rgba(127, 179, 211, .22);
      opacity: 0;
      pointer-events: none;
      transform: translateY(16px) scale(.98);
      transform-origin: bottom right;
      transition: opacity .18s ease, transform .18s ease;
    }
    .voyage-widget-root.bottom-right .voyage-widget-panel,
    .voyage-widget-root.bottom-left .voyage-widget-panel {
      bottom: calc(100% + 14px);
    }
    .voyage-widget-root.bottom-right .voyage-widget-panel,
    .voyage-widget-root.top-right .voyage-widget-panel {
      right: 0;
    }
    .voyage-widget-root.bottom-left .voyage-widget-panel,
    .voyage-widget-root.top-left .voyage-widget-panel {
      left: 0;
    }
    .voyage-widget-root.top-right .voyage-widget-panel,
    .voyage-widget-root.top-left .voyage-widget-panel {
      top: calc(100% + 14px);
      transform-origin: top right;
    }
    .voyage-widget-root.is-open .voyage-widget-panel {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }
    .voyage-widget-header {
      height: 52px;
      padding: 0 14px 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #e8f4fd;
      background: linear-gradient(135deg, #071830, #0a2540);
      border-bottom: 1px solid rgba(127, 179, 211, .16);
    }
    .voyage-widget-title {
      font-size: 13px;
      font-weight: 700;
      letter-spacing: .2px;
    }
    .voyage-widget-close {
      border: 0;
      background: transparent;
      color: #7fb3d3;
      font-size: 22px;
      line-height: 1;
      cursor: pointer;
    }
    .voyage-widget-frame {
      width: 100%;
      height: calc(100% - 52px);
      border: 0;
      background: #040c18;
    }
    @media (max-width: 640px) {
      .voyage-widget-root.bottom-right,
      .voyage-widget-root.bottom-left,
      .voyage-widget-root.top-right,
      .voyage-widget-root.top-left {
        left: 12px;
        right: 12px;
        top: auto;
        bottom: 12px;
      }
      .voyage-widget-launcher {
        width: 100%;
        justify-content: center;
      }
      .voyage-widget-panel {
        position: fixed;
        left: 12px;
        right: 12px;
        bottom: 72px;
        width: auto;
        height: min(calc(100vh - 92px), 760px);
      }
    }
  `;
  document.head.appendChild(style);

  const root = document.createElement('div');
  root.className = `voyage-widget-root ${position}`;

  const launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.className = 'voyage-widget-launcher';
  launcher.setAttribute('aria-expanded', 'false');
  launcher.innerHTML = `<span style="font-size:16px">✈</span><span>${launcherLabel}</span>`;

  const panel = document.createElement('div');
  panel.className = 'voyage-widget-panel';

  const header = document.createElement('div');
  header.className = 'voyage-widget-header';
  header.innerHTML = `<div class="voyage-widget-title">${title}</div>`;

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'voyage-widget-close';
  closeBtn.setAttribute('aria-label', 'Close VoyageAI widget');
  closeBtn.textContent = '×';
  header.appendChild(closeBtn);

  const frame = document.createElement('iframe');
  frame.className = 'voyage-widget-frame';
  frame.loading = 'lazy';
  frame.allow = 'microphone';
  frame.src = `${baseUrl}/login.html?embed=1`;

  panel.appendChild(header);
  panel.appendChild(frame);
  root.appendChild(panel);
  root.appendChild(launcher);
  document.body.appendChild(root);

  function openWidget() {
    root.classList.add('is-open');
    launcher.setAttribute('aria-expanded', 'true');
  }

  function closeWidget() {
    root.classList.remove('is-open');
    launcher.setAttribute('aria-expanded', 'false');
  }

  launcher.addEventListener('click', function () {
    if (root.classList.contains('is-open')) closeWidget();
    else openWidget();
  });

  closeBtn.addEventListener('click', closeWidget);

  document.addEventListener('click', function (event) {
    if (!root.classList.contains('is-open')) return;
    if (root.contains(event.target)) return;
    closeWidget();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeWidget();
  });

  window.VoyageAIWidget = {
    open: openWidget,
    close: closeWidget,
    mount: function () { return root; },
    iframe: frame
  };
})();
