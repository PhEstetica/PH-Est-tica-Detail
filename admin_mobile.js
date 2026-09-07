(function () {
  const body = document.body;
  const toggle = document.querySelector('.admin-menu-toggle');
  const side = document.getElementById('admin-side');
  const closers = document.querySelectorAll('[data-admin-menu-close]');
  if (!toggle || !side) return;

  function setOpen(open) {
    body.classList.toggle('admin-menu-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  toggle.addEventListener('click', function () {
    setOpen(!body.classList.contains('admin-menu-open'));
  });
  closers.forEach(function (el) { el.addEventListener('click', function () { setOpen(false); }); });
  side.querySelectorAll('a').forEach(function (a) { a.addEventListener('click', function () { setOpen(false); }); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
  window.addEventListener('resize', function () { if (window.innerWidth > 980) setOpen(false); });
})();
