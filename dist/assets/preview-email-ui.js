(() => {
  const ACTIVE_KEY = 'pv_active_project_v2';
  let polling = false;
  let lastProjectId = '';
  let buildStarting = false;
  let buildWatcher = false;

  function ensureStyles() {
    if (document.getElementById('pvPreviewStyles')) return;
    const style = document.createElement('style');
    style.id = 'pvPreviewStyles';
    style.textContent = `
      .pv-preview-modal{position:fixed;inset:0;z-index:9999;display:none;background:rgba(3,18,14,.78);backdrop-filter:blur(10px);padding:3vh 3vw}.pv-preview-modal.open{display:grid;grid-template-rows:auto 1fr}.pv-preview-bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;background:#071d17;color:#fff;border-radius:18px 18px 0 0;padding:.8rem 1rem}.pv-preview-bar strong{font-size:.9rem}.pv-preview-bar span{color:#a7bdb4;font-size:.7rem}.pv-preview-close{border:1px solid rgba(255,255,255,.22);background:transparent;color:#fff;border-radius:999px;padding:.45rem .7rem;cursor:pointer}.pv-preview-frame{width:100%;height:100%;border:0;background:#fff;border-radius:0 0 18px 18px}.pv-preview-loading{display:grid;place-items:center;background:#fff;color:#23463c;border-radius:0 0 18px 18px;font-weight:750}.pv-pay-action{background:var(--lime)!important;color:var(--ink)!important;border-color:var(--lime)!important}.pv-pay-action[disabled]{opacity:.65;cursor:wait}
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

  function packagePrice(name) {
    const pkg = billingConfig?.packages?.[name] || {};
    return pkg.configured && typeof pkg.unit_amount === 'number' ? money(pkg.unit_amount, pkg.currency) : '';
  }

  async function beginCheckout(project) {
    const button = document.getElementById('payPublishButton');
    try {
      if (button) { button.disabled = true; button.textContent = 'Odpiram plačilo …'; }
      status('STRAN JE PRIPRAVLJENA\nOdpiram varno Stripe plačilo. Po uspešnem plačilu bo objavljena točno pregledana verzija.');
      const checkout = await request('/billing/checkout', {method:'POST', body:JSON.stringify({project_id:project.id})});
      if (checkout.paid) {
        status('PLAČILO JE ŽE POTRJENO\nObjavljam pregledano verzijo spletne strani.');
        watchProject(project.id);
        return;
      }
      if (!checkout.checkout_url) throw new Error('Stripe Checkout povezava ni bila ustvarjena.');
      window.location.assign(checkout.checkout_url);
    } catch (e) {
      if (button) { button.disabled = false; button.textContent = 'Plačaj in objavi →'; }
      status(`PLAČILA NI BILO MOGOČE ODPRETI\n${e.message}`);
    }
  }

  function ensurePaymentAction(project) {
    const actions = document.getElementById('resultActions');
    if (!actions) return;
    let pay = document.getElementById('payPublishButton');
    if (project.status !== 'ready_for_payment' && project.status !== 'payment_pending') {
      pay?.remove();
      return;
    }
    actions.classList.add('visible');
    if (!pay) {
      pay = document.createElement('button');
      pay.id = 'payPublishButton';
      pay.type = 'button';
      pay.className = 'button small pv-pay-action';
      actions.insertBefore(pay, actions.firstChild);
    }
    const price = packagePrice(project.package);
    if (project.status === 'payment_pending') {
      pay.disabled = true;
      pay.textContent = 'Plačilo v teku …';
    } else {
      pay.disabled = false;
      pay.textContent = price ? `Plačaj ${price} in objavi →` : 'Plačaj in objavi →';
      pay.onclick = () => beginCheckout(project);
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
    ensurePaymentAction(project);
  }

  function postBuildStatus(project) {
    const issues = project.last_audit?.issues || [];
    const severe = issues.filter(x => ['critical','high'].includes(x.severity)).length;
    const qa = project.last_audit?.visual_qa || {};
    const lines = [
      statusLabels?.[project.status] || project.status,
      `Projekt: ${project.id}`,
      `GitHub repo: ${project.repo_name || 'še ni ustvarjen'}`,
      `Slike: ${project.last_audit?.uploaded_images ?? '—'}`,
      `Visual QA: ${qa.score ?? '—'}${qa.render_count ? ` / ${qa.render_count} renderjev` : ''}`,
      `Najdene težave: ${issues.length}${severe ? ` (${severe} pomembnih)` : ''}`
    ];
    if (project.status === 'ready_for_payment') lines.push('', 'STRAN JE IZDELANA IN PREVERJENA.', 'Najprej jo odpri v zasebnem predogledu. Plačilo nato sprosti isto pregledano verzijo v javno objavo.');
    if (project.status === 'payment_pending') lines.push('', 'Stripe Checkout je odprt oziroma plačilo še ni potrjeno.');
    if (project.status === 'publishing') lines.push('', 'Plačilo oziroma testni bypass je potrjen. Stran se objavlja.');
    if (project.last_audit?.public_live && project.last_audit?.public_url) lines.push(`Javna stran: ${project.last_audit.public_url}`);
    if (issues.length) lines.push('', ...issues.slice(0,6).map(x => `• ${x.message}`));
    return lines.join('\n');
  }

  async function watchProject(id) {
    if (!id || buildWatcher) return;
    buildWatcher = true;
    try {
      for (let i = 0; i < 480; i++) {
        const project = await request(`/projects/${id}`);
        activeProjectId = id;
        localStorage.setItem(ACTIVE_KEY, id);
        updatePipeline(project.status);
        ensureActions(project);
        status(postBuildStatus(project));

        if (project.status === 'ready_for_payment') return;
        if (['ready','needs_review','failed'].includes(project.status)) {
          if (project.repo_name) document.getElementById('resultActions')?.classList.add('visible');
          return;
        }
        await sleep(3000);
      }
      status('IZDELAVA ŠE VEDNO TEČE\nProjekt je shranjen. Status lahko preveriš v Moji projekti.');
    } catch (e) {
      status(`PREVERJANJE PROJEKTA NI USPELO\n${e.message}`);
    } finally {
      buildWatcher = false;
      buildStarting = false;
      const generate = document.getElementById('generate');
      if (generate) { generate.disabled = false; generate.textContent = 'Začni izdelavo →'; }
    }
  }

  async function startPostBuildFlow(event) {
    event?.preventDefault();
    event?.stopImmediatePropagation();
    if (buildStarting) return;
    const generate = document.getElementById('generate');
    if (!token) {
      status('IZDELAVA JE BLOKIRANA\nNajprej se registriraj ali prijavi.');
      return;
    }
    buildStarting = true;
    if (generate) { generate.disabled = true; generate.textContent = 'Začenjam …'; }
    try {
      validateProject();
      const healthy = await checkHealth(false);
      if (!healthy) throw new Error('Storitev trenutno ni dosegljiva.');
      resetPipeline();
      updatePipeline('queued');
      document.getElementById('resultActions')?.classList.remove('visible');
      status('SHRANJUJEM BRIEF\nProjekt pripravljam brez zagona, da se najprej varno naložijo vse fotografije.');

      const createBody = {...payload(), defer_build:true};
      const created = await request('/projects', {method:'POST', body:JSON.stringify(createBody)});
      activeProjectId = created.id;
      localStorage.setItem(ACTIVE_KEY, created.id);

      await uploadSelectedImages(created.id);
      status(`BRIEF IN SLIKE SO SHRANJENI\nProjekt: ${created.id}\nSlike: ${selectedImages.length}\nZačenjam izdelavo in Visual QA.`);
      await request(`/projects/${created.id}/build`, {method:'POST'});
      watchProject(created.id);
    } catch (e) {
      buildStarting = false;
      if (generate) { generate.disabled = false; generate.textContent = 'Začni izdelavo →'; }
      status(`IZDELAVA NI ZAGNANA\n${e.message}`);
    }
  }

  function installPostBuildFlow() {
    if (typeof stageIndex === 'object') {
      stageIndex.visual_qa = 3;
      stageIndex.repository_ready = 4;
      stageIndex.ready_for_payment = 5;
      stageIndex.payment_pending = 5;
      stageIndex.publishing = 5;
    }
    if (typeof statusLabels === 'object') {
      statusLabels.visual_qa = 'Vizualni QA: desktop, tablet, mobile';
      statusLabels.repository_ready = 'Končna koda je pripravljena';
      statusLabels.ready_for_payment = 'Pripravljeno za predogled in plačilo';
      statusLabels.payment_pending = 'Plačilo v teku';
      statusLabels.publishing = 'Objava spletne strani';
    }

    if (typeof updateCheckoutHint === 'function') {
      updateCheckoutHint = function() {
        const hint = document.getElementById('checkoutHint');
        const packageEl = document.getElementById('package');
        if (!hint || !packageEl) return;
        const name = packageEl.value;
        const pkg = billingConfig?.packages?.[name] || {};
        if (pkg.configured && typeof pkg.unit_amount === 'number') {
          hint.innerHTML = `<strong>Najprej izdelava in zasebni predogled.</strong> Plačilo ${money(pkg.unit_amount, pkg.currency)} se odpre šele po uspešnem buildu in Visual QA; nato se objavi ista pregledana verzija.`;
        } else if (billingConfig?.enabled) {
          hint.innerHTML = `<strong>Paket ${name} še nima nastavljene Stripe cene.</strong> Izdelava lahko teče, javna objava pa bo zahtevala nastavitev plačila.`;
        } else {
          hint.innerHTML = '<strong>Testni način:</strong> stran se najprej izdela in preveri; plačilo trenutno ni zahtevano.';
        }
      };
      updateCheckoutHint();
    }

    const generate = document.getElementById('generate');
    generate?.addEventListener('click', startPostBuildFlow, true);

    const requested = new URLSearchParams(location.search).get('project');
    if (requested) localStorage.setItem(ACTIVE_KEY, requested);
    const remembered = requested || localStorage.getItem(ACTIVE_KEY) || '';
    if (remembered && token && API) setTimeout(() => watchProject(remembered), 900);
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
  installPostBuildFlow();
  setInterval(poll, 2500);
  setTimeout(poll, 1000);
  window.pvOpenPrivatePreview = projectId => openPreview(projectId || lastProjectId || activeProjectId);
})();