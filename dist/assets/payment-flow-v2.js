(() => {
  const button = document.getElementById('generate');
  if (!button) return;

  const ACTIVE_KEY = 'pv_active_project_v2';
  const ACTIVE_STATUSES = new Set([
    'queued','designing','building','auditing','visual_qa','fixing',
    'repository_ready','ready_for_payment','payment_pending','publishing'
  ]);

  const localLabels = {
    queued:'V čakalni vrsti',
    designing:'Priprava strukture',
    building:'Izdelava strani',
    auditing:'Preverjanje kakovosti',
    visual_qa:'Visual QA — desktop, tablet in mobile',
    fixing:'Samodejni popravki',
    repository_ready:'Končna koda je pripravljena',
    ready_for_payment:'Stran je izdelana — pripravljena za plačilo',
    payment_pending:'Plačilo v teku',
    publishing:'Objavljam stran',
    ready:'Končano',
    needs_review:'Potreben pregled',
    failed:'Ustavljeno'
  };

  let checkoutStarted = false;
  let launchInProgress = false;
  let watcherVersion = 0;

  function rememberActive(id) {
    if (!id) return;
    activeProjectId = id;
    localStorage.setItem(ACTIVE_KEY, id);
  }

  function clearActive(id) {
    const saved = localStorage.getItem(ACTIVE_KEY);
    if (!id || saved === id) localStorage.removeItem(ACTIVE_KEY);
    if (!id || activeProjectId === id) activeProjectId = null;
  }

  function setBuildButtonBusy(busy) {
    launchInProgress = busy;
    button.disabled = busy;
    button.setAttribute('aria-busy', busy ? 'true' : 'false');
    button.style.opacity = busy ? '.62' : '';
    button.style.cursor = busy ? 'wait' : '';
    if (busy) {
      button.dataset.originalLabel = button.dataset.originalLabel || button.textContent;
      button.textContent = 'Izdelava se začenja …';
    } else {
      button.textContent = button.dataset.originalLabel || 'Začni izdelavo →';
    }
  }

  // Replace the old "payment before build" note with the real commercial flow.
  window.updateCheckoutHint = function updateCheckoutHintPostbuild() {
    const hint = document.getElementById('checkoutHint');
    const packageEl = document.getElementById('package');
    if (!hint || !packageEl) return;
    const name = packageEl.value;
    const pkg = billingConfig.packages?.[name] || {};
    if (pkg.configured && typeof pkg.unit_amount === 'number') {
      hint.innerHTML = `<strong>Najprej izdelamo in preverimo stran.</strong> Po končanem buildu in Visual QA plačaš ${money(pkg.unit_amount, pkg.currency)}. Šele nato se že izdelana stran javno objavi.`;
    } else if (billingConfig.enabled) {
      hint.innerHTML = `<strong>Paket ${name} še nima aktivnega plačila.</strong> Stran se lahko izdela, javna objava pa sledi po urejeni ceni.`;
    } else {
      hint.innerHTML = '<strong>Testni način:</strong> izdelava in objava lahko tečeta brez plačila.';
    }
  };
  setTimeout(() => window.updateCheckoutHint(), 0);

  function updatePostbuildPipeline(projectStatus) {
    const pipes = Array.from(document.querySelectorAll('.pipe'));
    if (!pipes.length) return;

    const normalStage = {
      queued:0,
      designing:1,
      building:2,
      auditing:3,
      visual_qa:3,
      fixing:4,
      repository_ready:5,
      publishing:5
    };

    pipes.forEach((el, i) => {
      el.classList.remove('running','done');
      const state = el.querySelector('em');
      if (state) state.textContent = 'čaka';
    });

    if (projectStatus === 'ready') {
      pipes.forEach(el => {
        el.classList.add('done');
        const state = el.querySelector('em');
        if (state) state.textContent = 'končano';
      });
      return;
    }

    if (projectStatus === 'ready_for_payment' || projectStatus === 'payment_pending') {
      pipes.forEach((el, i) => {
        const state = el.querySelector('em');
        if (i < 5) {
          el.classList.add('done');
          if (state) state.textContent = 'končano';
        } else {
          el.classList.add('running');
          if (state) state.textContent = projectStatus === 'payment_pending' ? 'plačilo' : 'čaka plačilo';
        }
      });
      return;
    }

    if (projectStatus === 'needs_review') {
      pipes.forEach((el, i) => {
        const state = el.querySelector('em');
        if (i < 5) {
          el.classList.add('done');
          if (state) state.textContent = 'končano';
        } else {
          el.classList.add('running');
          if (state) state.textContent = 'pregled';
        }
      });
      return;
    }

    if (projectStatus === 'failed') {
      const running = pipes.find(el => el.classList.contains('running')) || pipes[3];
      if (running) {
        running.classList.add('running');
        const state = running.querySelector('em');
        if (state) state.textContent = 'ustavljeno';
      }
      return;
    }

    const active = normalStage[projectStatus] ?? 0;
    pipes.forEach((el, i) => {
      const state = el.querySelector('em');
      if (i < active) {
        el.classList.add('done');
        if (state) state.textContent = 'končano';
      } else if (i === active) {
        el.classList.add('running');
        if (state) {
          if (projectStatus === 'visual_qa') state.textContent = 'render QA';
          else if (projectStatus === 'repository_ready') state.textContent = 'koda pripravljena';
          else if (projectStatus === 'publishing') state.textContent = 'objavlja';
          else state.textContent = 'teče';
        }
      }
    });
  }

  async function beginCheckout(projectId) {
    if (checkoutStarted) return;
    checkoutStarted = true;
    try {
      status('STRAN JE IZDELANA IN PREVERJENA\nOdpiram varno Stripe plačilo. Po uspešnem plačilu gre ista stran takoj v javno objavo ...');
      const checkout = await request('/billing/checkout', {
        method:'POST',
        body:JSON.stringify({project_id:projectId})
      });
      if (checkout.paid) {
        status('PLAČILO JE ŽE POTRJENO\nObjavljam že izdelano spletno stran ...');
        checkoutStarted = false;
        watchPostbuild(projectId);
        return;
      }
      if (!checkout.checkout_url) throw new Error('Stripe Checkout povezava ni bila ustvarjena.');
      window.location.assign(checkout.checkout_url);
    } catch (e) {
      checkoutStarted = false;
      status(`PLAČILA NI MOGOČE ODPRETI\n${e.message}\n\nStran je izdelana in ostaja shranjena. Poskusi ponovno.`);
    }
  }

  function showPayButton(projectId) {
    const actions = document.getElementById('resultActions');
    if (!actions) return;
    actions.classList.add('visible');
    let pay = document.getElementById('payPublishButton');
    if (!pay) {
      pay = document.createElement('button');
      pay.id = 'payPublishButton';
      pay.type = 'button';
      pay.className = 'button small';
      pay.textContent = 'Plačaj in objavi →';
      actions.insertBefore(pay, actions.firstChild);
    }
    pay.onclick = () => beginCheckout(projectId);
    document.getElementById('siteLink')?.remove();
  }

  function clearPayButton() {
    document.getElementById('payPublishButton')?.remove();
  }

  function projectStatusText(project, id) {
    const issues = project.last_audit?.issues || [];
    const audit = project.last_audit || {};
    const lines = [
      localLabels[project.status] || project.status,
      `Projekt: ${id}`,
      `Koda: ${project.repo_name ? 'pripravljena' : 'v izdelavi'}`,
      `Visual QA: ${audit.visual_qa?.score ?? '—'}`,
      `Renderji: ${audit.visual_qa?.render_count ?? '—'}`,
      `Najdene težave: ${issues.length}`
    ];
    return {lines, issues, audit};
  }

  async function watchPostbuild(id) {
    rememberActive(id);
    const myVersion = ++watcherVersion;
    setBuildButtonBusy(true);

    for (let i = 0; i < 600; i++) {
      if (myVersion !== watcherVersion) return;
      try {
        const project = await request(`/projects/${id}`);
        const {lines, issues} = projectStatusText(project, id);
        updatePostbuildPipeline(project.status);

        if (project.status === 'ready_for_payment') {
          lines.push('', 'Spletna stran je v celoti izdelana in je prestala zaključni pregled.', 'Še NI javno dostopna.', 'Klikni »Plačaj in objavi«; po potrditvi plačila bo ista izdelana stran šla live brez ponovne generacije.');
          status(lines.join('\n'));
          showPayButton(id);
          setBuildButtonBusy(true);
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }

        if (project.status === 'payment_pending') {
          lines.push('', 'Stripe Checkout čaka na zaključek plačila.');
        }
        if (project.status === 'repository_ready') {
          lines.push('', 'Končna koda je pripravljena. Zaključujem delivery korak.');
        }
        if (project.status === 'publishing') {
          clearPayButton();
          lines.push('', 'Objavljam že izdelano stran — brez ponovne generacije.');
        }
        if (project.status === 'ready' && project.repo_name) {
          clearPayButton();
          clearActive(id);
          setResultLinks(project.repo_name);
          document.getElementById('resultActions')?.classList.add('visible');
          lines.push('', `Javna stran: ${finalSiteUrl(project.repo_name)}`);
          status(lines.join('\n'));
          setBuildButtonBusy(false);
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }
        if (project.status === 'needs_review' || project.status === 'failed') {
          clearPayButton();
          clearActive(id);
          if (project.repo_name) document.getElementById('resultActions')?.classList.add('visible');
          if (issues.length) lines.push('', ...issues.slice(0,6).map(x => `• ${x.message}`));
          status(lines.join('\n'));
          setBuildButtonBusy(false);
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }

        status(lines.join('\n'));
      } catch (e) {
        status(`PREVERJANJE PROJEKTA NI USPELO\n${e.message}\n\nProjekt ostaja shranjen. Po ponovnem nalaganju se bo spremljanje nadaljevalo.`);
        setBuildButtonBusy(false);
        return;
      }
      await sleep(3000);
    }

    status('IZDELAVA ŠE TEČE\nProjekt je shranjen, vendar je spremljanje v brskalniku doseglo časovno omejitev. Osveži stran; spremljanje se bo samodejno nadaljevalo.');
    setBuildButtonBusy(false);
  }

  async function startProjectBuildFirst() {
    if (launchInProgress) return;
    if (!token) {
      status('IZDELAVA JE BLOKIRANA\nNajprej se registriraj ali prijavi.');
      return;
    }

    setBuildButtonBusy(true);
    try {
      validateProject();
      const healthy = await checkHealth(false);
      if (!healthy) throw new Error('Storitev trenutno ni dosegljiva.');

      checkoutStarted = false;
      clearPayButton();
      resetPipeline();
      updatePostbuildPipeline('queued');
      document.getElementById('resultActions')?.classList.remove('visible');
      status('ZAČENJAM IZDELAVO\nNajprej shranjujem brief in fotografije. Plačilo bo zahtevano šele po končanem Visual QA.');

      // Deferred creation is critical: the backend must not start generation
      // until every uploaded image, focal point and placement has been saved.
      const created = await request('/projects', {
        method:'POST',
        body:JSON.stringify({...payload(), defer_build:true})
      });
      rememberActive(created.id);

      await uploadSelectedImages(created.id);

      const build = await request(`/projects/${created.id}/build`, {method:'POST'});
      if (!build.started && !build.already_running && !build.already_finished) {
        throw new Error('Build ni bilo mogoče zagnati.');
      }

      if (created.payment_bypassed) {
        status(`TESTNI RAČUN — PAYMENT BYPASS\nProjekt: ${created.id}\nStran se bo izdelala, preverila in objavila brez plačila.`);
      } else if (created.payment_required) {
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Najprej izdelava + QA. Plačilo sledi čisto na koncu pred objavo.`);
      } else {
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Testni način brez plačila.`);
      }

      // Do not unlock the launch button while this project is active. This
      // prevents a second click from creating a duplicate project.
      watchPostbuild(created.id);
    } catch (e) {
      status(`IZDELAVA NI ZAGNANA\n${e.message}`);
      setBuildButtonBusy(false);
    }
  }

  async function resumeExistingProject() {
    if (!token) return;
    try {
      let id = localStorage.getItem(ACTIVE_KEY) || '';
      let project = null;

      if (id) {
        try {
          project = await request(`/projects/${id}`);
        } catch {
          localStorage.removeItem(ACTIVE_KEY);
          id = '';
        }
      }

      // Migration path from the older frontend: find the newest unfinished
      // project even if its id was never written to localStorage.
      if (!id) {
        const projects = await request('/projects');
        const candidate = Array.isArray(projects)
          ? projects.find(item => ACTIVE_STATUSES.has(item.status))
          : null;
        if (candidate) {
          id = candidate.id;
          project = candidate;
          rememberActive(id);
        }
      }

      if (!id || !project || !ACTIVE_STATUSES.has(project.status)) return;

      status(`OBNAVLJAM SPREMLJANJE\nProjekt: ${id}\nTrenutno stanje: ${localLabels[project.status] || project.status}`);
      updatePostbuildPipeline(project.status);
      watchPostbuild(id);
    } catch (e) {
      // Health/status UI remains usable even if recovery fails. The user can
      // still open the project from the dashboard.
      console.warn('Could not resume active project', e);
    }
  }

  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    startProjectBuildFirst();
  }, true);

  const params = new URLSearchParams(location.search);
  if (params.get('payment') === 'success' && params.get('project_id')) {
    rememberActive(params.get('project_id'));
    setTimeout(() => {
      status('PLAČILO POTRJENO\nSpletna stran je že izdelana. Zdaj jo objavljam v živo ...');
      watchPostbuild(params.get('project_id'));
    }, 1800);
  } else {
    // builder.js runs its health check during initial load. Resume just after
    // that so "SYSTEM ONLINE" can never permanently hide an active build.
    setTimeout(resumeExistingProject, 2200);
  }
})();