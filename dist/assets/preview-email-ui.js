(() => {
  // UI-only enhancement. The payment-flow-v2.js module owns creation, polling,
  // payment status and the sole build watcher. Never spawn a second build flow.
  let lastProjectId = '';

  function ensureModal() {
    let modal = document.getElementById('pvPreviewModal');
    if (modal) return modal;
    const css = document.createElement('style');
    css.textContent = '.pv-preview-modal{position:fixed;inset:0;z-index:9999;display:none;background:rgba(3,18,14,.78);padding:3vh 3vw}.pv-preview-modal.open{display:grid;grid-template-rows:auto 1fr}.pv-preview-bar{display:flex;justify-content:space-between;align-items:center;gap:1rem;background:#071d17;color:#fff;border-radius:18px 18px 0 0;padding:.8rem 1rem}.pv-preview-bar span{color:#a7bdb4;font-size:.7rem}.pv-preview-close{border:1px solid #8ca69b;background:transparent;color:#fff;border-radius:99px;padding:.45rem .7rem;cursor:pointer}.pv-preview-frame{width:100%;height:100%;border:0;background:#fff;border-radius:0 0 18px 18px}.pv-preview-loading{display:grid;place-items:center;background:#fff;color:#23463c;border-radius:0 0 18px 18px;padding:1rem}';
    css.id = 'pvPreviewStyles';
    document.head.appendChild(css);
    modal = document.createElement('div');
    modal.id = 'pvPreviewModal';
    modal.className = 'pv-preview-modal';
    modal.innerHTML = '<div class="pv-preview-bar"><div><strong>Zasebni predogled</strong><div><span>Podpisana različica iz GitHub repozitorija</span></div></div><button class="pv-preview-close" type="button">Zapri ×</button></div><div class="pv-preview-loading" id="pvPreviewLoading">Pripravljam predogled …</div><iframe class="pv-preview-frame" id="pvPreviewFrame" title="Zasebni predogled spletne strani" sandbox="allow-scripts allow-forms" referrerpolicy="no-referrer" style="display:none"></iframe>';
    document.body.appendChild(modal);
    function close() {
      modal.classList.remove('open');
      const frame = document.getElementById('pvPreviewFrame');
      if (frame) { frame.src = 'about:blank'; frame.style.display = 'none'; }
    }
    modal.querySelector('.pv-preview-close')?.addEventListener('click', close);
    modal.addEventListener('click', event => { if (event.target === modal) close(); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && modal.classList.contains('open')) close();
    });
    return modal;
  }

  async function openPreview(projectId) {
    if (!projectId) {
      status('Izberi projekt, preden odpreš zasebni predogled.');
      return;
    }
    const modal = ensureModal();
    modal.classList.add('open');
    const loading = document.getElementById('pvPreviewLoading');
    const frame = document.getElementById('pvPreviewFrame');
    if (loading) { loading.style.display = 'grid'; loading.textContent = 'Preverjam dostop do zasebne različice …'; }
    if (frame) { frame.style.display = 'none'; frame.src = 'about:blank'; }
    try {
      const session = await request(`/projects/${encodeURIComponent(projectId)}/preview-session`, {method:'POST'});
      if (!session.url) throw new Error('Strežnik ni vrnil povezave za predogled.');
      const url = new URL(session.url, location.href);
      const trustedOrigin = new URL(API, location.href).origin;
      if (url.origin !== trustedOrigin || !url.pathname.startsWith('/preview/')) {
        throw new Error('Predogled ima nepričakovan izvor; povezava je zavrnjena.');
      }
      if (location.protocol === 'https:' && url.protocol === 'http:') {
        modal.classList.remove('open');
        window.open(url.href, '_blank', 'noopener,noreferrer');
        status('Zasebni predogled se odpre v ločenem zavihku, ker je lokalni API HTTP.');
        return;
      }
      if (frame) {
        frame.onload = () => {
          if (loading) loading.style.display = 'none';
          frame.style.display = 'block';
        };
        frame.src = url.href;
      }
    } catch (err) {
      if (loading) {
        loading.style.display = 'grid';
        loading.textContent = 'Predogled ni dosegljiv: ' + err.message +
          ' Preveri, ali zasebni GitHub repozitorij še obstaja in ali ima trenutni PAT pravico Contents: Read.';
      }
    }
  }

  async function sendHandoff(projectId) {
    try {
      status('Pošiljam navodila za prevzem spletne strani …');
      const result = await request(`/projects/${encodeURIComponent(projectId)}/handoff-email`, {method:'POST'});
      status('Napotki poslani: ' + (result.recipient || 'prejemnik'));
    } catch (error) {
      status('E-pošte ni mogoče poslati: ' + error.message);
    }
  }

  function syncActions(project) {
    if (!project || !project.id) return;
    lastProjectId = project.id;
    const actions = document.getElementById('resultActions');
    if (!actions || !project.repo_name) return;
    if (!['repository_ready','ready_for_payment','payment_pending','publishing','ready','needs_review']
        .includes(project.status)) return;
    actions.classList.add('visible');

    let preview = document.getElementById('privatePreviewButton');
    if (!preview) {
      preview = document.createElement('button');
      preview.id = 'privatePreviewButton';
      preview.type = 'button';
      preview.className = 'button secondary small';
      actions.insertBefore(preview, actions.firstChild);
    }
    preview.textContent = 'Private preview ↗';
    preview.onclick = () => openPreview(project.id);

    let email = document.getElementById('handoffEmailButton');
    if (!email) {
      email = document.createElement('button');
      email.id = 'handoffEmailButton';
      email.type = 'button';
      email.className = 'button secondary small';
      email.textContent = 'Pošlji napotke na e-mail';
      actions.appendChild(email);
    }
    email.onclick = () => sendHandoff(project.id);
    // Never add a second pay button; V12 owns the QA/payment state.
  }

  window.pvSyncProjectActions = syncActions;
  window.pvOpenPrivatePreview = id => openPreview(id || lastProjectId || activeProjectId);

  // One bootstrap read for an existing terminal project. Active project
  // monitoring is exclusively performed by payment-flow-v2.js.
  setTimeout(async () => {
    if (!token || !API) return;
    const id = new URLSearchParams(location.search).get('project') ||
      localStorage.getItem('pv_active_project_v2');
    if (!id) return;
    try {
      syncActions(await request(`/projects/${encodeURIComponent(id)}`));
    } catch { /* Missing or inaccessible project: leave controls hidden. */ }
  }, 1800);
})();
