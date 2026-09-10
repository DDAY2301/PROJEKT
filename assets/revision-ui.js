(() => {
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  const resetWorkspaceViewport = () => {
    if (!location.hash) window.scrollTo({top: 0, left: 0, behavior: 'auto'});
  };
  resetWorkspaceViewport();
  window.addEventListener('pageshow', resetWorkspaceViewport);
  window.addEventListener('load', () => setTimeout(resetWorkspaceViewport, 0));

  const style = document.createElement('style');
  style.textContent = `
    .intro{padding:0!important}.preview{padding:0!important}
    .intro-main{padding-bottom:2rem!important;overflow:hidden}
    .proofs{display:flex!important;flex-wrap:wrap!important;align-items:center!important;gap:.55rem!important;margin-top:1.35rem!important;padding-top:1rem!important;padding-bottom:.1rem!important;border-top:1px solid rgba(255,255,255,.09)}
    .proofs span{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-height:2rem!important;padding:.4rem .72rem!important;border:1px solid rgba(255,255,255,.13)!important;border-radius:999px!important;background:rgba(255,255,255,.045)!important;color:#dce8e4!important;line-height:1.15!important;white-space:nowrap!important}
    @media(max-width:760px){.proofs{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important}.proofs span{white-space:normal!important;text-align:center!important}}
    @media(max-width:460px){.proofs{grid-template-columns:1fr!important}}
    .my-sites{padding:1rem;border:1px solid var(--line);border-radius:1.1rem;background:#fff;box-shadow:0 14px 40px rgba(16,41,35,.06)}
    .my-sites-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.65rem}.my-sites-head h2{margin:0;font-size:1.05rem}.my-sites-head span{padding:.24rem .48rem;border-radius:999px;background:#e6f0eb;color:var(--good);font-size:.62rem;font-weight:900}
    .my-sites-empty{padding:.9rem;border-radius:.78rem;background:#f0f4f2;color:var(--muted);font-size:.76rem;line-height:1.5}.my-sites-empty strong{display:block;margin-bottom:.15rem;color:var(--ink);font-size:.82rem}
    .published-site{display:grid;grid-template-columns:1fr auto;gap:.7rem;align-items:center;padding:.78rem;border:1px solid #cfe0d8;border-radius:.8rem;background:#f4faf7}.published-site strong{display:block;font-size:.83rem}.published-site small{display:block;margin-top:.1rem;color:var(--muted);font-size:.64rem}.site-actions{display:flex;gap:.4rem;flex-wrap:wrap;justify-content:flex-end}.site-actions a,.site-actions button{min-height:2.35rem!important;padding:.45rem .65rem!important;font-size:.7rem!important}
    .revision-card{display:none;margin-top:.85rem;padding:.9rem;border:1px solid var(--line);border-radius:.9rem;background:#f7faf8}
    .revision-card.visible{display:block}.revision-card h4{margin:0;font-size:.9rem}.revision-card p{margin:.25rem 0 .7rem;color:var(--muted);font-size:.72rem;line-height:1.45}
    .revision-card textarea{width:100%;min-height:5.8rem;padding:.7rem .75rem;border:1px solid #b8c7c0;border-radius:.72rem;background:#fff;resize:vertical;font:inherit;font-size:.78rem}
    .revision-card textarea:focus{outline:0;border-color:var(--green);box-shadow:0 0 0 4px rgba(18,63,53,.08)}
    .revision-actions{display:flex;align-items:center;gap:.5rem;margin-top:.55rem;flex-wrap:wrap}.revision-actions button:disabled{opacity:.55;cursor:not-allowed}
    .revision-history{display:grid;gap:.35rem;margin-top:.7rem}.revision-item{padding:.55rem .62rem;border-radius:.6rem;background:#edf3f0;font-size:.68rem}.revision-item strong{display:block;color:var(--green);font-size:.62rem;text-transform:uppercase;letter-spacing:.06em}.revision-item span{display:block;margin-top:.12rem;color:#49605a}
    .live-mini{display:none;margin-top:.75rem;border:1px solid var(--line);border-radius:.75rem;overflow:hidden;background:#fff}.live-mini.visible{display:block}.live-mini-top{display:flex;align-items:center;justify-content:space-between;padding:.5rem .6rem;border-bottom:1px solid var(--line);font-size:.65rem;font-weight:800}.live-mini iframe{display:block;width:100%;height:240px;border:0;background:#fff}
    @media(max-width:720px){.published-site{grid-template-columns:1fr}.site-actions{justify-content:flex-start}}
  `;
  document.head.appendChild(style);

  const maincol = document.querySelector('.maincol');
  const actions = document.getElementById('resultActions');
  if (!actions || !maincol) return;

  const sitesCard = document.createElement('section');
  sitesCard.className = 'my-sites';
  sitesCard.id = 'mySites';
  sitesCard.innerHTML = `
    <div class="my-sites-head"><h2>Moje strani</h2><span>VEDNO DOSTOPNO</span></div>
    <div id="mySitesBody" class="my-sites-empty"><strong>Preverjam tvoje strani …</strong>Po prijavi se tukaj pokaže zadnja objavljena stran.</div>
  `;
  maincol.insertBefore(sitesCard, maincol.firstElementChild);
  const mySitesBody = document.getElementById('mySitesBody');

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function renderEmptySites(message = 'Izpolni projekt spodaj in klikni “Začni izdelavo”. Ko je objava končana, se tukaj takoj pojavi javna povezava.') {
    mySitesBody.className = 'my-sites-empty';
    mySitesBody.innerHTML = `<strong>Še nimaš objavljene strani.</strong>${escapeHtml(message)}`;
  }

  function renderPublishedSite(project) {
    if (!project?.repo_name) return renderEmptySites();
    const url = finalSiteUrl(project.repo_name);
    mySitesBody.className = '';
    mySitesBody.innerHTML = `
      <div class="published-site">
        <div><strong>${escapeHtml(project.name || project.repo_name)}</strong><small>${escapeHtml(url)}</small></div>
        <div class="site-actions">
          <a class="button small" href="${url}" target="_blank" rel="noopener">Odpri stran ↗</a>
          <button class="button secondary small" id="editPublishedSite" type="button">Uredi</button>
          <a class="button secondary small" href="https://github.com/${GITHUB_OWNER}/${encodeURIComponent(project.repo_name)}" target="_blank" rel="noopener">GitHub ↗</a>
        </div>
      </div>`;
    document.getElementById('editPublishedSite')?.addEventListener('click', () => {
      const revision = document.getElementById('revisionCard');
      if (revision) {
        revision.classList.add('visible');
        revision.scrollIntoView({behavior:'smooth', block:'center'});
        setTimeout(() => document.getElementById('revisionInstruction')?.focus(), 350);
      }
    });
  }

  async function refreshMySites() {
    if (!token) {
      mySitesBody.className = 'my-sites-empty';
      mySitesBody.innerHTML = '<strong>Prijavi se za dostop do svojih strani.</strong>Po prijavi bo tukaj vedno prikazana zadnja objavljena stran.';
      return;
    }
    try {
      const projects = await request('/projects');
      const published = projects.find(p => p.repo_name);
      if (published) renderPublishedSite(published);
      else if (projects.length) renderEmptySites(`Zadnji projekt ima stanje “${projects[0].status || 'v pripravi'}”, vendar še nima javne objave.`);
      else renderEmptySites();
    } catch (e) {
      mySitesBody.className = 'my-sites-empty';
      mySitesBody.innerHTML = `<strong>Strani trenutno ni mogoče preveriti.</strong>${escapeHtml(e.message)}`;
    }
  }

  document.querySelectorAll('.pkg').forEach(btn => btn.addEventListener('click', () => {
    const name = btn.dataset.package;
    const limit = packageLimits[name];
    const note = document.getElementById('pageLimit');
    if (note) note.textContent = `✓ Izbran paket ${name} — največ ${limit} strani.`;
  }));

  const host = actions.closest('.side-card') || actions.closest('.process-card') || actions.parentElement;
  const card = document.createElement('div');
  card.id = 'revisionCard';
  card.className = 'revision-card';
  card.innerHTML = `
    <h4>Spremeni objavljeno stran</h4>
    <p>Opiši spremembo z navadnim stavkom. Sistem ohrani obstoječo stran, spremeni potrebne datoteke, preveri rezultat in ponovno objavi isto povezavo.</p>
    <textarea id="revisionInstruction" maxlength="3000" placeholder="npr. Hero naj bo bolj premium in temnejši. CTA naj bo bolj izrazit. Na strani Kontakt dodaj kratek FAQ."></textarea>
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

  function liveUrl() { return currentRepo ? finalSiteUrl(currentRepo) : ''; }
  function refreshPreview() {
    const url = liveUrl();
    if (!url) return;
    liveLink.href = url;
    liveFrame.src = `${url}?pv=${Date.now()}`;
    liveMini.classList.add('visible');
  }
  async function loadHistory() {
    if (!activeProjectId || !token) return;
    try {
      const items = await request(`/projects/${activeProjectId}/revisions`);
      historyEl.innerHTML = items.slice(0, 4).map(item => `<div class="revision-item"><strong>${escapeHtml(item.status)}</strong><span>${escapeHtml(item.instruction)}</span></div>`).join('');
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
    if (!activeProjectId) { status('Najprej dokončaj osnovno spletno stran.'); return; }
    if (text.length < 3) { status('Opiši spremembo, ki jo želiš na objavljeni strani.'); instruction.focus(); return; }
    apply.disabled = true;
    apply.textContent = 'Izvajam ...';
    try {
      await request(`/projects/${activeProjectId}/revise`, {method:'POST', body:JSON.stringify({instruction:text})});
      status(`SPREMEMBA SPREJETA\nProjekt: ${activeProjectId}\n\nObstoječa stran se ureja, nato sledi ponovni pregled in objava.`);
      updatePipeline('revising');
      instruction.value = '';
      await loadHistory();
      watch(activeProjectId);
      for (let i = 0; i < 180; i++) {
        await sleep(4000);
        const project = await request(`/projects/${activeProjectId}`);
        if (['ready','needs_review','failed'].includes(project.status)) {
          apply.disabled = false;
          apply.textContent = 'Izvedi spremembo →';
          if (project.repo_name) { currentRepo = project.repo_name; setResultLinks(project.repo_name); }
          await loadHistory();
          await refreshMySites();
          if (project.status !== 'failed') setTimeout(refreshPreview, 3500);
          return;
        }
      }
      apply.disabled = false;
      apply.textContent = 'Izvedi spremembo →';
    } catch (e) {
      apply.disabled = false;
      apply.textContent = 'Izvedi spremembo →';
      status(`SPREMEMBA NI USPELA\n${e.message}`);
    }
  });

  document.getElementById('logout')?.addEventListener('click', () => setTimeout(refreshMySites, 0));
  document.getElementById('login')?.addEventListener('click', () => setTimeout(refreshMySites, 900));
  document.getElementById('register')?.addEventListener('click', () => setTimeout(refreshMySites, 900));
  refreshMySites();
})();