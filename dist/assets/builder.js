const params = new URLSearchParams(window.location.search);
const $ = id => document.getElementById(id);
let token = localStorage.getItem('pv_token') || '';
let API = '';
let activeProjectId = null;
const GITHUB_OWNER = 'DDAY2301';

function cleanApi(value) {
  return (value || '').trim().replace(/\/$/, '');
}

function initialApi() {
  const fromUrl = cleanApi(params.get('api'));
  if (fromUrl) {
    localStorage.setItem('pv_api_url', fromUrl);
    return fromUrl;
  }
  const saved = cleanApi(localStorage.getItem('pv_api_url'));
  if (saved) return saved;
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') return location.origin;
  return '';
}

API = initialApi();

function status(msg) {
  const el = $('status');
  if (el) el.textContent = msg;
}

function setSignal(id, text, state = '') {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = `signal-state ${state}`.trim();
}

function errorMessage(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map(x => {
      const where = Array.isArray(x.loc) ? x.loc.filter(v => v !== 'body').join('.') : '';
      return `${where ? where + ': ' : ''}${x.msg || 'Neveljaven podatek'}`;
    }).join(' | ');
  }
  return fallback;
}

async function request(path, options = {}) {
  if (!API) throw new Error('Povezava storitve ni nastavljena.');
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(`${API}${path}`, {...options, headers});
  } catch {
    throw new Error('Povezava trenutno ni dosegljiva. Preveri, da lokalni servis deluje.');
  }
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = {detail: text}; }
  if (!response.ok) throw new Error(errorMessage(data, `HTTP ${response.status}`));
  return data;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function checkHealth(showStatus = true) {
  if ($('apiUrl')) $('apiUrl').value = API;
  if (!API) {
    setSignal('apiState', 'Ni povezano', 'bad');
    setSignal('modelState', '—');
    setSignal('githubState', '—');
    if (showStatus) status('Builder je pripravljen. V nastavitvah povezave vnesi naslov storitve.');
    return false;
  }

  setSignal('apiState', 'Preverjam');
  setSignal('modelState', 'Preverjam');
  let lastError = null;

  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      const health = await request('/health');
      setSignal('apiState', 'Online', 'ok');
      setSignal('modelState', 'Pripravljen', 'ok');
      setSignal('githubState', health.github_configured ? 'Povezan' : 'Ni povezano', health.github_configured ? 'ok' : 'warn');
      if ($('apiHint')) $('apiHint').textContent = API;
      if (showStatus) {
        status(health.github_configured
          ? 'SISTEM ONLINE\nPovezava je aktivna. Izdelava in GitHub objava sta pripravljeni.'
          : 'SISTEM ONLINE\nIzdelava je pripravljena, GitHub objava pa še ni povezana.');
      }
      return true;
    } catch (e) {
      lastError = e;
      if (attempt < 5) await sleep(1800);
    }
  }

  setSignal('apiState', 'Nedosegljivo', 'bad');
  setSignal('modelState', '—');
  setSignal('githubState', '—');
  if (showStatus) status(`POVEZAVA NI DOSEGLJIVA\n${lastError?.message || 'Poskusi znova čez nekaj sekund.'}`);
  return false;
}

$('connectApi')?.addEventListener('click', async () => {
  const next = cleanApi($('apiUrl').value);
  if (!next || !/^https?:\/\//i.test(next)) {
    status('Vnesi veljaven naslov povezave.');
    return;
  }
  if (API && API !== next) {
    token = '';
    localStorage.removeItem('pv_token');
    updateAuthUi();
  }
  API = next;
  localStorage.setItem('pv_api_url', API);
  await checkHealth(true);
});

function authBody() {
  return {email: $('email').value.trim(), password: $('password').value};
}

function validateAuth() {
  const email = $('email').value.trim();
  const password = $('password').value;
  if (!email) throw new Error('Vpiši e-poštni naslov.');
  if (!/^\S+@\S+\.\S+$/.test(email)) throw new Error('Vpiši veljaven e-poštni naslov.');
  if (password.length < 8) throw new Error('Geslo mora imeti najmanj 8 znakov.');
}

function updateAuthUi(message) {
  const logged = Boolean(token);
  $('logout').style.display = logged ? 'inline-flex' : 'none';
  $('register').style.display = logged ? 'none' : 'inline-flex';
  $('login').style.display = logged ? 'none' : 'inline-flex';
  $('authState').classList.toggle('ok', logged);
  $('authState').textContent = message || (logged ? 'Prijavna seja je aktivna.' : 'Nisi prijavljen.');
}

$('register')?.addEventListener('click', async () => {
  try {
    validateAuth();
    status('Ustvarjam račun ...');
    const data = await request('/auth/register', {method: 'POST', body: JSON.stringify(authBody())});
    token = data.token;
    localStorage.setItem('pv_token', token);
    updateAuthUi('Registriran in prijavljen.');
    status('Račun je pripravljen. Zdaj lahko začneš izdelavo projekta.');
    loadRecentProjects();
  } catch (e) {
    const hint = /already registered/i.test(e.message) ? '\nTa e-pošta že obstaja — uporabi Prijava.' : '';
    status(`REGISTRACIJA NI USPELA\n${e.message}${hint}`);
  }
});

$('login')?.addEventListener('click', async () => {
  try {
    validateAuth();
    status('Prijavljam ...');
    const data = await request('/auth/login', {method: 'POST', body: JSON.stringify(authBody())});
    token = data.token;
    localStorage.setItem('pv_token', token);
    updateAuthUi('Prijava uspešna.');
    status('Prijava je uspešna. Projektni workspace je pripravljen.');
    loadRecentProjects();
  } catch (e) {
    status(`PRIJAVA NI USPELA\n${e.message}`);
  }
});

$('logout')?.addEventListener('click', () => {
  token = '';
  localStorage.removeItem('pv_token');
  updateAuthUi('Odjavljen.');
  status('Prijavna seja je zaključena.');
});

const packageLimits = {Start: 3, Standard: 6, Premium: 12};

function selectPackage(name) {
  if (!packageLimits[name]) return;
  $('package').value = name;
  document.querySelectorAll('.pkg').forEach(el => el.classList.toggle('active', el.dataset.package === name));
  $('pageLimit').textContent = `Paket ${name} omogoča največ ${packageLimits[name]} strani.`;
}

document.querySelectorAll('.pkg').forEach(el => el.addEventListener('click', () => selectPackage(el.dataset.package)));

function parsePages() {
  const rows = $('pages').value.split('\n').map(x => x.trim()).filter(Boolean);
  const limit = packageLimits[$('package').value];
  if (rows.length > limit) throw new Error(`Paket ${$('package').value} omogoča največ ${limit} strani. Trenutno jih je ${rows.length}.`);
  return rows.map((line, i) => {
    const [title, purpose = ''] = line.split('|').map(x => x.trim());
    const slug = i === 0 ? 'index' : title.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return {slug, title, purpose};
  });
}

function validateProject() {
  if (!$('name').value.trim()) throw new Error('Vpiši ime projekta.');
  if (!$('organization').value.trim()) throw new Error('Vpiši organizacijo ali podjetje.');
  if (!$('goal').value.trim()) throw new Error('Opiši glavni cilj strani.');
  const contact = $('contact').value.trim();
  if (contact && !/^\S+@\S+\.\S+$/.test(contact)) throw new Error('Kontaktni e-mail ni veljaven.');
  parsePages();
}

function payload() {
  return {
    name: $('name').value.trim(),
    organization: $('organization').value.trim(),
    package: $('package').value,
    programme: $('programme').value.trim(),
    goal: $('goal').value.trim(),
    audience: $('audience').value.trim(),
    tone: $('tone').value.trim(),
    brand: {
      primary_color: $('primary').value,
      secondary_color: $('secondary').value,
      background_color: $('background').value,
      text_color: $('textColor').value,
      font_style: $('fontStyle').value,
      mood: $('mood').value.trim()
    },
    pages: parsePages(),
    hero_title: $('heroTitle').value.trim(),
    hero_subtitle: $('heroSubtitle').value.trim(),
    cta_text: $('cta').value.trim(),
    contact_email: $('contact').value.trim() || null,
    image_direction: $('imageDirection').value.trim(),
    custom_requirements: $('requirements').value.trim()
  };
}

function resetPipeline() {
  document.querySelectorAll('.pipe').forEach(el => {
    el.classList.remove('running', 'done');
    const state = el.querySelector('em');
    if (state) state.textContent = 'čaka';
  });
}

const stageIndex = {
  queued: 0,
  designing: 1,
  building: 2,
  auditing: 3,
  fixing: 4,
  publishing: 5,
  ready: 5,
  needs_review: 5,
  failed: -1
};

function updatePipeline(current) {
  const active = stageIndex[current] ?? 0;
  document.querySelectorAll('.pipe').forEach((el, i) => {
    el.classList.remove('running', 'done');
    const state = el.querySelector('em');
    if (!state) return;
    if (current === 'failed') {
      state.textContent = i === Math.max(active, 0) ? 'ustavljeno' : 'čaka';
      return;
    }
    if (i < active || (current === 'ready' && i <= active)) {
      el.classList.add('done');
      state.textContent = 'končano';
    } else if (i === active && !['ready', 'needs_review'].includes(current)) {
      el.classList.add('running');
      state.textContent = 'teče';
    } else if (current === 'needs_review' && i === active) {
      el.classList.add('running');
      state.textContent = 'pregled';
    } else {
      state.textContent = 'čaka';
    }
  });
}

const statusLabels = {
  queued: 'V čakalni vrsti',
  designing: 'Priprava strukture',
  building: 'Izdelava strani',
  auditing: 'Preverjanje kakovosti',
  fixing: 'Samodejni popravki',
  publishing: 'Objava kode in spletne strani',
  ready: 'Končano',
  needs_review: 'Potreben pregled',
  failed: 'Ustavljeno'
};

function finalSiteUrl(repoName) {
  return `https://${GITHUB_OWNER.toLowerCase()}.github.io/${repoName}/`;
}

function setResultLinks(repoName) {
  if (!repoName) return;
  const actions = $('resultActions');
  const repoLink = $('repoLink');
  repoLink.href = `https://github.com/${GITHUB_OWNER}/${repoName}`;

  let siteLink = $('siteLink');
  if (!siteLink) {
    siteLink = document.createElement('a');
    siteLink.id = 'siteLink';
    siteLink.className = 'button small';
    siteLink.target = '_blank';
    siteLink.rel = 'noopener';
    siteLink.textContent = 'Odpri spletno stran ↗';
    actions.insertBefore(siteLink, repoLink);
  }
  siteLink.href = finalSiteUrl(repoName);
}

$('generate')?.addEventListener('click', async () => {
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
    $('resultActions').classList.remove('visible');
    status('Projekt pošiljam v izdelavo ...');
    const created = await request('/projects', {method: 'POST', body: JSON.stringify(payload())});
    activeProjectId = created.id;
    status(`IZDELAVA ZAČETA\nProjekt: ${created.id}\n\nPripravljam strukturo in vsebino.`);
    watch(created.id);
  } catch (e) {
    status(`IZDELAVA NI ZAGNANA\n${e.message}`);
  }
});

async function watch(id) {
  for (let i = 0; i < 180; i++) {
    await sleep(4000);
    try {
      const project = await request(`/projects/${id}`);
      const issues = project.last_audit?.issues || [];
      updatePipeline(project.status);
      const severe = issues.filter(x => ['critical', 'high'].includes(x.severity)).length;
      const lines = [
        statusLabels[project.status] || project.status,
        `Projekt: ${id}`,
        `GitHub repo: ${project.repo_name || 'še ni ustvarjen'}`,
        `Samodejni popravki: ${project.auto_fix_attempts || 0}`,
        `Najdene težave: ${issues.length}${severe ? ` (${severe} pomembnih)` : ''}`
      ];
      if (project.repo_name) {
        setResultLinks(project.repo_name);
        lines.push(`Javna stran: ${finalSiteUrl(project.repo_name)}`);
      }
      if (issues.length) {
        lines.push('', ...issues.slice(0, 6).map(x => `• ${x.message}`));
      }
      status(lines.join('\n'));
      if (['ready', 'needs_review', 'failed'].includes(project.status)) {
        if (project.repo_name) $('resultActions').classList.add('visible');
        return;
      }
    } catch (e) {
      status(`STATUSA NI MOGOČE PREVERITI\n${e.message}`);
      return;
    }
  }
  status('Izdelava še vedno teče. Status lahko preveriš nekoliko pozneje.');
}

$('newBuild')?.addEventListener('click', () => {
  activeProjectId = null;
  resetPipeline();
  $('resultActions').classList.remove('visible');
  status('Pripravljen za nov projekt.');
  window.scrollTo({top: 0, behavior: 'smooth'});
});

async function loadRecentProjects() {
  if (!token) return;
  try {
    const projects = await request('/projects');
    if (!projects.length) return;
    const project = projects[0];
    activeProjectId = project.id;
    if (project.status) updatePipeline(project.status);
    if (project.repo_name) {
      setResultLinks(project.repo_name);
      $('resultActions').classList.add('visible');
    }
  } catch {}
}

function updatePreview() {
  const canvas = $('previewCanvas');
  if (!canvas) return;
  canvas.style.setProperty('--preview-bg', $('background').value);
  canvas.style.setProperty('--preview-text', $('textColor').value);
  canvas.style.setProperty('--preview-primary', $('primary').value);
  canvas.style.setProperty('--preview-secondary', $('secondary').value);
  $('previewLogo').textContent = ($('organization').value || $('name').value || 'YOUR PROJECT').toUpperCase().slice(0, 28);
  $('previewEyebrow').textContent = ($('programme').value || 'PROJECT / DIGITAL EXPERIENCE').toUpperCase().slice(0, 42);
  $('previewTitle').textContent = $('heroTitle').value || $('name').value || 'Spletna stran, ki ima jasen namen.';
  $('previewSubtitle').textContent = $('heroSubtitle').value || $('goal').value || 'Vpiši vsebino na levi in predogled se bo sproti prilagajal.';
  $('previewCta').textContent = $('cta').value || 'Kontaktirajte nas';
}

['name','organization','programme','goal','heroTitle','heroSubtitle','cta','primary','secondary','background','textColor'].forEach(id => {
  $(id)?.addEventListener('input', updatePreview);
});

const requestedPackage = params.get('paket');
if (packageLimits[requestedPackage]) selectPackage(requestedPackage); else selectPackage('Start');

try {
  const rawPrefill = localStorage.getItem('pv_prefill');
  if (rawPrefill) {
    const p = JSON.parse(rawPrefill);
    if (p.organization) $('organization').value = p.organization;
    if (p.programme) $('programme').value = p.programme;
    if (p.goal) $('goal').value = p.goal;
    if (p.contact_email) {
      $('contact').value = p.contact_email;
      if (!$('email').value) $('email').value = p.contact_email;
    }
    if (packageLimits[p.package]) selectPackage(p.package);
    const extras = [];
    if (p.contact_name) extras.push(`Kontaktna oseba: ${p.contact_name}`);
    if (p.deadline) extras.push(`Želeni rok: ${p.deadline}`);
    if (p.existing_url) extras.push(`Obstoječa povezava: ${p.existing_url}`);
    if (extras.length && !$('requirements').value) $('requirements').value = extras.join('; ');
    localStorage.removeItem('pv_prefill');
  }
} catch {}

if ($('apiUrl')) $('apiUrl').value = API;
updateAuthUi();
updatePreview();
resetPipeline();
checkHealth(true).then(ok => { if (ok && token) loadRecentProjects(); });