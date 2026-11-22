(function () {
  const root = document.documentElement;
  // тема
  document.querySelectorAll('[data-theme-toggle]').forEach(b => b.addEventListener('click', () => {
    const t = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = t;
    try { localStorage.setItem('theme', t); } catch (e) {}
    window.dispatchEvent(new Event('themechange'));
  }));
  // мобильное меню
  document.querySelectorAll('[data-nav-toggle]').forEach(b => b.addEventListener('click', () =>
    document.querySelector('.app').classList.toggle('nav-open')));
  // тосты
  document.querySelectorAll('.toast').forEach((t, i) => {
    const close = () => { t.classList.add('out'); setTimeout(() => t.remove(), 300); };
    t.querySelector('button')?.addEventListener('click', close);
    setTimeout(close, 4500 + i * 400);
  });
  // подтверждение действий: <form data-confirm="Заголовок" data-confirm-text="..." data-tone="danger|primary" data-ok="Удалить">
  const dlg = document.getElementById('confirm-dialog');
  let pending = null;
  document.addEventListener('submit', e => {
    const f = e.target;
    if (!f.dataset.confirm || f.dataset.confirmed) return;
    e.preventDefault();
    pending = { form: f, submitter: e.submitter };
    dlg.querySelector('h3').textContent = f.dataset.confirm;
    dlg.querySelector('p').textContent = f.dataset.confirmText || 'Это действие нельзя отменить.';
    const ok = dlg.querySelector('[data-ok]');
    ok.textContent = f.dataset.ok || 'Удалить';
    const primary = f.dataset.tone === 'primary';
    ok.className = 'btn ' + (primary ? 'primary' : 'danger solid');
    dlg.querySelector('.ic').className = 'ic' + (primary ? ' pr' : '');
    dlg.querySelector('.ic').innerHTML = document.getElementById(primary ? 'ic-check' : 'ic-trash').innerHTML;
    dlg.showModal();
  });
  dlg?.querySelector('[data-ok]').addEventListener('click', () => {
    const { form, submitter } = pending; dlg.close();
    form.dataset.confirmed = '1';
    if (submitter && submitter.name) {
      const h = document.createElement('input'); h.type = 'hidden'; h.name = submitter.name; h.value = submitter.value; form.appendChild(h);
    }
    form.submit();
  });
  dlg?.querySelector('[data-cancel]').addEventListener('click', () => dlg.close());
  // открытие диалогов по data-open="id"
  document.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () =>
    document.getElementById(b.dataset.open).showModal()));
  document.querySelectorAll('dialog [data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(d => d.addEventListener('click', e => { if (e.target === d) d.close(); }));
  // фильтр внутри диалога выбора
  document.querySelectorAll('[data-filter]').forEach(inp => inp.addEventListener('input', () => {
    const q = inp.value.toLowerCase();
    document.querySelectorAll(inp.dataset.filter + ' label').forEach(l => l.style.display = l.textContent.toLowerCase().includes(q) ? '' : 'none');
  }));
})();
