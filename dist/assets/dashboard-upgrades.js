(() => {
  const qs = new URLSearchParams(location.search);
  const API = (qs.get('api') || localStorage.getItem('pv_api_url') || '').trim().replace(/\/$/, '');
  const token = () => localStorage.getItem('pv_token') || '';

  function state(text, good=false) {
    const el = document.getElementById('state');
    if (!el) return;
    el.textContent = text;
    el.style.color = good ? '#d9ff65' : '#a7bbb3';
  }

  async function apiRequest(path, options={}) {
    if (!API) throw new Error('API povezava ni nastavljena.');
    const headers = {'Content-Type':'application/json', ...(options.headers || {})};
    if (token()) headers.Authorization = `Bearer ${token()}`;
    const res = await fetch(`${API}${path}`, {...options, headers});
    const text = await res.text();
    let data; try { data = JSON.parse(text); } catch { data = {detail:text}; }
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
    return data;
  }

  function button(label, attr, id) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'button light';
    el.textContent = label;
    el.dataset[attr] = id;
    return el;
  }

  async function openPreview(projectId) {
    const popup = window.open('about:blank', '_blank');
    try {
      const session = await apiRequest(`/projects/${projectId}/preview-session`, {method:'POST'});
      if (!session.url) throw new Error('Preview URL ni bil ustvarjen.');
      if (popup) popup.location = session.url;
      else window.location.href = session.url;
      state('Zasebni predogled je pripravljen.', true);
    } catch (err) {
      if (popup) popup.close();
      state(err.message);
    }
  }

  async function sendHandoff(projectId) {
    try {
      state('Pošiljam deployment napotke …');
      const result = await apiRequest(`/projects/${projectId}/handoff-email`, {method:'POST'});
      state(`Napotki so poslani na ${result.recipient || 'e-pošto uporabnika'}.`, true);
    } catch (err) {
      state(err.message);
    }
  }

  function sourceReady(card) {
    const text = card.textContent || '';
    return !/Repo:\s*še ni ustvarjen/i.test(text);
  }

  function enhanceCard(card) {
    if (!card) return;
    const projectId = card.dataset.project;
    if (!projectId) return;

    const ready = sourceReady(card);
    const mainActions = card.querySelector('.project-main .project-actions');
    const existingPreview = mainActions?.querySelector('[data-private-preview]');
    if (ready && mainActions && !existingPreview) {
      const preview = button('Private preview ↗', 'privatePreview', projectId);
      mainActions.insertBefore(preview, mainActions.firstChild);
    } else if (!ready) {
      existingPreview?.remove();
    }

    const handoffPanel = Array.from(card.querySelectorAll('.panel')).find(panel => /Predaja in koda/.test(panel.textContent || ''));
    const handoffActions = handoffPanel?.querySelector('.project-actions');
    const existingEmail = handoffActions?.querySelector('[data-handoff-email]');
    if (ready && handoffActions && !existingEmail) {
      const email = button('Pošlji napotke na e-mail', 'handoffEmail', projectId);
      handoffActions.appendChild(email);
    } else if (!ready) {
      existingEmail?.remove();
    }
  }

  function enhanceAll() {
    document.querySelectorAll('.project[data-project]').forEach(enhanceCard);
  }

  document.addEventListener('click', event => {
    const preview = event.target.closest('[data-private-preview]');
    if (preview) {
      event.preventDefault();
      openPreview(preview.dataset.privatePreview);
      return;
    }
    const email = event.target.closest('[data-handoff-email]');
    if (email) {
      event.preventDefault();
      sendHandoff(email.dataset.handoffEmail);
    }
  });

  const projects = document.getElementById('projects');
  if (projects) new MutationObserver(enhanceAll).observe(projects, {childList:true, subtree:true});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enhanceAll);
  else enhanceAll();
})();
