(() => {
  const ACTIVE_KEY = 'pv_active_project_v2';
  let polling = false;
  let lastProjectId = '';

  function ensureStyles() {
    if (document.getElementById('pvPreviewStyles')) return;
    const style = document.createElement('style');
    style.id = 'pvPreviewStyles';
    style.textContent = `
      .pv-preview-modal{position:fixed;inset:0;z-index:9999;display:none;background:rgba(3,18,14,.78);backdrop-filter:blur(10px);padding:3vh 3vw}.pv-preview-modal.open{display:grid;grid-template-rows:auto 1fr}.pv-preview-bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;background:#071d17;color:#fff;border-radius:18px 18px 0 0;padding:.8rem 1rem}.pv-preview-bar strong{font-size:.9rem}.pv-preview-bar span{color:#a7bdb4;font-size:.7rem}.pv-preview-close{border:1px solid rgba(255,255,255,.22);background:transparent;color:#fff;border-radius:999px;padding:.45rem .7rem;cursor:pointer}.pv-preview-frame{width:100%;height:100%;border:0;background:#fff;border-radius:0 0 18px 18px}.pv-preview-loading{display:grid;place-items:center;background:#fff;color:#23463c;border-radius:0 0 18px 18px;font-weight:750}
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    ensureStyles();
    let modal = document.getElementById('pvPreviewModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pvPreviewModal';
    modal.className = 'pv-preview-modal';
    modal.innerHTML = `<div class="pv-preview-bar"><div><strong>Private preview pred plačilom</strong><br><span>To je dejanska generirana koda iz zasebnega GitHub repozitorija.</span></div><button class="pv-preview-close" type="button">Zapri ×</button></div><div class="pv-preview-loading" id="pvPreviewLoading">Pripravljam varen predogled …</div><iframe class="pv-preview-frame" id="pvPreviewFrame" title="Predogled generirane spletne strani" style="display:none"></iframe>`;
    document.body.appendChild(modal);
    const close = () => {
      modal.classList.remove('open');
      const frame = document.getElementById('pvPreviewFrame');
      if (frame) { frame.src = 'about:blank'; frame.style.display = 'none'; }
      const load = document.getElementById('pvPreviewLoading');
      if (load) load.style.display = 'grid';
    };
    modal.querySelector('.pv-preview-close')?.addEventListener('click', close);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.classList.contains('open')) close(); });
    return modal;
  }

  async function openPreview(projectId) {
    const modal = ensureModal();
    modal.classList.add('open');
    const loading = document.getElementById('pvPreviewLoading');
    const frame = document.getElementById('pvPreviewFrame');
    if (loading) { loading.textContent = 'Pripravljam varen predogled …'; loading.style.display = 'grid'; }
    if (frame) frame.style.display = 'none';
    try {
      const session = await request(`/projects/${projectId}/preview-session`, {method:'POST'});
      if (!session.url) throw new Error('Preview URL ni bil ustvarjen.');

      const previewUrl = new URL(session.url, location.href);
      const mixedLocal = location.protocol === 'https:' && previewUrl.protocol === 'http:';
      if (mixedLocal) {
        modal.classList.remove('open');
        window.open(previewUrl.href, '_blank', 'noopener');
        status('PRIVATE PREVIEW JE PRIPRAVLJEN\nKer lokalni API teče prek HTTP, se predogled odpre v novem zavihku. V produkciji z HTTPS API se odpre neposredno v workspaceu.');
        return;
      }

      if (frame) {
        frame.onload = () => { if (loading) loading.style.display='none'; frame.style.display='block'; };
        frame.src = previewUrl.href;
      }
    } catch (e) {
      if (loading) loading.textContent = `Predogled ni na voljo: ${e.message}`;
    }
  }

  async function sendHandoff(projectId) {
    try {
      status('POŠILJAM NAPOTKE\nPripravljam source/deployment navodila in e-mail …');
      const result = await request(`/projects/${projectId}/handoff-email`, {method:'POST'});
      status(`NAPOTKI POSLANI\nPrejemnik: ${result.recipient || 'uporabnik'}\nV e-mailu so navodila za source, njihov GitHub repo in GitHub Pages deployment.`);
    } catch (e) {
      status(`E-MAIL NI POSLAN\n${e.message}\n\nNavodila ostanejo na voljo v dashboardu.`);
    }
  }

  function ensureActions(project) {
    const actions = document.getElementById('resultActions');
    if (!actions || !project?.repo_name) return;
    const audit = project.last_audit || {};
    if (!audit.repository_ready && !['repository_ready','ready_for_payment','payment_pending','publishing','ready','needs_review'].includes(project.status)) return;
    actions.classList.add('visible');

    let preview = document.getElementById('privatePreviewButton');
    if (!preview) {
      preview = document.createElement('button');
      preview.id = 'privatePreviewButton';
      preview.type = 'button';
      preview.className = 'button secondary small';
      actions.insertBefore(preview, actions.firstChild);
    }
    preview.textContent = project.status === 'ready_for_payment' ? 'Predogled pred plačilom ↗' : 'Private preview ↗';
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
  }

  async function poll() {
    if (polling || !token) return;
    const id = activeProjectId || localStorage.getItem(ACTIVE_KEY) || '';
    if (!id) return;
    polling = true;
    try {
      const project = await request(`/projects/${id}`);
      lastProjectId = id;
      ensureActions(project);
    } catch {
      // Main builder flow owns error/status reporting; this enhancement stays quiet.
    } finally {
      polling = false;
    }
  }

  ensureModal();
  setInterval(poll, 2500);
  setTimeout(poll, 1000);
  window.pvOpenPrivatePreview = projectId => openPreview(projectId || lastProjectId || activeProjectId);
})();
