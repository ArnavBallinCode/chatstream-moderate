// Wikimedia username autocomplete widget.
// Activate by calling initUserPicker(containerEl, submitBtn).
//
// Expected HTML inside container:
//   <input class="user-picker-input" type="text">
//   <ul  class="user-picker-suggestions"></ul>
//   <input type="hidden" name="wiki_username">
//   <input type="hidden" name="centralauth_id">

(function () {
  const MW_API = 'https://en.wikipedia.org/w/api.php';

  async function fetchSuggestions(prefix) {
    const url = `${MW_API}?action=query&list=allusers&auprefix=${encodeURIComponent(prefix)}&aulimit=8&format=json&origin=*`;
    const r = await fetch(url);
    const j = await r.json();
    return (j.query?.allusers || []).map(u => u.name);
  }

  async function fetchCentralAuthId(username) {
    const url = `${MW_API}?action=query&list=users&ususers=${encodeURIComponent(username)}&usprop=centralids&format=json&origin=*`;
    const r = await fetch(url);
    const j = await r.json();
    const user = j.query?.users?.[0];
    if (!user || user.missing !== undefined) return null;
    return user.centralids?.CentralAuth ?? null;
  }

  function initUserPicker(container, submitBtn) {
    const textInput  = container.querySelector('.user-picker-input');
    const list       = container.querySelector('.user-picker-suggestions');
    const nameHidden = container.querySelector('input[name="wiki_username"]');
    const caidHidden = container.querySelector('input[name="centralauth_id"]');

    let debounceTimer = null;
    let selectedName  = null;

    function clearSelection() {
      selectedName = null;
      nameHidden.value = '';
      caidHidden.value = '';
      if (submitBtn) submitBtn.disabled = true;
    }

    function closeList() {
      list.innerHTML = '';
      list.classList.add('hidden');
    }

    function select(name) {
      textInput.value = name;
      selectedName = name;
      closeList();
      fetchCentralAuthId(name).then(caid => {
        if (caid == null) {
          textInput.setCustomValidity('User not found on Wikimedia.');
          textInput.reportValidity();
          clearSelection();
          return;
        }
        textInput.setCustomValidity('');
        nameHidden.value = name;
        caidHidden.value = caid;
        if (submitBtn) submitBtn.disabled = false;
      });
    }

    textInput.addEventListener('input', () => {
      clearSelection();
      const q = textInput.value.trim();
      if (q.length < 2) { closeList(); return; }

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        const names = await fetchSuggestions(q);
        closeList();
        if (!names.length) return;
        names.forEach(name => {
          const li = document.createElement('li');
          li.textContent = name;
          li.addEventListener('mousedown', e => { e.preventDefault(); select(name); });
          list.appendChild(li);
        });
        list.classList.remove('hidden');
      }, 300);
    });

    textInput.addEventListener('keydown', e => {
      const items = list.querySelectorAll('li');
      const active = list.querySelector('li.active');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = active ? active.nextElementSibling : items[0];
        if (next) { active?.classList.remove('active'); next.classList.add('active'); }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = active ? active.previousElementSibling : items[items.length - 1];
        if (prev) { active?.classList.remove('active'); prev.classList.add('active'); }
      } else if (e.key === 'Enter' && active) {
        e.preventDefault();
        select(active.textContent);
      } else if (e.key === 'Escape') {
        closeList();
      }
    });

    document.addEventListener('click', e => {
      if (!container.contains(e.target)) closeList();
    });
  }

  // Auto-init all .user-picker containers on the page
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.user-picker').forEach(container => {
      const form      = container.closest('form');
      const submitBtn = form?.querySelector('[type="submit"]');
      initUserPicker(container, submitBtn);
    });
  });
})();
