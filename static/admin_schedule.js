(() => {
  const presetForm = document.getElementById('schedulePresetForm');
  if (presetForm) {
    const boxes = [...presetForm.querySelectorAll('input[name="weekdays"]')];
    presetForm.querySelectorAll('[data-days]').forEach((button) => {
      button.addEventListener('click', () => {
        const wanted = new Set((button.dataset.days || '').split(',').filter(Boolean));
        boxes.forEach((box) => { box.checked = wanted.has(box.value); });
      });
    });

    const state = document.getElementById('presetState');
    const times = document.getElementById('presetTimes');
    const refreshPreset = () => {
      const closed = state && state.value === 'closed';
      if (times) {
        times.classList.toggle('is-disabled', closed);
        times.querySelectorAll('input').forEach((input) => { input.disabled = closed; });
      }
    };
    state?.addEventListener('change', refreshPreset);
    refreshPreset();
  }

  document.querySelectorAll('[data-schedule-day]').forEach((card) => {
    const toggle = card.querySelector('[data-open-toggle]');
    const status = card.querySelector('[data-day-status]');
    const fields = card.querySelector('[data-time-fields]');
    const refresh = () => {
      const open = Boolean(toggle?.checked);
      card.classList.toggle('is-open', open);
      card.classList.toggle('is-closed', !open);
      if (status) status.textContent = open ? 'Aberto' : 'Fechado';
      if (fields) fields.classList.toggle('is-muted', !open);
    };
    toggle?.addEventListener('change', refresh);
    refresh();
  });

  const blockDate = document.getElementById('blockDate');
  document.querySelectorAll('[data-date-offset]').forEach((button) => {
    button.addEventListener('click', () => {
      if (!blockDate) return;
      const d = new Date();
      d.setHours(12, 0, 0, 0);
      d.setDate(d.getDate() + Number(button.dataset.dateOffset || 0));
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      blockDate.value = `${yyyy}-${mm}-${dd}`;
      blockDate.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
})();
