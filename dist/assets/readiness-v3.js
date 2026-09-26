(() => {
  const WORKSPACE_KEY = 'pv_workspace_draft_v2';
  const REQUIRED = [
    ['name', 'Ime projekta'],
    ['organization', 'Organizacija / podjetje'],
    ['goal', 'Glavni cilj'],
    ['pages', 'Strani in vsebina']
  ];
  const OPTIONAL = [
    ['audience', 'Ciljna publika'],
    ['heroTitle', 'Glavni naslov'],
    ['heroSubtitle', 'Podnaslov'],
    ['contact', 'Kontaktni e-mail']
  ];
  const SAVED_FIELDS = [
    'name','organization','programme','audience','goal','tone','pages','heroTitle',
    'heroSubtitle','cta','contact','requirements','primary','secondary','background',
    'textColor','fontStyle','mood','imageDirection','package'
  ];

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));

  function readSaved() {
    try { return JSON.parse(localStorage.getItem(WORKSPACE_KEY) || '{}') || {}; }
    catch { return {}; }
  }

  function currentValue(id) {
    const el = document.getElementById(id);
    return el ? String(el.value || '').trim() : '';
  }

  function persist() {
    const next = {updated_at:new Date().toISOString()};
    SAVED_FIELDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) next[id] = el.value;
    });
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify(next));
  }

  function restore() {
    const saved = readSaved();
    SAVED_FIELDS.forEach(id => {
      const el = document.getElementById(id);
      if (!el || saved[id] === undefined || saved[id] === null || saved[id] === '') return;
      const current = String(el.value || '').trim();
      const defaults = new Set([
        'professional and human',
        'clean, trustworthy, contemporary',
        'authentic, relevant, non-stock feeling',
        'Kontaktirajte nas'
      ]);
      if (!current || defaults.has(current)) el.value = saved[id];
    });

    if (saved.package && typeof selectPackage === 'function') selectPackage(saved.package);
    if (typeof syncPreview === 'function') syncPreview();
  }

  function serviceReady() {
    const el = document.getElementById('apiState');
    return Boolean(el?.classList.contains('ok'));
  }

  function authReady() {
    try { return Boolean(token); } catch { return Boolean(localStorage.getItem('pv_token')); }
  }

  function pagesValid() {
    try {
      if (typeof parsePages === 'function') return parsePages().length > 0;
    } catch {}
    return Boolean(currentValue('pages'));
  }

  function validateContact() {
    const value = currentValue('contact');
    return !value || /^\S+@\S+\.\S+$/.test(value);
  }

  function calculate() {
    const checks = [
      {key:'service', label:'Storitev je dosegljiva', ok:serviceReady(), critical:true},
      {key:'auth', label:'Uporabnik je prijavljen', ok:authReady(), critical:true},
      ...REQUIRED.map(([id,label]) => ({
        key:id,
        label,
        ok:id === 'pages' ? pagesValid() : Boolean(currentValue(id)),
        critical:true
      })),
      ...OPTIONAL.map(([id,label]) => ({
        key:id,
        label,
        ok:id === 'contact' ? validateContact() && Boolean(currentValue(id)) : Boolean(currentValue(id)),
        critical:false
      }))
    ];
    const completed = checks.filter(x => x.ok).length;
    const criticalMissing = checks.filter(x => x.critical && !x.ok);
    return {checks, completed, total:checks.length, criticalMissing};
  }

  function styles() {
    if (document.getElementById('pvReadinessStyles')) return;
    const style = document.createElement('style');
    style.id = 'pvReadinessStyles';
    style.textContent = `
      .readiness-card{padding:.95rem;border:1px solid var(--line);border-radius:1.2rem;background:var(--card);box-shadow:var(--shadow)}
      .readiness-head{display:flex;align-items:flex-start;justify-content:space-between;gap:.7rem}
      .readiness-head h3{margin:0;font-size:.88rem}.readiness-head p{margin:.2rem 0 0;color:var(--muted);font-size:.64rem;line-height:1.4}
      .readiness-score{display:grid;place-items:center;min-width:3.2rem;height:3.2rem;border-radius:50%;background:conic-gradient(var(--good) var(--score),#e5ece8 0);position:relative}
      .readiness-score::after{content:"";position:absolute;inset:.3rem;border-radius:50%;background:var(--card)}
      .readiness-score b{position:relative;z-index:1;font-size:.67rem}
      .readiness-list{display:grid;gap:.33rem;margin-top:.75rem}.readiness-item{display:flex;align-items:center;gap:.45rem;padding:.44rem .5rem;border-radius:.58rem;background:#f1f5f3;font-size:.63rem;font-weight:760}
      .readiness-item::before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:#b9c8c1;flex:0 0 auto}.readiness-item.ok::before{background:var(--good);box-shadow:0 0 0 3px rgba(29,123,98,.08)}
      .readiness-item.critical:not(.ok){background:#fff1f1;color:#8b3131}.readiness-item.critical:not(.ok)::before{background:#d85b5b}
      .readiness-actions{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.7rem}.readiness-actions button{border:1px solid var(--line);border-radius:.6rem;background:#fff;padding:.48rem .6rem;color:var(--ink);font-size:.61rem;font-weight:850;cursor:pointer}
      .readiness-actions button:hover{border-color:#9fb5ab}.build-blocked{opacity:.58!important;cursor:not-allowed!important;box-shadow:none!important;transform:none!important}
      .draft-status{margin-top:.55rem;color:var(--muted);font-size:.58rem;line-height:1.35}
      .field.field-error input,.field.field-error textarea,.field.field-error select{border-color:#d85b5b;box-shadow:0 0 0 3px rgba(216,91,91,.08)}
      @media(max-width:1220px){.readiness-card{grid-column:auto}}
    `;
    document.head.appendChild(style);
  }

  function installCard() {
    if (document.getElementById('projectReadiness')) return;
    const side = document.querySelector('.side');
    if (!side) return;
    const card = document.createElement('section');
    card.id = 'projectReadiness';
    card.className = 'readiness-card';
    card.setAttribute('aria-live','polite');
    card.innerHTML = `
      <div class="readiness-head">
        <div><h3>Pripravljenost projekta</h3><p>Pred izdelavo preverim povezavo, račun in ključne podatke briefa.</p></div>
        <div class="readiness-score" id="readinessScore" style="--score:0deg"><b id="readinessScoreText">0%</b></div>
      </div>
      <div class="readiness-list" id="readinessList"></div>
      <div class="readiness-actions">
        <button type="button" id="readinessCheckApi">Preveri povezavo</button>
        <button type="button" id="readinessFocusMissing">Pokaži manjkajoče</button>
        <button type="button" id="readinessClearDraft">Počisti osnutek</button>
      </div>
      <div class="draft-status" id="readinessDraftStatus">Osnutek se lokalno shranjuje samodejno.</div>
    `;
    const pipeline = side.querySelector('.side-card');
    side.insertBefore(card, pipeline || side.firstChild);

    document.getElementById('readinessCheckApi')?.addEventListener('click', async () => {
      const btn = document.getElementById('readinessCheckApi');
      btn.disabled = true;
      btn.textContent = 'Preverjam …';
      try {
        if (typeof checkHealth === 'function') await checkHealth(true);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Preveri povezavo';
        render();
      }
    });

    document.getElementById('readinessFocusMissing')?.addEventListener('click', () => {
      const {criticalMissing} = calculate();
      document.querySelectorAll('.field-error').forEach(el => el.classList.remove('field-error'));
      for (const item of criticalMissing) {
        const el = document.getElementById(item.key);
        el?.closest('.field')?.classList.add('field-error');
      }
      const first = criticalMissing.find(x => document.getElementById(x.key));
      document.getElementById(first?.key)?.scrollIntoView({behavior:'smooth',block:'center'});
      document.getElementById(first?.key)?.focus({preventScroll:true});
    });

    document.getElementById('readinessClearDraft')?.addEventListener('click', () => {
      localStorage.removeItem(WORKSPACE_KEY);
      const s = document.getElementById('readinessDraftStatus');
      if (s) s.textContent = 'Lokalni osnutek je počiščen. Trenutni vnos ostane na zaslonu.';
    });
  }

  function render() {
    const list = document.getElementById('readinessList');
    const score = document.getElementById('readinessScore');
    const scoreText = document.getElementById('readinessScoreText');
    if (!list || !score || !scoreText) return;

    const result = calculate();
    const pct = Math.round((result.completed / Math.max(1,result.total)) * 100);
    score.style.setProperty('--score', `${pct * 3.6}deg`);
    scoreText.textContent = `${pct}%`;
    list.innerHTML = result.checks.map(item =>
      `<div class="readiness-item ${item.ok ? 'ok' : ''} ${item.critical ? 'critical' : ''}">${esc(item.label)}</div>`
    ).join('');

    const build = document.getElementById('generate');
    const blocked = result.criticalMissing.length > 0;
    if (build && build.getAttribute('aria-busy') !== 'true') {
      build.disabled = blocked;
      build.classList.toggle('build-blocked', blocked);
      build.title = blocked ? 'Dopolni obvezne podatke, prijavo in povezavo storitve.' : '';
    }

  }

  function bindPersistence() {
    SAVED_FIELDS.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const event = el.matches('select,input[type="color"]') ? 'change' : 'input';
      el.addEventListener(event, () => {
        persist();
        render();
        const s = document.getElementById('readinessDraftStatus');
        if (s) s.textContent = 'Osnutek shranjen v tem brskalniku.';
      });
    });

    document.addEventListener('click', event => {
      if (event.target.closest('.pkg,[data-remove],[data-placement],#login,#register,#logout,#connectApi')) {
        setTimeout(() => { persist(); render(); }, 80);
      }
    });

    const apiState = document.getElementById('apiState');
    if (apiState) new MutationObserver(render).observe(apiState,{attributes:true,childList:true,subtree:true});
    const authState = document.getElementById('authState');
    if (authState) new MutationObserver(render).observe(authState,{attributes:true,childList:true,subtree:true});
  }

  function boot() {
    styles();
    restore();
    installCard();
    bindPersistence();
    render();
    setTimeout(render, 700);
    setTimeout(render, 2500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();