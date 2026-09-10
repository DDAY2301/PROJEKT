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
    .intro{padding:0!important}
    .preview{padding:0!important}
    .revision-card{display:none;margin-top:.85rem;padding:.9rem;border:1px solid var(--line);border-radius:.9rem;background:#f7faf8}
    .revision-card.visible{display:block}.revision-card h4{margin:0;font-size:.9rem}.revision-card p{margin:.25rem 0 .7rem;color:var(--muted);font-size:.72rem;line-height:1.45}
    .revision-card textarea{width:100%;min-height:5.8rem;padding:.7rem .75rem;border:1px solid #b8c7c0;border-radius:.72rem;background:#fff;resize:vertical;font:inherit;font-size:.78rem}
    .revision-card textarea:focus{outline:0;border-color:var(--green);box-shadow:0 0 0 4px rgba(18,63,53,.08)}
    .revision-actions{display:flex;align-items:center;gap:.5rem;margin-top:.55rem;flex-wrap:wrap}.revision-actions button:disabled{opacity:.55;cursor:not-allowed}
    .revision-history{display:grid;gap:.35rem;margin-top:.7rem}.revision-item{padding:.55rem .62rem;border-radius:.6rem;background:#edf3f0;font-size:.68rem}.revision-item strong{display:block;color:var(--green);font-size:.62rem;text-transform:uppercase;letter-spacing:.06em}.revision-item span{display:block;margin-top:.12rem;color:#49605a}
    .live-mini{display:none;margin-top:.75rem;border:1px solid var(--line);border-radius:.75rem;overflow:hidden;background:#fff}.live-mini.visible{display:block}.live-mini-top{display:flex;align-items:center;justify-content:space-between;padding:.5rem .6rem;border-bottom:1px solid var(--line);font-size:.65rem;font-weight:800}.live-mini iframe{display:block;width:100%;height:240px;border:0;background:#fff}
  `;
  document.head.appendChild(style);

  const actions = document.getElementById('resultActions');
  if (!actions) return;
  const host = actions.closest('.side-card') || actions.closest('.process-card') || actions.parentElement;

  const card = document.createElement('div');
  card.id = 'revisionCard';
  card.className = 'revision-card';
  card.innerHTML = `
    <h4>Spremeni objavljeno stran</h4>
    <p>Opiši spremembo z navadnim stavkom. Sistem ohrani obstoječo stran, spremeni potrebne datoteke, preveri rezultat in ponovno objavi isto povezavo.</p>
    <textarea id="revisionInstruction" maxlength="3000" placeholder="npr. Hero naj bo bolj premium in temnejši. CTA naj bo bolj izrazit. Na strani Kontakt dodaj kratek FAQ."></textarea>
    <div class="revision-actions">
      <button class="button small" id="applyRevision" type="button">Izvedi spremembo →</button>
      <button class="button secondary small" id="refreshLivePreview" type="button">Osveži predogled</button>
    </div>
    <div class="revision-history" id="revisionHistory"></div>
    <div class="live-mini" id="liveMini"><div class="live-mini-top"><span>Objavljena stran</span><a id="liveMiniLink" target="_blank" rel="noopener">Odpri ↗</a></div><iframe id="liveMiniFrame" title="Predogled objavljene strani" loading="lazy"></iframe></div>
  `;
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
  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }
  async function loadHistory() {
    if (!activeProjectId || !token) return;
    try {
      const items = await request(`/projects/${activeProjectId}/revisions`);
      historyEl.innerHTML = items.slice(0, 4).map(item => `<div class="revision-item"><strong>${item.status}</strong><span>${escapeHtml(item.instruction)}</span></div>`).join('');
    } catch {}
  }
  function showForRepo(repoName) {
    if (!repoName) return;
    currentRepo = repoName;
    card.classList.add('visible');
    refreshPreview();
    loadHistory();
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
})();