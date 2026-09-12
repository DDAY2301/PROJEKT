(() => {
  const button = document.getElementById('generate');
  if (!button) return;

  const localLabels = {
    queued:'V čakalni vrsti',
    designing:'Priprava strukture',
    building:'Izdelava strani',
    auditing:'Preverjanje kakovosti',
    visual_qa:'Visual QA',
    fixing:'Samodejni popravki',
    repository_ready:'Končna koda je pripravljena',
    ready_for_payment:'Stran je izdelana — čaka na plačilo',
    payment_pending:'Plačilo v teku',
    publishing:'Plačilo potrjeno — objavljam stran',
    ready:'Končano',
    needs_review:'Potreben pregled',
    failed:'Ustavljeno'
  };

  let checkoutStarted = false;

  function updatePostbuildPipeline(projectStatus) {
    if (typeof updatePipeline === 'function') updatePipeline(projectStatus);
    const pipes = document.querySelectorAll('.pipe');
    if (projectStatus === 'ready_for_payment' && pipes.length) {
      pipes.forEach((el, i) => {
        const state = el.querySelector('em');
        if (i < 5) {
          el.classList.add('done');
          el.classList.remove('running');
          if (state) state.textContent = 'končano';
        } else {
          el.classList.add('running');
          el.classList.remove('done');
          if (state) state.textContent = 'čaka plačilo';
        }
      });
    }
  }

  async function beginCheckout(projectId) {
    if (checkoutStarted) return;
    checkoutStarted = true;
    try {
      status('STRAN JE IZDELANA IN PREVERJENA\nPlačilo odklene javno objavo. Odpiram varno Stripe Checkout stran ...');
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
      status(`PLAČILA NI MOGOČE ODPRETI\n${e.message}\n\nStran je izdelana in ostaja shranjena. Poskusi ponovno iz projekta.`);
    }
  }

  async function watchPostbuild(id) {
    for (let i = 0; i < 300; i++) {
      await sleep(3000);
      try {
        const project = await request(`/projects/${id}`);
        const issues = project.last_audit?.issues || [];
        const audit = project.last_audit || {};
        updatePostbuildPipeline(project.status);

        const lines = [
          localLabels[project.status] || project.status,
          `Projekt: ${id}`,
          `GitHub repo: ${project.repo_name || 'še ni ustvarjen'}`,
          `Visual QA: ${audit.visual_qa?.score ?? '—'}`,
          `Najdene težave: ${issues.length}`
        ];

        if (project.status === 'ready_for_payment') {
          lines.push('', 'Spletna stran je v celoti izdelana in preverjena.', 'Še ni javno objavljena. Plačilo jo odklene za objavo.');
          status(lines.join('\n'));
          await sleep(700);
          await beginCheckout(id);
          return;
        }

        if (project.status === 'payment_pending') {
          lines.push('', 'Stripe Checkout čaka na zaključek plačila.');
        }
        if (project.status === 'publishing') {
          lines.push('', 'Plačilo je potrjeno. Objavljam že izdelano stran — brez ponovne generacije.');
        }
        if (project.status === 'ready' && project.repo_name) {
          setResultLinks(project.repo_name);
          document.getElementById('resultActions')?.classList.add('visible');
          lines.push('', `Javna stran: ${finalSiteUrl(project.repo_name)}`);
          status(lines.join('\n'));
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }
        if (project.status === 'needs_review' || project.status === 'failed') {
          if (project.repo_name) document.getElementById('resultActions')?.classList.add('visible');
          if (issues.length) lines.push('', ...issues.slice(0,6).map(x => `• ${x.message}`));
          status(lines.join('\n'));
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }

        status(lines.join('\n'));
      } catch (e) {
        status(`PREVERJANJE PROJEKTA NI USPELO\n${e.message}`);
        return;
      }
    }
  }

  async function startProjectBuildFirst() {
    if (!token) {
      status('IZDELAVA JE BLOKIRANA\nNajprej se registriraj ali prijavi.');
      return;
    }

    try {
      validateProject();
      const healthy = await checkHealth(false);
      if (!healthy) throw new Error('Storitev trenutno ni dosegljiva.');

      checkoutStarted = false;
      resetPipeline();
      updatePipeline('queued');
      document.getElementById('resultActions')?.classList.remove('visible');
      status('ZAČENJAM IZDELAVO\nPlačilo bo zahtevano šele, ko bo stran izdelana in uspešno prestala QA.');

      const created = await request('/projects', {
        method:'POST',
        body:JSON.stringify(payload())
      });
      activeProjectId = created.id;

      await uploadSelectedImages(created.id);

      if (selectedImages.length) {
        await request(`/projects/${created.id}/audit`, {method:'POST'});
      }

      if (created.payment_bypassed) {
        status(`TESTNI RAČUN — PAYMENT BYPASS\nProjekt: ${created.id}\nStran se bo izdelala, preverila in objavila brez plačila.`);
      } else if (created.payment_required) {
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Plačilo sledi šele po končanem buildu in Visual QA.`);
      } else {
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Testni način brez plačila.`);
      }

      watchPostbuild(created.id);
    } catch (e) {
      status(`IZDELAVA NI ZAGNANA\n${e.message}`);
    }
  }

  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    startProjectBuildFirst();
  }, true);

  // When Stripe returns after a successful end-of-build payment, the legacy
  // handler verifies the session. This observer updates the message to reflect
  // the new model: the site already exists; only publication remains.
  const params = new URLSearchParams(location.search);
  if (params.get('payment') === 'success' && params.get('project_id')) {
    setTimeout(() => {
      status('PLAČILO POTRJENO\nSpletna stran je že izdelana. Zdaj jo objavljam v živo ...');
      watchPostbuild(params.get('project_id'));
    }, 1800);
  }
})();
