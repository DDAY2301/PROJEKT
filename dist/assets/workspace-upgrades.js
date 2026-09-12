(() => {
  const DRAFT_KEY = 'pv_draft_v1';
  const allowedImageTypes = new Set(['image/jpeg','image/png','image/webp']);
  const maxImageBytes = 8 * 1024 * 1024;
  const maxImages = 12;

  const readDraft = () => {
    try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') || {}; }
    catch { return {}; }
  };
  const writeDraft = patch => {
    const next = {...readDraft(), ...patch, updated_at:new Date().toISOString()};
    localStorage.setItem(DRAFT_KEY, JSON.stringify(next));
    return next;
  };
  const esc = value => String(value || '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const slugify = value => String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'') || 'page';

  /* ------------------------------------------------------------------
     1. Carry the landing-page package + brief into the builder.
     ------------------------------------------------------------------ */
  function restoreLandingDraft() {
    const draft = readDraft();
    const requested = new URLSearchParams(location.search).get('paket');
    const pkg = packageLimits?.[requested] ? requested : (packageLimits?.[draft.package] ? draft.package : null);
    if (pkg) selectPackage(pkg);

    const mapping = {
      name:'name',
      organization:'organization',
      audience:'audience',
      programme:'programme',
      goal:'goal'
    };
    Object.entries(mapping).forEach(([draftKey, elementId]) => {
      const el = document.getElementById(elementId);
      if (el && !el.value.trim() && draft[draftKey]) el.value = draft[draftKey];
      el?.addEventListener('input', () => writeDraft({[draftKey]:el.value}));
    });
    document.querySelectorAll('.pkg').forEach(btn => btn.addEventListener('click', () => writeDraft({package:btn.dataset.package})));
    syncPreview();
  }

  /* ------------------------------------------------------------------
     2. Upgrade the basic file input into a proper drag/drop media studio.
     Images can target the whole homepage or an exact page + role.
     ------------------------------------------------------------------ */
  function configuredPages() {
    const raw = document.getElementById('pages')?.value || '';
    const rows = raw.split('\n').map(x => x.trim()).filter(Boolean);
    return rows.map((line, index) => {
      const title = (line.split('|')[0] || `Page ${index + 1}`).trim();
      return {title, slug:index === 0 ? 'index' : slugify(title)};
    });
  }

  function placementOptions(selected) {
    const base = [
      ['auto','Samodejno — agent določi'],
      ['hero','Domov — hero'],
      ['content','Domov — vsebina'],
      ['gallery','Domov — galerija'],
    ];
    const pageOptions = [];
    configuredPages().forEach(page => {
      if (page.slug === 'index') return;
      pageOptions.push([`page:${page.slug}:hero`,`${page.title} — hero`]);
      pageOptions.push([`page:${page.slug}:content`,`${page.title} — vsebina`]);
      pageOptions.push([`page:${page.slug}:gallery`,`${page.title} — galerija`]);
    });
    return [...base, ...pageOptions].map(([value,label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
  }

  function validateIncomingFiles(files) {
    const accepted = [];
    for (const file of files) {
      if (!allowedImageTypes.has(file.type)) {
        status(`SLIKA NI SPREJETA\n${file.name}: uporabi JPG, PNG ali WebP.`);
        continue;
      }
      if (file.size > maxImageBytes) {
        status(`SLIKA JE PREVELIKA\n${file.name}: največ 8 MB na sliko.`);
        continue;
      }
      accepted.push(file);
    }
    return accepted;
  }

  function imageItem(file, index) {
    return {
      file,
      placement:index === 0 && selectedImages.length === 0 ? 'hero' : 'auto',
      alt:file.name.replace(/\.[^.]+$/,'').replace(/[-_]+/g,' ').trim(),
      previewUrl:URL.createObjectURL(file),
    };
  }

  function enhanceMediaUi() {
    const input = document.getElementById('projectImages');
    if (!input || document.getElementById('mediaDropzone')) return;

    const style = document.createElement('style');
    style.textContent = `
      .media-studio{margin-top:.85rem}.media-drop{display:grid;place-items:center;min-height:9rem;padding:1.1rem;border:1.5px dashed #9eb6ac;border-radius:1rem;background:linear-gradient(135deg,#f7fbf8,#eef5f1);text-align:center;cursor:pointer;transition:.2s}.media-drop:hover,.media-drop.dragging{border-color:var(--good);background:#e8f4ee;box-shadow:0 0 0 4px rgba(27,118,95,.06)}.media-drop strong{display:block;font-size:.88rem}.media-drop span{display:block;margin-top:.2rem;color:var(--muted);font-size:.7rem}.media-drop b{display:grid;place-items:center;width:2.3rem;height:2.3rem;margin-bottom:.55rem;border-radius:.7rem;background:var(--ink);color:var(--lime);font-size:1.1rem}
      .media-queue{display:grid;gap:.55rem;margin-top:.7rem}.media-row{display:grid;grid-template-columns:5.2rem minmax(0,1fr) minmax(11rem,.55fr) 2.2rem;gap:.6rem;align-items:center;padding:.55rem;border:1px solid var(--line);border-radius:.8rem;background:#fff}.media-thumb{width:5.2rem;height:4.2rem;border-radius:.6rem;object-fit:cover;background:#edf2ef}.media-copy strong{display:block;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.media-copy input,.media-row select{width:100%;margin-top:.28rem;border:1px solid #b9c8c1;border-radius:.55rem;padding:.48rem;background:#fff;font:inherit;font-size:.7rem}.media-remove{border:0;background:transparent;color:#6e7f79;font-size:1.25rem;cursor:pointer}.media-help{margin-top:.5rem;color:var(--muted);font-size:.67rem;line-height:1.45}
      @media(max-width:760px){.media-row{grid-template-columns:4.3rem 1fr 2rem}.media-thumb{width:4.3rem;height:4rem}.media-row select{grid-column:2/4}.media-remove{grid-column:3;grid-row:1}}
    `;
    document.head.appendChild(style);

    input.style.display = 'none';
    const parent = input.parentElement;
    parent.classList.add('media-studio');
    const drop = document.createElement('div');
    drop.id = 'mediaDropzone';
    drop.className = 'media-drop';
    drop.tabIndex = 0;
    drop.setAttribute('role','button');
    drop.setAttribute('aria-label','Dodaj fotografije ali slike projekta');
    drop.innerHTML = '<div><b>＋</b><strong>Spusti slike sem ali klikni za izbor</strong><span>Do 12 slik · JPG, PNG ali WebP · največ 8 MB na sliko</span></div>';
    input.before(drop);

    const help = document.createElement('div');
    help.className = 'media-help';
    help.textContent = 'Vsaki sliki lahko določiš natančno stran in vlogo: hero, vsebina ali galerija. Agent sliko vključi v objavljeno kodo in jo optimizira znotraj izbranega layouta.';
    const queue = document.getElementById('imageQueue');
    queue?.classList.add('media-queue');
    queue?.after(help);

    const addFiles = incoming => {
      const accepted = validateIncomingFiles(Array.from(incoming || []));
      const room = Math.max(0, maxImages - selectedImages.length);
      accepted.slice(0, room).forEach((file, i) => selectedImages.push(imageItem(file, i)));
      if (accepted.length > room) status(`OMEJITEV SLIK\nUporabiš lahko največ ${maxImages} slik na projekt.`);
      renderImageQueue();
    };

    drop.addEventListener('click', () => input.click());
    drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    ['dragenter','dragover'].forEach(name => drop.addEventListener(name, e => { e.preventDefault(); drop.classList.add('dragging'); }));
    ['dragleave','drop'].forEach(name => drop.addEventListener(name, e => { e.preventDefault(); drop.classList.remove('dragging'); }));
    drop.addEventListener('drop', e => addFiles(e.dataTransfer?.files));

    // Replace the original change handler semantics by normalising its result
    // after it runs. The original handler still supports ordinary file-picker use.
    input.addEventListener('change', () => {
      selectedImages.forEach((item, index) => {
        if (!item.previewUrl && item.file) item.previewUrl = URL.createObjectURL(item.file);
        if (item.placement === 'gallery' && index > 0) item.placement = 'auto';
      });
      renderImageQueue();
    });

    window.renderImageQueue = renderImageQueue = function upgradedRenderImageQueue() {
      const host = document.getElementById('imageQueue');
      if (!host) return;
      host.innerHTML = '';
      selectedImages.forEach((item, index) => {
        if (!item.previewUrl && item.file) item.previewUrl = URL.createObjectURL(item.file);
        const row = document.createElement('div');
        row.className = 'media-row';
        row.innerHTML = `
          <img class="media-thumb" src="${esc(item.previewUrl || '')}" alt="">
          <div class="media-copy"><strong>${esc(item.file?.name || 'Slika')}</strong><input data-alt="${index}" value="${esc(item.alt || '')}" aria-label="Opis slike" placeholder="Opis / alt text"></div>
          <select data-placement="${index}" aria-label="Mesto slike">${placementOptions(item.placement || 'auto')}</select>
          <button class="media-remove" type="button" data-remove="${index}" aria-label="Odstrani sliko">×</button>`;
        host.appendChild(row);
      });
      host.querySelectorAll('[data-alt]').forEach(el => el.addEventListener('input', e => { selectedImages[Number(e.target.dataset.alt)].alt = e.target.value; }));
      host.querySelectorAll('[data-placement]').forEach(el => el.addEventListener('change', e => { selectedImages[Number(e.target.dataset.placement)].placement = e.target.value; }));
      host.querySelectorAll('[data-remove]').forEach(el => el.addEventListener('click', e => {
        const index = Number(e.currentTarget.dataset.remove);
        const removed = selectedImages.splice(index,1)[0];
        if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
        renderImageQueue();
      }));
    };

    document.getElementById('pages')?.addEventListener('input', () => renderImageQueue());
    renderImageQueue();
  }

  /* ------------------------------------------------------------------
     3. Preview terminal: quick local edits before build; natural-language
     revision commands after a site has been published.
     ------------------------------------------------------------------ */
  function installPreviewTerminal() {
    const preview = document.querySelector('.preview');
    const top = preview?.querySelector('.preview-top');
    if (!preview || !top || document.getElementById('previewTerminal')) return;

    const style = document.createElement('style');
    style.textContent = `
      .preview-tools{display:flex;align-items:center;gap:.4rem}.terminal-toggle{border:1px solid var(--line);border-radius:.55rem;background:#fff;color:var(--ink);padding:.38rem .55rem;font-size:.64rem;font-weight:850;cursor:pointer}.preview-terminal{display:none;border-top:1px solid var(--line);background:#051611;color:#d8e8e2;padding:.7rem}.preview-terminal.open{display:block}.terminal-screen{min-height:8rem;max-height:15rem;overflow:auto;white-space:pre-wrap;font:500 .65rem/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-line{display:grid;grid-template-columns:auto 1fr;gap:.45rem;align-items:center;margin-top:.55rem;border-top:1px solid rgba(255,255,255,.08);padding-top:.55rem}.terminal-line span{color:var(--lime);font:700 .72rem ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-line input{min-width:0;border:0;outline:0;background:transparent;color:#fff;font:500 .72rem ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-hint{margin-top:.45rem;color:#78988e;font-size:.58rem}
    `;
    document.head.appendChild(style);

    const currentLabel = top.querySelector('span');
    const tools = document.createElement('div');
    tools.className = 'preview-tools';
    if (currentLabel) tools.appendChild(currentLabel);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'terminal-toggle';
    toggle.textContent = 'Terminal';
    tools.appendChild(toggle);
    top.appendChild(tools);

    const terminal = document.createElement('div');
    terminal.id = 'previewTerminal';
    terminal.className = 'preview-terminal';
    terminal.innerHTML = `
      <div class="terminal-screen" id="terminalScreen">PROJECT VISIBILITY TERMINAL\nType help for commands.\nDraft commands change the live preview; free text on a published project starts a checked revision.</div>
      <div class="terminal-line"><span>pv&gt;</span><input id="terminalInput" autocomplete="off" spellcheck="false" placeholder="npr. title Nova naslovna vrstica"></div>
      <div class="terminal-hint">Commands: help · title · subtitle · cta · primary · accent · background · text · status · open · clear · or a natural-language revision request</div>`;
    preview.appendChild(terminal);

    const screen = terminal.querySelector('#terminalScreen');
    const input = terminal.querySelector('#terminalInput');
    const log = line => { screen.textContent += `\n${line}`; screen.scrollTop = screen.scrollHeight; };
    const setField = (id, value) => {
      const el = document.getElementById(id);
      if (!el) return false;
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles:true}));
      syncPreview();
      return true;
    };
    const color = value => /^#[0-9a-f]{6}$/i.test(value);

    async function projectStatus() {
      if (!activeProjectId || !token) { log('No active authenticated project.'); return null; }
      const project = await request(`/projects/${activeProjectId}`);
      log(`status=${project.status} repo=${project.repo_name || '-'} fixes=${project.auto_fix_attempts || 0}`);
      return project;
    }

    async function revise(instruction) {
      if (!token) { log('Login required before a published-site revision.'); return; }
      if (!activeProjectId) { log('No active project. Build or open a published project first.'); return; }
      const project = await request(`/projects/${activeProjectId}`);
      if (!project.repo_name) { log('This project is not published yet. Use draft commands or finish the first build.'); return; }
      log(`revision> ${instruction}`);
      const created = await request(`/projects/${activeProjectId}/revise`, {method:'POST', body:JSON.stringify({instruction})});
      log(`revision ${created.id} queued`);
      for (let i = 0; i < 100; i++) {
        await sleep(2500);
        const state = await request(`/projects/${activeProjectId}`);
        if (i % 3 === 0) log(`... ${state.status}`);
        if (['ready','needs_review','failed'].includes(state.status)) {
          log(state.status === 'failed' ? 'Revision failed. See process log for details.' : 'Revision published and checked.');
          if (state.repo_name) {
            const frame = document.getElementById('liveMiniFrame');
            if (frame) frame.src = `${finalSiteUrl(state.repo_name)}?terminal=${Date.now()}`;
          }
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }
      }
      log('Revision is still running; it will continue in the background.');
    }

    async function run(raw) {
      const command = raw.trim();
      if (!command) return;
      log(`pv> ${command}`);
      const [head, ...rest] = command.split(/\s+/);
      const arg = rest.join(' ').trim();
      switch (head.toLowerCase()) {
        case 'help':
          log('title <text> | subtitle <text> | cta <text> | primary #RRGGBB | accent #RRGGBB | background #RRGGBB | text #RRGGBB | status | open | clear');
          log('Any other sentence becomes a natural-language revision when an active published project exists.');
          return;
        case 'title': if (arg && setField('heroTitle',arg)) log('Hero title updated.'); else log('Usage: title <text>'); return;
        case 'subtitle': if (arg && setField('heroSubtitle',arg)) log('Hero subtitle updated.'); else log('Usage: subtitle <text>'); return;
        case 'cta': if (arg && setField('cta',arg)) log('CTA updated.'); else log('Usage: cta <text>'); return;
        case 'primary': if (color(arg) && setField('primary',arg)) log('Primary color updated.'); else log('Use #RRGGBB.'); return;
        case 'accent': if (color(arg) && setField('secondary',arg)) log('Accent color updated.'); else log('Use #RRGGBB.'); return;
        case 'background': if (color(arg) && setField('background',arg)) log('Background updated.'); else log('Use #RRGGBB.'); return;
        case 'text': if (color(arg) && setField('textColor',arg)) log('Text color updated.'); else log('Use #RRGGBB.'); return;
        case 'status': await projectStatus(); return;
        case 'open': {
          const p = await projectStatus();
          if (p?.repo_name) window.open(finalSiteUrl(p.repo_name), '_blank', 'noopener');
          return;
        }
        case 'clear': screen.textContent = 'PROJECT VISIBILITY TERMINAL'; return;
        default: await revise(command);
      }
    }

    toggle.addEventListener('click', () => {
      terminal.classList.toggle('open');
      toggle.textContent = terminal.classList.contains('open') ? 'Zapri terminal' : 'Terminal';
      if (terminal.classList.contains('open')) setTimeout(() => input.focus(), 0);
    });
    input.addEventListener('keydown', async e => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const value = input.value;
      input.value = '';
      try { await run(value); } catch (err) { log(`ERROR: ${err.message}`); }
    });
  }

  restoreLandingDraft();
  enhanceMediaUi();
  installPreviewTerminal();
})();
