(() => {
  const qs = new URLSearchParams(location.search);
  const $ = id => document.getElementById(id);
  let token = localStorage.getItem('pv_token') || '';
  let API = (qs.get('api') || localStorage.getItem('pv_api_url') || '').trim().replace(/\/$/, '');
  if (qs.get('api')) localStorage.setItem('pv_api_url', API);

  const esc = value => String(value ?? '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const money = (amount,currency) => {
    if (typeof amount !== 'number' || !currency) return '—';
    try { return new Intl.NumberFormat('sl-SI',{style:'currency',currency:String(currency).toUpperCase()}).format(amount/100); }
    catch { return `${(amount/100).toFixed(2)} ${String(currency).toUpperCase()}`; }
  };
  const apiLink = path => {
    const url = new URL(path, location.href);
    if (API) url.searchParams.set('api', API);
    return url.href;
  };
  $('landingLink').href = apiLink('./');
  $('builderLink').href = apiLink('builder.html');

  function state(text, good=false) {
    $('state').textContent = text;
    $('state').style.color = good ? '#d9ff65' : '#a7bbb3';
  }

  async function request(path, options={}) {
    if (!API) throw new Error('API povezava ni nastavljena. Zaženi lokalni servis prek start-stable-local.ps1.');
    const headers = {...(options.headers || {})};
    if (!(options.body instanceof FormData)) headers['Content-Type'] = headers['Content-Type'] || 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    let res;
    try { res = await fetch(`${API}${path}`, {...options, headers}); }
    catch { throw new Error('API trenutno ni dosegljiv.'); }
    const text = await res.text();
    let data; try { data = JSON.parse(text); } catch { data = {detail:text}; }
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
    return data;
  }

  async function authenticate(kind) {
    const email = $('email').value.trim();
    const password = $('password').value;
    if (!email || password.length < 8) { state('Vpiši veljaven e-mail in geslo z najmanj 8 znaki.'); return; }
    try {
      const data = await request(`/auth/${kind}`, {method:'POST', body:JSON.stringify({email,password})});
      token = data.token;
      localStorage.setItem('pv_token', token);
      state('Prijavna seja je aktivna.', true);
      syncAccount();
      await loadProjects();
    } catch (err) { state(err.message); }
  }

  function syncAccount() {
    $('loginBox').classList.toggle('hidden', !!token);
    $('logoutBox').classList.toggle('hidden', !token);
    $('accountText').textContent = token ? 'Prijavljen račun lahko upravlja svoje projekte.' : 'Prijavi se z istim računom kot v builderju.';
    if (!token) state('Nisi prijavljen.');
  }

  const statusLabel = status => ({
    queued:'V čakalni vrsti', awaiting_payment:'Čaka plačilo', payment_pending:'Plačilo v teku', designing:'Struktura', building:'Izdelava', auditing:'QA', visual_qa:'Visual QA', fixing:'Popravki', publishing:'Objava', revising:'Revizija', ready:'Pripravljeno', needs_review:'Potreben pregled', failed:'Napaka'
  })[status] || status;
  const badgeClass = status => status === 'ready' ? 'good' : status === 'failed' ? 'bad' : ['needs_review','awaiting_payment','payment_pending'].includes(status) ? 'warn' : '';

  function projectCard(p) {
    const payment = p.payment;
    const paymentText = payment?.status === 'paid' ? `Plačano ${money(payment.amount_total,payment.currency)}` : payment ? 'Plačilo v teku' : 'Brez plačila';
    const qa = p.visual_qa;
    const qaText = qa?.available ? `${qa.score ?? '—'}/100` : 'Ni izveden';
    const live = p.public_live && p.public_url;
    const domain = p.domain?.domain || '';
    const workspace = apiLink(`builder.html?project=${encodeURIComponent(p.id)}`);
    return `<article class="project" data-project="${esc(p.id)}">
      <div class="project-main">
        <div><h3>${esc(p.name)}</h3><div class="project-meta">${esc(p.organization || '')} · ${esc(p.package)} · <span class="datum">${new Date(p.updated_at).toLocaleString('sl-SI')}</span></div></div>
        <div class="metric"><span>Status</span><strong><i class="badge ${badgeClass(p.status)}">${esc(statusLabel(p.status))}</i></strong></div>
        <div class="metric"><span>Plačilo</span><strong>${esc(paymentText)}</strong></div>
        <div class="metric"><span>Visual QA</span><strong>${esc(qaText)}</strong></div>
        <div class="project-actions">
          ${live ? `<a class="button" href="${esc(p.public_url)}" target="_blank" rel="noopener">Odpri stran ↗</a>` : ''}
          <a class="button light" href="${esc(workspace)}">Workspace</a>
          <button class="button light" type="button" data-details="${esc(p.id)}">Podrobnosti</button>
        </div>
      </div>
      <div class="details" id="details-${esc(p.id)}">
        <section class="panel"><h4>Vizualna kakovost</h4><div class="qa-score"><b>${esc(qa?.score ?? '—')}</b><p>${qa?.available ? `${esc(qa.pages_checked || 0)} strani · ${esc(qa.render_count || 0)} renderjev · desktop + tablet + mobile${p.severe_issue_count ? ` · ${esc(p.severe_issue_count)} pomembnih težav` : ' · brez pomembnih težav'}` : 'Visual QA se izvede med naslednjo izdelavo z nameščenim Chromiumom.'}</p></div></section>
        <section class="panel"><h4>Domena</h4><div class="domain-row"><input value="${esc(domain)}" data-domain-input="${esc(p.id)}" placeholder="www.mojprojekt.si"><button class="button" type="button" data-domain-save="${esc(p.id)}">Shrani</button></div><div class="project-meta">${domain ? `Shranjena domena: ${esc(domain)} · status ${esc(p.domain.status)}` : 'Domena še ni nastavljena. DNS povezava se preveri posebej.'}</div></section>
        <section class="panel"><h4>Spremeni objavljeno stran</h4><div class="revision-row"><textarea data-revision-input="${esc(p.id)}" placeholder="Npr. Zamenjaj hero naslov in naredi galerijo bolj editorial."></textarea><button class="button" type="button" data-revise="${esc(p.id)}">Izvedi</button></div><div class="revisions" id="revisions-${esc(p.id)}"><div class="revision"><span>${esc(p.revision_count)} dosedanjih revizij</span></div></div></section>
        <section class="panel"><h4>Predaja in koda</h4><div class="project-actions" style="justify-content:flex-start"><button class="button" type="button" data-source="${esc(p.id)}">Prenesi source ZIP</button>${p.repo_name ? `<a class="button light" href="https://github.com/DDAY2301/${esc(p.repo_name)}" target="_blank" rel="noopener">GitHub ↗</a>` : ''}${p.public_url ? `<a class="button light" href="${esc(p.public_url)}" target="_blank" rel="noopener">Live URL ↗</a>` : ''}</div><div class="project-meta">Repo: ${esc(p.repo_name || 'še ni ustvarjen')}</div></section>
      </div>
    </article>`;
  }

  async function loadProjects() {
    if (!token) { $('projects').innerHTML = '<div class="empty">Prijavi se za prikaz projektov.</div>'; return; }
    try {
      state('Nalagam projekte …');
      const projects = await request('/dashboard/projects');
      $('sumProjects').textContent = projects.length;
      $('sumLive').textContent = projects.filter(x => x.public_live).length;
      const scores = projects.map(x => x.visual_qa?.score).filter(x => typeof x === 'number');
      $('sumQa').textContent = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : '—';
      $('sumRevisions').textContent = projects.reduce((n,x)=>n+(x.revision_count||0),0);
      $('projects').innerHTML = projects.length ? projects.map(projectCard).join('') : `<div class="empty">Še nimaš projektov. <a href="${esc(apiLink('./#paketi'))}">Začni prvo stran →</a></div>`;
      bindProjectActions();
      state('Dashboard je posodobljen.', true);
    } catch (err) { state(err.message); $('projects').innerHTML = `<div class="empty">${esc(err.message)}</div>`; }
  }

  async function loadRevisions(projectId) {
    const host = $(`revisions-${projectId}`); if (!host) return;
    host.innerHTML = '<div class="revision"><span>Nalagam …</span></div>';
    try {
      const rows = await request(`/projects/${projectId}/revisions`);
      host.innerHTML = rows.length ? rows.map(r => `<div class="revision"><strong>${esc(r.status)}</strong><span>${esc(r.instruction)} · ${new Date(r.created_at).toLocaleString('sl-SI')}</span></div>`).join('') : '<div class="revision"><span>Ni še revizij.</span></div>';
    } catch (err) { host.innerHTML = `<div class="revision"><span>${esc(err.message)}</span></div>`; }
  }

  async function saveDomain(projectId) {
    const input = document.querySelector(`[data-domain-input="${CSS.escape(projectId)}"]`);
    try {
      const data = await request(`/projects/${projectId}/domain`, {method:'PUT', body:JSON.stringify({domain:input?.value || ''})});
      state(data.domain ? `Domena ${data.domain} je shranjena.` : 'Domena je odstranjena.', true);
      await loadProjects();
    } catch (err) { state(err.message); }
  }

  async function revise(projectId) {
    const input = document.querySelector(`[data-revision-input="${CSS.escape(projectId)}"]`);
    const instruction = input?.value.trim();
    if (!instruction) { state('Najprej napiši spremembo.'); return; }
    try {
      const row = await request(`/projects/${projectId}/revise`, {method:'POST', body:JSON.stringify({instruction})});
      if (input) input.value = '';
      state(`Revizija ${row.id} je v čakalni vrsti.`, true);
      await loadRevisions(projectId);
      setTimeout(loadProjects, 2500);
    } catch (err) { state(err.message); }
  }

  async function downloadSource(projectId) {
    try {
      state('Pripravljam source ZIP …');
      const res = await fetch(`${API}/projects/${projectId}/source.zip`, {headers:{Authorization:`Bearer ${token}`}});
      if (!res.ok) { let msg=`HTTP ${res.status}`; try { msg=(await res.json()).detail || msg; } catch {} throw new Error(msg); }
      const blob = await res.blob();
      const cd = res.headers.get('content-disposition') || '';
      const match = cd.match(/filename="([^"]+)"/i);
      const name = match?.[1] || 'website-source.zip';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href=url; a.download=name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      state('Source ZIP je pripravljen.', true);
    } catch (err) { state(err.message); }
  }

  function bindProjectActions() {
    document.querySelectorAll('[data-details]').forEach(btn => btn.addEventListener('click', () => {
      const id=btn.dataset.details, el=$(`details-${id}`); el?.classList.toggle('open'); if (el?.classList.contains('open')) loadRevisions(id);
    }));
    document.querySelectorAll('[data-domain-save]').forEach(btn => btn.addEventListener('click',()=>saveDomain(btn.dataset.domainSave)));
    document.querySelectorAll('[data-revise]').forEach(btn => btn.addEventListener('click',()=>revise(btn.dataset.revise)));
    document.querySelectorAll('[data-source]').forEach(btn => btn.addEventListener('click',()=>downloadSource(btn.dataset.source)));
  }

  $('login').addEventListener('click',()=>authenticate('login'));
  $('register').addEventListener('click',()=>authenticate('register'));
  $('logout').addEventListener('click',()=>{ token=''; localStorage.removeItem('pv_token'); syncAccount(); loadProjects(); });
  $('refresh').addEventListener('click',loadProjects);
  syncAccount();
  if (token) { state('Prijavna seja je aktivna.', true); loadProjects(); }
})();