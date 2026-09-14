(() => {
  function button(label, attr, id) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'button light';
    el.textContent = label;
    el.dataset[attr] = id;
    return el;
  }

  async function openPreview(projectId) {
    const popup = window.open('about:blank', '_blank');
    try {
      const session = await request(`/projects/${projectId}/preview-session`, {method:'POST'});
      if (!session.url) throw new Error('Preview URL ni bil ustvarjen.');
      if (popup) popup.location = session.url;
      else window.location.href = session.url;
      state('Zasebni predogled je pripravljen.', true);
    } catch (err) {
      if (popup) popup.close();
      state(err.message);
    }
  }

  async function sendHandoff(projectId) {
    try {
      state('Pošiljam deployment napotke …');
      const result = await request(`/projects/${projectId}/handoff-email`, {method:'POST'});
      state(`Napotki so poslani na ${result.recipient || 'e-pošto uporabnika'}.`, true);
    } catch (err) {
      state(err.message);
    }
  }

  function enhanceCard(card) {
    if (!card || card.dataset.pvUpgraded === '1') return;
    const projectId = card.dataset.project;
    if (!projectId) return;
    card.dataset.pvUpgraded = '1';

    const mainActions = card.querySelector('.project-main .project-actions');
    if (mainActions && !mainActions.querySelector('[data-private-preview]')) {
      const preview = button('Private preview ↗', 'privatePreview', projectId);
      mainActions.insertBefore(preview, mainActions.firstChild);
    }

    const handoffPanel = Array.from(card.querySelectorAll('.panel')).find(panel => /Predaja in koda/.test(panel.textContent || ''));
    const handoffActions = handoffPanel?.querySelector('.project-actions');
    if (handoffActions && !handoffActions.querySelector('[data-handoff-email]')) {
      const email = button('Pošlji napotke na e-mail', 'handoffEmail', projectId);
      handoffActions.appendChild(email);
    }
  }

  function enhanceAll() {
    document.querySelectorAll('.project[data-project]').forEach(enhanceCard);
  }

  document.addEventListener('click', event => {
    const preview = event.target.closest('[data-private-preview]');
    if (preview) {
      event.preventDefault();
      openPreview(preview.dataset.privatePreview);
      return;
    }
    const email = event.target.closest('[data-handoff-email]');
    if (email) {
      event.preventDefault();
      sendHandoff(email.dataset.handoffEmail);
    }
  });

  const projects = document.getElementById('projects');
  if (projects) new MutationObserver(enhanceAll).observe(projects, {childList:true, subtree:true});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enhanceAll);
  else enhanceAll();
})();
