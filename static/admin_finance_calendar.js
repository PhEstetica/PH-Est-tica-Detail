(() => {
  const root = document.querySelector('.admin-main');
  if (!root) return;

  const isFinancePage = location.pathname.startsWith('/admin/financeiro');
  if (!isFinancePage) return;

  function openPicker(input) {
    if (!input || input.disabled || input.readOnly) return;
    if (typeof input.showPicker === 'function') {
      try { input.showPicker(); } catch (_) { input.focus(); }
    } else {
      input.focus();
      input.click();
    }
  }

  root.querySelectorAll('input[type="date"], input[type="month"]').forEach((input) => {
    if (input.dataset.calendarEnhanced === '1') return;
    input.dataset.calendarEnhanced = '1';
    input.classList.add('finance-calendar-input');
    input.setAttribute('autocomplete', 'off');

    const label = input.closest('label');
    if (label) label.classList.add('finance-calendar-label');

    input.addEventListener('click', (event) => {
      // Em navegadores compatíveis, clicar em qualquer parte do campo abre o calendário.
      if (event.detail > 0) openPicker(input);
    });

    input.addEventListener('keydown', (event) => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.altKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        openPicker(input);
      }
    });
  });
})();
