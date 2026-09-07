// Helpers globais mínimos. Mantido sem dependências externas para facilitar implantação.
window.PH = { brl(v){ return new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(v||0)); } };

// V14 — menu responsivo premium do site público
(() => {
  const toggle = document.getElementById('mobileMenuToggle');
  const panel = document.getElementById('mobileMenuPanel');
  const topbar = document.getElementById('siteTopbar');
  if (!toggle || !panel || !topbar) return;

  const closeMenu = () => {
    topbar.classList.remove('mobile-menu-open');
    toggle.setAttribute('aria-expanded', 'false');
  };

  toggle.addEventListener('click', () => {
    const open = !topbar.classList.contains('mobile-menu-open');
    topbar.classList.toggle('mobile-menu-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  panel.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenu(); });
  document.addEventListener('click', (event) => { if (!topbar.contains(event.target)) closeMenu(); });
})();
