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
    ready_for_payment:'Stran je izdelana — pripravljena za plačilo',
    payment_pending:'Plačilo v teku',
    publishing:'Plačilo potrjeno — objavljam stran',
    ready:'Končano',
    needs_review:'Potreben pregled',
    failed:'Ustavljeno'
  };

  let checkoutStarted = false;

  // Replace the old "payment before build" note with the actual commercial flow.
  window.updateCheckoutHint = function updateCheckoutHintPostbuild() {
    const hint = document.getElementById('checkoutHint');
    const packageEl = document.getElementById('package');
    if (!hint || !packageEl) return;
    const name = packageEl.value;
    const pkg = billingConfig.packages?.[name] || {};
    if (pkg.configured && typeof pkg.unit_amount === 'number') {
      hint.innerHTML = `<strong>Najprej izdelamo stran.</strong> Po končanem buildu in Visual QA plačaš ${money(pkg.unit_amount, pkg.currency)}. Šele nato se stran javno objavi.`;
    } else if (billingConfig.enabled) {
      hint.innerHTML = `<strong>Paket ${name} še nima aktivnega plačila.</strong> Stran se lahko izdela, javna objava pa sledi po urejeni ceni.`;
    } else {
      hint.innerHTML = '<strong>Testni način:</strong> izdelava in objava lahko tečeta brez plačila.';
    }
  };
  setTimeout(() => window.updateCheckoutHint(), 0);

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
          if (state) state.textContent = 'plačilo';
        }
      });
    }
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

    const siteLink = document.getElementById('siteLink');
    if (siteLink) siteLink.remove();
  }

  function clearPayButton() {
    document.getElementById('payPublishButton')?.remove();
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
          `Koda: ${project.repo_name ? 'pripravljena' : 'v izdelavi'}`,
          `Visual QA: ${audit.visual_qa?.score ?? '—'}`,
          `Najdene težave: ${issues.length}`
        ];

        if (project.status === 'ready_for_payment') {
          lines.push('', 'Spletna stran je v celoti izdelana in je prestala zaključni pregled.', 'Še NI javno dostopna.', 'Klikni »Plačaj in objavi«; po potrditvi plačila bo ista izdelana stran šla live brez ponovne generacije.');
          status(lines.join('\n'));
          showPayButton(id);
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }

        if (project.status === 'payment_pending') {
          lines.push('', 'Stripe Checkout čaka na zaključek plačila.');
        }
        if (project.status === 'publishing') {
          clearPayButton();
          lines.push('', 'Plačilo je potrjeno. Objavljam že izdelano stran — brez ponovne generacije.');
        }
        if (project.status === 'ready' && project.repo_name) {
          clearPayButton();
          setResultLinks(project.repo_name);
          document.getElementById('resultActions')?.classList.add('visible');
          lines.push('', `Javna stran: ${finalSiteUrl(project.repo_name)}`);
          status(lines.join('\n'));
          if (typeof loadRecentProjects === 'function') loadRecentProjects();
          return;
        }
        if (project.status === 'needs_review' || project.status === 'failed') {
          clearPayButton();
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
      clearPayButton();
      resetPipeline();
      updatePipeline('queued');
      document.getElementById('resultActions')?.classList.remove('visible');
      status('ZAČENJAM IZDELAVO\nPlačilo bo zahtevano šele, ko bo stran izdelana in uspešno prestala Visual QA.');

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
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Najprej izdelava + QA. Plačilo sledi čisto na koncu pred objavo.`);
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

  const params = new URLSearchParams(location.search);
  if (params.get('payment') === 'success' && params.get('project_id')) {
    setTimeout(() => {
      status('PLAČILO POTRJENO\nSpletna stran je že izdelana. Zdaj jo objavljam v živo ...');
      watchPostbuild(params.get('project_id'));
    }, 1800);
  }
})();