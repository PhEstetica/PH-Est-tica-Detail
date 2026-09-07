(function () {
  const root = document.querySelector('[data-settings-tabs]');
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll('[data-settings-tab]'));
  const panels = Array.from(root.querySelectorAll('[data-settings-panel]'));
  const valid = new Set(panels.map((panel) => panel.dataset.settingsPanel));

  function chooseTab() {
    const hash = (window.location.hash || '').replace('#', '');
    if (valid.has(hash)) return hash;

    const params = new URLSearchParams(window.location.search);
    if (params.has('restored') || params.has('restore_error')) return 'backups';
    if (params.has('wa_messages') || params.has('wa_messages_reset')) return 'mensagens-whatsapp';
    if (params.has('image') || params.has('image_reset')) return 'imagens-home';
    if (params.has('logo')) return 'logo';
    return 'identidade';
  }

  function activate(name, updateHash) {
    if (!valid.has(name)) name = 'identidade';
    root.classList.add('settings-tabs-ready');

    tabs.forEach((tab) => {
      const active = tab.dataset.settingsTab === name;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-current', active ? 'page' : 'false');
    });

    panels.forEach((panel) => {
      const active = panel.dataset.settingsPanel === name;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });

    if (updateHash && window.location.hash !== '#' + name) {
      history.replaceState(null, '', window.location.pathname + window.location.search + '#' + name);
    }
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', (event) => {
      event.preventDefault();
      activate(tab.dataset.settingsTab, true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });

  window.addEventListener('hashchange', () => activate(chooseTab(), false));
  activate(chooseTab(), false);
})();
