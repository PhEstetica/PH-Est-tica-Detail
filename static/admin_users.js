(() => {
  const syncRole = (form) => {
    const role = form.querySelector('[data-role-select]')?.value || 'staff';
    const picker = form.querySelector('[data-permission-picker]');
    if (!picker) return;
    picker.classList.toggle('manager-permissions', role === 'manager');
    picker.querySelectorAll('input[type="checkbox"][name^="perm_"]').forEach((box) => {
      if (role === 'manager') {
        box.checked = true;
        box.disabled = true;
      } else {
        box.disabled = false;
      }
    });
  };

  document.querySelectorAll('[data-permission-form]').forEach((form) => {
    form.querySelector('[data-perm-all]')?.addEventListener('click', () => {
      form.querySelectorAll('input[type="checkbox"][name^="perm_"]:not(:disabled)').forEach((b) => b.checked = true);
    });
    form.querySelector('[data-perm-none]')?.addEventListener('click', () => {
      form.querySelectorAll('input[type="checkbox"][name^="perm_"]:not(:disabled)').forEach((b) => b.checked = false);
    });
    const role = form.querySelector('[data-role-select]');
    role?.addEventListener('change', () => syncRole(form));
    syncRole(form);
  });
})();
