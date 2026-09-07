(function () {
  const groups = Array.from(document.querySelectorAll('[data-admin-tab-group]'));
  if (!groups.length) return;

  function own(group, selector) {
    return Array.from(group.querySelectorAll(selector)).filter((el) => el.closest('[data-admin-tab-group]') === group);
  }

  groups.forEach((group) => {
    const name = group.dataset.adminTabGroup || 'tabs';
    const buttons = own(group, '[data-admin-tab]');
    const panels = own(group, '[data-admin-tab-panel]');
    if (!buttons.length || !panels.length) return;

    const valid = new Set(panels.map((panel) => panel.dataset.adminTabPanel));
    const storageKey = `ph_admin_tabs:${window.location.pathname}:${name}`;
    const defaultTab = group.dataset.defaultTab || panels[0].dataset.adminTabPanel;

    function activate(tab) {
      if (!valid.has(tab)) tab = defaultTab;
      if (!valid.has(tab)) tab = panels[0].dataset.adminTabPanel;

      buttons.forEach((button) => {
        const active = button.dataset.adminTab === tab;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });

      panels.forEach((panel) => {
        const active = panel.dataset.adminTabPanel === tab;
        panel.hidden = !active;
        panel.classList.toggle('active', active);
      });

      try { localStorage.setItem(storageKey, tab); } catch (_) {}
    }

    buttons.forEach((button) => {
      button.addEventListener('click', () => activate(button.dataset.adminTab));
    });

    let saved = null;
    try { saved = localStorage.getItem(storageKey); } catch (_) {}
    activate(valid.has(saved) ? saved : defaultTab);
    group.classList.add('admin-tabs-ready');
  });
})();
