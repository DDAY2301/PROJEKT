(() => {
  const baseRequest = request;
  let sessionExpiryHandled = false;
  request = async function(path, options = {}) {
    try {
      return await baseRequest(path, options);
    } catch (e) {
      if (/invalid or expired token|missing bearer token/i.test(String(e?.message || ''))) {
        if (token) {
          token = '';
          localStorage.removeItem('pv_token');
        }
        if (!sessionExpiryHandled) {
          sessionExpiryHandled = true;
          updateAuthUi('Seja je potekla. Ponovno se prijavi.');
          status('PRIJAVA JE POTEKLA\nPonovno se prijavi. Vneseni podatki projekta ostanejo na strani.');
        }
      }
      throw e;
    }
  };

  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  const resetViewport = () => { if (!location.hash) window.scrollTo({top:0,left:0,behavior:'auto'}); };
  resetViewport();
  window.addEventListener('pageshow', resetViewport);

  const style = document.createElement('style');
  style.textContent = `
    .intro{padding:0!important}.preview{padding:0!important}.intro-main{padding-bottom:2rem!important;overflow:hidden}
    .proofs{display:flex!important;flex-wrap:wrap!important;gap:.55rem!important;margin-top:1.35rem!important;padding-top:1rem!important;border-top:1px solid rgba(255,255,255,.09)}
    .proofs span{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-height:2rem!important;padding:.4rem .72rem!important;border:1px solid rgba(255,255,255,.13)!important;border-radius:999px!important;background:rgba(255,255,255,.045)!important;color:#dce8e4!important;white-space:nowrap!important}
    .my-sites{padding:1rem;border:1px solid var(--line);border-radius:1.1rem;background:#fff;box-shadow:0 14px 40px rgba(16,41,35,.06)}
    .my-sites-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.65rem}.my-sites-head h2{margin:0;font-size:1.05rem}.my-sites-head span{padding:.24rem .48rem;border-radius:999px;background:#e6f0eb;color:var(--good);font-size:.62rem;font-weight:900}
    .my-sites-empty{padding:.9rem;border-radius:.78rem;background:#f0f4f2;color:var(--muted);font-size:.76rem;line-height:1.5}.my-sites-empty strong{display:block;margin-bottom:.15rem;color:var(--ink);font-size:.82rem}
    .published-site{display:grid;grid-template-columns:1fr auto;gap:.7rem;align-items:center;padding:.78rem;border:1px solid #cfe0d8;border-radius:.8rem;background:#f4faf7}.published-site strong{display:block;font-size:.83rem}.published-site small{display:block;margin-top:.12rem;color:var(--muted);font-size:.64rem}.site-actions{display:flex;gap:.4rem;flex-wrap:wrap;justify-content:flex-end}.site-actions a,.site-actions button{min-height:2.35rem!important;padding:.45rem .65rem!important;font-size:.7rem!important}
    .publish-warning{margin-top:.5rem;padding:.55rem .65rem;border-radius:.6rem;background:#fff3cd;color:#795b00;font-size:.68rem;line-height:1.45}
    .revision-card{display:none;margin-top:.85rem;padding:.9rem;border:1px solid var(--line);border-radius:.9rem;background:#f7faf8}.revision-card.visible{display:block}.revision-card h4{margin:0;font-size:.9rem}.revision-card p{margin:.25rem 0 .7rem;color:var(--muted);font-size:.72rem;line-height:1.45}
    .revision-card textarea{width:100%;min-height:5.8rem;padding:.7rem .75rem;border:1px solid #b8c7c0;border-radius:.72rem;background:#fff;resize:vertical;font:inherit;font-size:.78rem}.revision-actions{display:flex;gap:.5rem;margin-top:.55rem;flex-wrap:wrap}.revision-actions button:disabled{opacity:.55;cursor:not-allowed}
    .revision-history{display:grid;gap:.35rem;margin-top:.7rem}.revision-item{padding:.55rem .62rem;border-radius:.6rem;background:#edf3f0;font-size:.68rem}.revision-item strong{display:block;color:var(--good);font-size:.62rem;text-transform:uppercase}.revision-item span{display:block;margin-top:.12rem;color:#49605a}
    .live-mini{display:none;margin-top:.75rem;border:1px solid var(--line);border-radius:.75rem;overflow:hidden;background:#fff}.live-mini.visible{display:block}.live-mini-top{display:flex;align-items:center;justify-content:space-between;padding:.5rem .6rem;border-bottom:1px solid var(--line);font-size:.65rem;font-weight:800}.live-mini iframe{display:block;width:100%;height:240px;border:0;background:#fff}
    @media(max-width:760px){.proofs{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important}.proofs span{white-space:normal!important;text-align:center!important}.published-site{grid-template-columns:1fr}.site-actions{justify-content:flex-start}}
    @media(max-width:460px){.proofs{grid-template-columns:1fr!important}}
  `;
  document.head.appendChild(style);

  const maincol = document.querySelector('.maincol');
  const actions = document.getElementById('resultActions');
  if (!actions || !maincol) return;

  const sitesCard = document.createElement('section');
  sitesCard.className = 'my-sites';
  sitesCard.innerHTML = '<div class="my-sites-head"><h2>Moje strani</h2><span>VEDNO DOSTOPNO</span></div><div id="mySitesBody" class="my-sites-empty"><strong>Preverjam tvoje strani …</strong></div>';
  maincol.insertBefore(sitesCard, maincol.firstElementChild);
  const mySitesBody = document.getElementById('mySitesBody');

  const escapeHtml = value => String(value || '').replace(/[&<>\'\"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  function auditOf(project) {
    if (project?.last_audit && typeof project.last_audit === 'object') return project.last_audit;
    try { return JSON.parse(project?.last_audit_json || '{}'); } catch { return {}; }
  }
  function needsPublishRecovery(project) {
    const audit = auditOf(project);
    if (audit.publish_action_required === 'github_pages_permission') return true;
    return (audit.issues || []).some(i => i.code === 'GITHUB_PAGES_PERMISSION' || (i.code === 'BUILD_FAILED' && /public website publishing|github pages/i.test(i.message || '')));
  }
  function renderEmpty(message) {
    mySitesBody.className = 'my-sites-empty';
    mySitesBody.innerHTML = `<strong>Še nimaš objavljene strani.</strong>${escapeHtml(message || 'Izpolni projekt in klikni “Začni izdelavo”.')}`;
  }

  async function publishOnly(projectId, button) {
    if (!token) return status('Najprej se ponovno prijavi.');
    button.disabled = true;
    button.textContent = 'Objavljam ...';
    try {
      const result = await request(`/projects/${projectId}/publish`, {method:'POST'});
      activeProjectId = projectId;
      updatePipeline('publishing');
      status(`DOKONČUJEM OBJAVO\nProjekt: ${projectId}\nRepo: ${result.repo_name || 'preverjam'}\n\nGeneriranje se ne ponavlja.`);
      for (let i = 0; i < 45; i++) {
        await sleep(3000);
        const project = await request(`/projects/${projectId}`);
        updatePipeline(project.status);
        if (['ready','needs_review','failed'].includes(project.status)) {
          await refreshMySites();
          if (project.repo_name) setResultLinks(project.repo_name);
          const audit = auditOf(project);
          if (audit.public_live) status(`OBJAVA KONČANA\n${audit.public_url || finalSiteUrl(project.repo_name)}`);
          else if (needsPublishRecovery(project)) status('JAVNA OBJAVA ŠE NI DOVOLJENA\nGitHub token potrebuje Pages: Read and write ter Administration: Read and write.');
          return;
        }
      }
      status('Objava še poteka. Osveži “Moje strani” čez nekaj trenutkov.');
    } catch (e) {
      status(`OBJAVA NI USPELA\n${e.message}`);
    } finally {
      button.disabled = false;
      button.textContent = 'Dokončaj objavo →';
    }
  }

  function renderProject(project) {
    const audit = auditOf(project);
    const repo = project.repo_name || '';
    const url = audit.public_url || (repo ? finalSiteUrl(repo) : '');
    const live = audit.public_live === true;
    const recovery = needsPublishRecovery(project);
    mySitesBody.className = '';
    mySitesBody.innerHTML = `
      <div class="published-site">
        <div>
          <strong>${escapeHtml(project.name || repo || 'Spletna stran')}</strong>
          <small>${live ? escapeHtml(url) : repo ? `Koda pripravljena: ${escapeHtml(repo)}` : 'Koda je pripravljena za dokončanje objave.'}</small>
          ${recovery ? '<div class="publish-warning">Stran je izdelana, vendar trenutni GitHub token nima dovoljenja za vklop GitHub Pages. Po popravku dovoljenj ponovno zaženi servis in klikni “Dokončaj objavo”.</div>' : ''}
        </div>
        <div class="site-actions">
          ${live ? `<a class="button small" href="${escapeHtml(url)}" target="_blank" rel="noopener">Odpri stran ↗</a><button class="button secondary small" id="editPublishedSite" type="button">Uredi</button>` : ''}
          ${recovery ? '<button class="button small" id="publishExistingSite" type="button">Dokončaj objavo →</button>' : ''}
          ${repo ? `<a class="button secondary small" href="https://github.com/${GITHUB_OWNER}/${encodeURIComponent(repo)}" target="_blank" rel="noopener">GitHub ↗</a>` : ''}
        </div>
      </div>`;
    document.getElementById('publishExistingSite')?.addEventListener('click', e => publishOnly(project.id, e.currentTarget));
    document.getElementById('editPublishedSite')?.addEventListener('click', () => {
      const revision = document.getElementById('revisionCard');
      if (revision) {
        activeProjectId = project.id;
        revision.classList.add('visible');
        revision.scrollIntoView({behavior:'smooth', block:'center'});
      }
    });
  }

  async function refreshMySites() {
    if (!token) {
      mySitesBody.className = 'my-sites-empty';
      mySitesBody.innerHTML = '<strong>Prijavi se za dostop do svojih strani.</strong>Po prijavi bo tukaj prikazana zadnja stran.';
      return;
    }
    try {
      const projects = await request('/projects');
      if (!projects.length) return renderEmpty();
      const candidate = projects.find(p => p.repo_name || needsPublishRecovery(p)) || projects[0];
      activeProjectId = candidate.id;
      if (candidate.repo_name || needsPublishRecovery(candidate)) renderProject(candidate);
      else renderEmpty(`Zadnji projekt ima stanje “${candidate.status || 'v pripravi'}”.`);
    } catch (e) {
      mySitesBody.className = 'my-sites-empty';
      mySitesBody.innerHTML = `<strong>Strani trenutno ni mogoče preveriti.</strong>${escapeHtml(e.message)}`;
    }
  }

  document.querySelectorAll('.pkg').forEach(btn => btn.addEventListener('click', () => {
    const name = btn.dataset.package;
    const note = document.getElementById('pageLimit');
    if (note) note.textContent = `✓ Izbran paket ${name} — največ ${packageLimits[name]} strani.`;
  }));

  const host = actions.closest('.side-card') || actions.parentElement;
  const card = document.createElement('div');
  card.id = 'revisionCard';
  card.className = 'revision-card';
  card.innerHTML = `
    <h4>Spremeni objavljeno stran</h4>
    <p>Opiši spremembo z navadnim stavkom. Sistem spremeni potrebne datoteke, preveri rezultat in ponovno objavi isto povezavo.</p>
    <textarea id="revisionInstruction" maxlength="3000" placeholder="npr. Hero naj bo bolj premium. CTA naj bo bolj izrazit. Dodaj kratek FAQ."></textarea>
    <div class="revision-actions"><button class="button small" id="applyRevision" type="button">Izvedi spremembo →</button><button class="button secondary small" id="refreshLivePreview" type="button">Osveži predogled</button></div>
    <div class="revision-history" id="revisionHistory"></div>
    <div class="live-mini" id="liveMini"><div class="live-mini-top"><span>Objavljena stran</span><a id="liveMiniLink" target="_blank" rel="noopener">Odpri ↗</a></div><iframe id="liveMiniFrame" title="Predogled objavljene strani" loading="lazy"></iframe></div>`;
  host.appendChild(card);

  const instruction = document.getElementById('revisionInstruction');
  const apply = document.getElementById('applyRevision');
  const refresh = document.getElementById('refreshLivePreview');
  const historyEl = document.getElementById('revisionHistory');
  const liveMini = document.getElementById('liveMini');
  const liveFrame = document.getElementById('liveMiniFrame');
  const liveLink = document.getElementById('liveMiniLink');
  let currentRepo = '';

  function refreshPreview() {
    if (!currentRepo) return;
    const url = finalSiteUrl(currentRepo);
    liveLink.href = url;
    liveFrame.src = `${url}?pv=${Date.now()}`;
    liveMini.classList.add('visible');
  }
  async function loadHistory() {
    if (!activeProjectId || !token) return;
    try {
      const items = await request(`/projects/${activeProjectId}/revisions`);
      historyEl.innerHTML = items.slice(0,4).map(item => `<div class="revision-item"><strong>${escapeHtml(item.status)}</strong><span>${escapeHtml(item.instruction)}</span></div>`).join('');
    } catch {}
  }
  function showForRepo(repoName) {
    if (!repoName) return;
    currentRepo = repoName;
    card.classList.add('visible');
    refreshPreview();
    loadHistory();
    refreshMySites();
  }

  const originalSetResultLinks = setResultLinks;
  setResultLinks = function(repoName) { originalSetResultLinks(repoName); showForRepo(repoName); };
  stageIndex.revising = 2;
  statusLabels.revising = 'Urejanje objavljene strani';
  refresh.addEventListener('click', refreshPreview);

  apply.addEventListener('click', async () => {
    const text = instruction.value.trim();
    if (!activeProjectId) return status('Najprej dokončaj osnovno spletno stran.');
    if (text.length < 3) return status('Opiši spremembo, ki jo želiš.');
    apply.disabled = true;
    apply.textContent = 'Izvajam ...';
    try {
      await request(`/projects/${activeProjectId}/revise`, {method:'POST', body:JSON.stringify({instruction:text})});
      status(`SPREMEMBA SPREJETA\nProjekt: ${activeProjectId}`);
      updatePipeline('revising');
      instruction.value = '';
      watch(activeProjectId);
      await loadHistory();
    } catch (e) {
      status(`SPREMEMBA NI USPELA\n${e.message}`);
    } finally {
      apply.disabled = false;
      apply.textContent = 'Izvedi spremembo →';
    }
  });

  document.getElementById('logout')?.addEventListener('click', () => setTimeout(refreshMySites,0));
  document.getElementById('login')?.addEventListener('click', () => { sessionExpiryHandled=false; setTimeout(refreshMySites,900); });
  document.getElementById('register')?.addEventListener('click', () => { sessionExpiryHandled=false; setTimeout(refreshMySites,900); });
  refreshMySites();
})();