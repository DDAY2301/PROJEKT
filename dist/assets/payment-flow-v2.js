(() => {
  const button = document.getElementById('generate');
  if (!button) return;

  async function startProjectWithServerPaymentDecision() {
    if (!token) {
      status('IZDELAVA JE BLOKIRANA\nNajprej se registriraj ali prijavi.');
      return;
    }

    try {
      validateProject();
      const healthy = await checkHealth(false);
      if (!healthy) throw new Error('Storitev trenutno ni dosegljiva.');

      resetPipeline();
      updatePipeline('queued');
      document.getElementById('resultActions')?.classList.remove('visible');
      status('Projekt ustvarjam ...');

      const created = await request('/projects', {
        method: 'POST',
        body: JSON.stringify(payload())
      });
      activeProjectId = created.id;

      await uploadSelectedImages(created.id);

      // The backend is the source of truth for whether this specific account
      // and project must pay. This allows a tightly-scoped sandbox QA bypass
      // without weakening payment enforcement for normal or live accounts.
      if (created.payment_required === true) {
        status('SLIKE SO SHRANJENE\nPripravljam varno Stripe plačilo ...');
        const checkout = await request('/billing/checkout', {
          method: 'POST',
          body: JSON.stringify({project_id: created.id})
        });
        if (checkout.paid) {
          status('PLAČILO JE ŽE POTRJENO\nZačenjam izdelavo.');
          watch(created.id);
          return;
        }
        if (!checkout.checkout_url) throw new Error('Stripe Checkout povezava ni bila ustvarjena.');
        window.location.assign(checkout.checkout_url);
        return;
      }

      // If files were uploaded after the project row was created, trigger the
      // existing audit/regeneration path so the final build definitely sees
      // the latest media assets.
      if (selectedImages.length) {
        await request(`/projects/${created.id}/audit`, {method:'POST'});
      }

      if (created.payment_bypassed) {
        status(`TESTNI PAYMENT BYPASS AKTIVEN\nProjekt: ${created.id}\nRačun je dovoljen za sandbox QA brez plačila.\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Začenjam izdelavo in Visual QA.`);
      } else {
        status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n${selectedImages.length ? `Slike: ${selectedImages.length}\n` : ''}Pripravljam strukturo in vsebino.`);
      }
      watch(created.id);
    } catch (e) {
      status(`IZDELAVA NI ZAGNANA\n${e.message}`);
    }
  }

  // Capture-phase listener runs before the historical builder.js click
  // handler. We intentionally stop that older handler so only one project is
  // created per click.
  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    startProjectWithServerPaymentDecision();
  }, true);
})();
