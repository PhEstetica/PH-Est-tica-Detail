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

// V15 — efeitos de entrada suaves e acabamento premium ao rolar.
(() => {
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const selectors = [
    '.home-v14 .section-head-v14',
    '.home-v14 .metric-v14-card',
    '.home-v14 .premium-service-card',
    '.home-v14 .premium-story-card',
    '.home-v14 .process-v14-card',
    '.home-v14 .premium-detail-grid figure',
    '.home-v14 .gallery-home-item',
    '.home-v14 .premium-illustrative-gallery figure',
    '.home-v14 .instagram-follow-v14',
    '.home-v14 .premium-testimonial-card',
    '.home-v14 .cta-card-v14'
  ];
  const items = [...document.querySelectorAll(selectors.join(','))];
  items.forEach((el, i) => {
    el.classList.add('ph-reveal');
    el.style.setProperty('--reveal-delay', `${Math.min((i % 4) * 70, 210)}ms`);
  });

  const heroItems = document.querySelectorAll('.hero-v14-copy, .hero-v14-media');
  heroItems.forEach((el, i) => {
    el.classList.add('ph-reveal', 'ph-reveal-hero');
    el.style.setProperty('--reveal-delay', `${i * 120}ms`);
  });

  if (reduceMotion || !('IntersectionObserver' in window)) {
    document.querySelectorAll('.ph-reveal').forEach(el => el.classList.add('is-visible'));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    document.querySelectorAll('.ph-reveal').forEach(el => observer.observe(el));
  }

  const topbar = document.getElementById('siteTopbar');
  if (topbar) {
    const updateTopbar = () => topbar.classList.toggle('is-scrolled', window.scrollY > 18);
    updateTopbar();
    window.addEventListener('scroll', updateTopbar, { passive: true });
  }
})();
