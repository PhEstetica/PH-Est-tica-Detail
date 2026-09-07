(function () {
  const root = document.querySelector('[data-service-tabs]');
  if (!root) return;

  const mainTabs = Array.from(root.querySelectorAll('[data-service-main-tab]'));
  const mainPanels = Array.from(root.querySelectorAll('[data-service-main-panel]'));
  const validMain = new Set(mainPanels.map((panel) => panel.dataset.serviceMainPanel));
  const storageMain = 'ph_admin_services_main';
  const storageSubPrefix = 'ph_admin_services_sub_';

  function validSub(main, sub) {
    return !!root.querySelector(`[data-service-sub-panel="${main}:${sub}"]`);
  }

  function currentFromHash() {
    const hash = (window.location.hash || '').replace('#', '');
    const match = /^(precos|adicionais)-(moto|carro)$/.exec(hash);
    return match ? { main: match[1], sub: match[2] } : null;
  }

  function preferredSub(main) {
    const saved = localStorage.getItem(storageSubPrefix + main);
    return validSub(main, saved) ? saved : 'moto';
  }

  function updateHash(main, sub) {
    const next = `#${main}-${sub}`;
    if (window.location.hash !== next) {
      history.replaceState(null, '', window.location.pathname + window.location.search + next);
    }
  }

  function activateSub(main, sub, updateUrl) {
    if (!validSub(main, sub)) sub = 'moto';
    localStorage.setItem(storageSubPrefix + main, sub);

    root.querySelectorAll(`[data-service-sub-tabs="${main}"] [data-service-sub-tab]`).forEach((tab) => {
      const active = tab.dataset.serviceSubTab === sub;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    root.querySelectorAll('[data-service-sub-panel]').forEach((panel) => {
      if (!panel.dataset.serviceSubPanel.startsWith(main + ':')) return;
      const active = panel.dataset.serviceSubPanel === `${main}:${sub}`;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });

    if (updateUrl) updateHash(main, sub);
  }

  function activateMain(main, requestedSub, updateUrl) {
    if (!validMain.has(main)) main = 'precos';
    localStorage.setItem(storageMain, main);

    mainTabs.forEach((tab) => {
      const active = tab.dataset.serviceMainTab === main;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    mainPanels.forEach((panel) => {
      const active = panel.dataset.serviceMainPanel === main;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });

    const sub = validSub(main, requestedSub) ? requestedSub : preferredSub(main);
    activateSub(main, sub, updateUrl);
  }

  mainTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      activateMain(tab.dataset.serviceMainTab, null, true);
      root.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  root.querySelectorAll('[data-service-sub-tabs] [data-service-sub-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const group = tab.closest('[data-service-sub-tabs]');
      const main = group.dataset.serviceSubTabs;
      activateSub(main, tab.dataset.serviceSubTab, true);
    });
  });

  root.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', () => {
      const activeMain = root.querySelector('[data-service-main-tab].active')?.dataset.serviceMainTab || 'precos';
      const activeSub = root.querySelector(`[data-service-sub-tabs="${activeMain}"] [data-service-sub-tab].active`)?.dataset.serviceSubTab || 'moto';
      localStorage.setItem(storageMain, activeMain);
      localStorage.setItem(storageSubPrefix + activeMain, activeSub);
    });
  });

  window.addEventListener('hashchange', () => {
    const fromHash = currentFromHash();
    if (fromHash) activateMain(fromHash.main, fromHash.sub, false);
  });

  const fromHash = currentFromHash();
  if (fromHash) {
    activateMain(fromHash.main, fromHash.sub, false);
  } else {
    const savedMain = localStorage.getItem(storageMain);
    activateMain(validMain.has(savedMain) ? savedMain : 'precos', null, false);
  }
})();
