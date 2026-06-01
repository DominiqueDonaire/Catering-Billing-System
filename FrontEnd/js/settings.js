(() => {
  const DEFAULT_FONT_SIZE = 15;
  const FONT_STEPS = [
    { label: 'Small', size: 13 },
    { label: 'Medium', size: 15 },
    { label: 'Large', size: 17 },
    { label: 'Extra Large', size: 19 }
  ];

  function getStoredFontSize() {
    const value = Number(localStorage.getItem('fontSize'));
    return FONT_STEPS.some(step => step.size === value) ? value : DEFAULT_FONT_SIZE;
  }

  function applyFontSize(size) {
    const resolved = FONT_STEPS.some(step => step.size === Number(size)) ? Number(size) : DEFAULT_FONT_SIZE;
    const scale = resolved / DEFAULT_FONT_SIZE;
    document.documentElement.style.fontSize = `${DEFAULT_FONT_SIZE}px`;
    document.documentElement.style.zoom = String(scale);
    localStorage.setItem('fontSize', String(resolved));
    return resolved;
  }

  let settingsOpen = false;

  function syncBodyScrollLock() {
    document.body.style.overflow = settingsOpen ? 'hidden' : '';
  }

  function settingsIconSvg() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2"></circle><path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a1.9 1.9 0 0 1 0 2.7 1.9 1.9 0 0 1-2.7 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-4 0v-.2a1 1 0 0 0-.7-.9 1 1 0 0 0-1.1.2l-.1.1a1.9 1.9 0 0 1-2.7 0 1.9 1.9 0 0 1 0-2.7l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1 0-4h.2a1 1 0 0 0 .9-.7 1 1 0 0 0-.2-1.1l-.1-.1a1.9 1.9 0 0 1 0-2.7 1.9 1.9 0 0 1 2.7 0l.1.1a1 1 0 0 0 1.1.2h.1a1 1 0 0 0 .6-.9V4a2 2 0 0 1 4 0v.2a1 1 0 0 0 .7.9 1 1 0 0 0 1.1-.2l.1-.1a1.9 1.9 0 0 1 2.7 0 1.9 1.9 0 0 1 0 2.7l-.1.1a1 1 0 0 0-.2 1.1v.1a1 1 0 0 0 .9.6H20a2 2 0 0 1 0 4h-.2a1 1 0 0 0-.9.7z"></path></svg>';
  }

  function injectStyles() {
    if (document.getElementById('settings-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'settings-panel-styles';
    style.textContent = `
      #settings-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.45);
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease;
        z-index: 5000;
      }
      #settings-overlay.open {
        opacity: 1;
        pointer-events: auto;
      }
      #settings-drawer {
        position: fixed;
        top: 0;
        right: 0;
        height: 100vh;
        width: min(380px, 92vw);
        background: #fff;
        color: #2c2c2c;
        border-left: 1px solid #eee;
        box-shadow: -10px 0 30px rgba(0,0,0,0.14);
        transform: translateX(100%);
        transition: transform 0.2s ease;
        z-index: 5001;
        display: flex;
        flex-direction: column;
      }
      body.dark #settings-drawer {
        background: #202124;
        color: #e8eaed;
        border-left-color: #303134;
      }
      #settings-drawer.open {
        transform: translateX(0);
      }
      .settings-head {
        padding: 18px 20px;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      body.dark .settings-head {
        border-bottom-color: #303134;
      }
      .settings-title {
        font-size: 18px;
        font-weight: 700;
      }
      .settings-close {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        border: 1px solid #eee;
        background: #fff;
        color: #666;
        cursor: pointer;
      }
      body.dark .settings-close {
        background: #2b2d31;
        border-color: #303134;
        color: #e8eaed;
      }
      .settings-body {
        padding: 18px 20px 22px;
        overflow-y: auto;
      }
      .settings-link-icon {
        width: 18px;
        height: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      .settings-link-icon svg {
        width: 18px;
        height: 18px;
        stroke: currentColor;
        fill: none;
        stroke-width: 1.9;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      .settings-label {
        font-size: 15px;
        font-weight: 700;
        margin-bottom: 2px;
      }
      .settings-desc {
        font-size: 13px;
        color: #888;
        margin-bottom: 14px;
      }
      body.dark .settings-desc {
        color: #9aa0a6;
      }
      .settings-slider {
        width: 100%;
        accent-color: #e07b00;
      }
      .settings-stops {
        margin-top: 10px;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
      }
      .settings-stop {
        font-size: 12px;
        text-align: center;
        color: #888;
      }
      body.dark .settings-stop {
        color: #9aa0a6;
      }
      .settings-stop.active {
        color: #e07b00;
        font-weight: 700;
      }
      .settings-preview {
        margin-top: 16px;
        padding: 14px;
        border-radius: 12px;
        border: 1px solid #eee;
        background: #fafafa;
      }
      body.dark .settings-preview {
        border-color: #303134;
        background: #2b2d31;
      }
      .settings-preview h4 {
        margin: 0 0 8px;
        font-size: 1.08rem;
        font-weight: 700;
      }
      .settings-preview p {
        margin: 0 0 6px;
        font-size: 0.95rem;
      }
      .settings-preview small {
        color: #888;
        font-size: 0.82rem;
      }
      body.dark .settings-preview small {
        color: #9aa0a6;
      }
      body {
        overflow-x: hidden;
      }
      .sidebar {
        position: fixed !important;
        left: 0;
        top: 0;
        width: 220px !important;
        height: 100vh !important;
        z-index: 200;
        overflow-y: auto;
        transform: translateX(0) !important;
      }
      .main {
        margin-left: 220px !important;
        width: calc(100% - 220px);
        min-width: 0;
      }
      body.page-entering .main {
        animation: appPageEnter 0.24s ease both;
      }
      body.page-leaving .main {
        opacity: 0;
        transform: translateX(18px);
        transition: opacity 0.18s ease, transform 0.18s ease;
      }
      @keyframes appPageEnter {
        from {
          opacity: 0;
          transform: translateX(18px);
        }
        to {
          opacity: 1;
          transform: translateX(0);
        }
      }
      @media (max-width: 800px) {
        .main {
          margin-left: 220px !important;
          width: calc(100% - 220px);
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .main {
          transition: none !important;
        }
        body.page-entering .main {
          animation: none;
        }
        body.page-leaving .main {
          transition: none;
          transform: none;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function buildSettingsPanel() {
    if (document.getElementById('settings-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'settings-overlay';

    const drawer = document.createElement('aside');
    drawer.id = 'settings-drawer';
    drawer.innerHTML = `
      <div class="settings-head">
        <div class="settings-title">Settings</div>
        <button class="settings-close" type="button" aria-label="Close settings">&times;</button>
      </div>
      <div class="settings-body">
        <div class="settings-label">Text Size</div>
        <div class="settings-desc">Adjust to make text easier to read</div>
        <input id="settings-font-slider" class="settings-slider" type="range" min="0" max="3" step="1" value="1">
        <div id="settings-stops" class="settings-stops">
          ${FONT_STEPS.map(step => `<div class="settings-stop" data-size="${step.size}">${step.label}</div>`).join('')}
        </div>
        <div class="settings-preview">
          <h4>Order #14 &mdash; Balay</h4>
          <p>Event Date: June 6, 2026</p>
          <small>&#8369;2,850.00 &middot; Verified</small>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    document.body.appendChild(drawer);

    const slider = drawer.querySelector('#settings-font-slider');
    const stops = Array.from(drawer.querySelectorAll('.settings-stop'));
    const closeBtn = drawer.querySelector('.settings-close');

    function syncUI(size) {
      const index = Math.max(0, FONT_STEPS.findIndex(step => step.size === size));
      slider.value = String(index);
      stops.forEach(stop => stop.classList.toggle('active', Number(stop.dataset.size) === size));
    }

    slider.addEventListener('input', () => {
      const size = FONT_STEPS[Number(slider.value)]?.size || DEFAULT_FONT_SIZE;
      applyFontSize(size);
      syncUI(size);
    });

    closeBtn.addEventListener('click', closeSettings);
    overlay.addEventListener('click', closeSettings);
    syncUI(getStoredFontSize());
  }

  function openSettings(event) {
    if (event) event.preventDefault();
    const overlay = document.getElementById('settings-overlay');
    const drawer = document.getElementById('settings-drawer');
    if (!overlay || !drawer) return;
    settingsOpen = true;
    overlay.classList.add('open');
    drawer.classList.add('open');
    syncBodyScrollLock();
  }

  function closeSettings() {
    const overlay = document.getElementById('settings-overlay');
    const drawer = document.getElementById('settings-drawer');
    if (!overlay || !drawer) return;
    settingsOpen = false;
    overlay.classList.remove('open');
    drawer.classList.remove('open');
    syncBodyScrollLock();
  }

  function injectSidebarSettingsLink() {
    const footer = document.querySelector('.sidebar-footer');
    const sidebar = footer?.parentElement;
    if (!footer || !sidebar || sidebar.querySelector('.app-settings-link')) return;

    const link = document.createElement('a');
    link.href = '#';
    link.className = 'nav-item app-settings-link';
    link.innerHTML = `<span class="settings-link-icon">${settingsIconSvg()}</span><span>Settings</span>`;
    link.addEventListener('click', openSettings);
    sidebar.insertBefore(link, footer);
  }

  function isSamePageUrl(url) {
    return url.pathname === window.location.pathname && url.search === window.location.search;
  }

  function animateSidebarNavigation() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    requestAnimationFrame(() => {
      document.body.classList.add('page-entering');
    });

    sidebar.addEventListener('click', event => {
      if (!event.target.closest) return;
      const link = event.target.closest('a.nav-item');
      if (!link || link.classList.contains('app-settings-link')) return;
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (link.target && link.target !== '_self') return;

      const href = link.getAttribute('href');
      if (!href || href.startsWith('#')) return;

      const targetUrl = new URL(href, window.location.href);
      if (isSamePageUrl(targetUrl)) return;

      event.preventDefault();
      sidebar.querySelectorAll('a.nav-item').forEach(item => item.classList.remove('active'));
      link.classList.add('active');
      document.body.classList.remove('page-entering');
      document.body.classList.add('page-leaving');

      window.setTimeout(() => {
        window.location.href = targetUrl.href;
      }, 180);
    });
  }

  function init() {
    applyFontSize(getStoredFontSize());
    injectStyles();
    buildSettingsPanel();
    injectSidebarSettingsLink();
    animateSidebarNavigation();

    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      if (settingsOpen) {
        closeSettings();
      }
    });
  }

  window.AppSettings = {
    open: openSettings,
    close: closeSettings,
    applyFontSize
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
