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
  $('status').textContent = msg;
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
  if (!API) throw new Error('Agent API ni povezan. Vnesi HTTPS naslov v Agent connection.');
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${API}${path}`, {...options, headers});
  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = {detail: text}; }
  if (!r.ok) throw new Error(errorMessage(data, `HTTP ${r.status}`));
  return data;
}

async function checkHealth(showStatus = true) {
  if ($('apiUrl')) $('apiUrl').value = API;
  if (!API) {
    setSignal('apiState', 'Ni povezan', 'bad');
    setSignal('modelState', '—');
    setSignal('githubState', '—');
    if (showStatus) status('Javni builder je pripravljen. Vnesi HTTPS Cloudflare API naslov in klikni Poveži.');
    return false;
  }
  setSignal('apiState', 'Preverjam');
  try {
    const h = await request('/health');
    setSignal('apiState', 'Online', 'ok');
    setSignal('modelState', h.model || 'local model', 'ok');
    setSignal('githubState', h.github_configured ? 'Povezan' : 'Manjka token', h.github_configured ? 'ok' : 'warn');
    $('apiHint').textContent = API;
    if (showStatus) status(`AGENT ONLINE\nAPI: ${API}\nModel: ${h.model}\nGitHub publishing: ${h.github_configured ? 'ENABLED' : 'DISABLED'}${h.github_configured ? '' : '\nZa končni publish ponovno zaženi backend z GitHub tokenom.'}`);
    return true;
  } catch (e) {
    setSignal('apiState', 'Offline', 'bad');
    setSignal('modelState', '—');
    setSignal('githubState', '—');
    if (showStatus) status(`API NI DOSEGLJIV\n${API}\n\n${e.message}`);
    return false;
  }
}

$('connectApi').addEventListener('click', async () => {
  const next = cleanApi($('apiUrl').value);
  if (!next || !/^https?:\/\//i.test(next)) {
    status('Vnesi veljaven API URL, npr. https://nekaj.trycloudflare.com');
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

$('register').addEventListener('click', async () => {
  try {
    validateAuth();
    status('AUTH / Ustvarjam račun ...');
    const d = await request('/auth/register', {method: 'POST', body: JSON.stringify(authBody())});
    token = d.token;
    localStorage.setItem('pv_token', token);
    updateAuthUi('Registriran in prijavljen. Workspace je odklenjen.');
    status('AUTH OK\nRačun je ustvarjen. Zdaj lahko zaženeš autonomous build.');
    loadRecentProjects();
  } catch (e) {
    const hint = /already registered/i.test(e.message) ? '\nTa e-pošta že obstaja — uporabi Prijava.' : '';
    status(`NAPAKA REGISTRACIJE\n${e.message}${hint}`);
  }
});

$('login').addEventListener('click', async () => {
  try {
    validateAuth();
    status('AUTH / Prijavljam ...');
    const d = await request('/auth/login', {method: 'POST', body: JSON.stringify(authBody())});
    token = d.token;
    localStorage.setItem('pv_token', token);
    updateAuthUi('Prijava uspešna. Workspace je odklenjen.');
    status('AUTH OK\nPrijava uspešna.');
    loadRecentProjects();
  } catch (e) {
    status(`NAPAKA PRIJAVE\n${e.message}`);
  }
});

$('logout').addEventListener('click', () => {
  token = '';
  localStorage.removeItem('pv_token');
  updateAuthUi('Odjavljen.');
  status('Lokalna prijavna seja je odstranjena iz brskalnika.');
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
    el.querySelector('em').textContent = 'waiting';
  });
}

const pipelineOrder = ['queued', 'designing', 'building', 'auditing', 'fixing', 'publishing', 'ready'];
function pipelineIndex(statusName) {
  if (statusName === 'needs_review') return pipelineOrder.indexOf('ready');
  return pipelineOrder.indexOf(statusName);
}

function updatePipeline(current) {
  const idx = pipelineIndex(current);
  const map = {
    queued: 0,
    designing: 1,
    building: 2,
    auditing: 3,
    fixing: 4,
    publishing: 5,
    ready: 5,
    needs_review: 5
  };
  const active = map[current] ?? idx;
  document.querySelectorAll('.pipe').forEach((el, i) => {
    el.classList.remove('running', 'done');
    const em = el.querySelector('em');
    if (i < active || (current === 'ready' && i <= active)) {
      el.classList.add('done');
      em.textContent = 'done';
    } else if (i === active && !['ready', 'needs_review'].includes(current)) {
      el.classList.add('running');
      em.textContent = 'running';
    } else if (current === 'needs_review' && i === active) {
      el.classList.add('running');
      em.textContent = 'review';
    } else {
      em.textContent = 'waiting';
    }
  });
}

$('generate').addEventListener('click', async () => {
  if (!token) {
    status('BUILD BLOKIRAN\nNajprej se registriraj ali prijavi.');
    return;
  }
  try {
    validateProject();
    const healthy = await checkHealth(false);
    if (!healthy) throw new Error('Agent API ni online.');
    resetPipeline();
    updatePipeline('queued');
    $('resultActions').classList.remove('visible');
    status('BUILD 01/06\nProjekt pošiljam v agentsko čakalno vrsto ...');
    const created = await request('/projects', {method: 'POST', body: JSON.stringify(payload())});
    activeProjectId = created.id;
    status(`BUILD STARTED\nProject ID: ${created.id}\n\nAgent prevzema brief in začenja načrtovanje.`);
    watch(created.id);
  } catch (e) {
    status(`BUILD NI ZAGNAN\n${e.message}`);
  }
});

async function watch(id) {
  for (let i = 0; i < 180; i++) {
    await new Promise(r => setTimeout(r, 4000));
    try {
      const p = await request(`/projects/${id}`);
      const issues = p.last_audit?.issues || [];
      updatePipeline(p.status);
      const severe = issues.filter(x => ['critical', 'high'].includes(x.severity)).length;
      status([
        `PROJECT ${p.status.toUpperCase()}`,
        `ID: ${id}`,
        `Model: ${$('modelState').textContent}`,
        `GitHub repo: ${p.repo_name || 'še ni ustvarjen'}`,
        `Self-fix attempts: ${p.auto_fix_attempts}`,
        `QA issues: ${issues.length} (${severe} critical/high)`,
        '',
        ...issues.slice(0, 8).map(x => `• ${x.severity.toUpperCase()} / ${x.code || 'QA'} / ${x.message}`)
      ].join('\n'));
      if (p.repo_name) {
        $('repoLink').href = `https://github.com/${GITHUB_OWNER}/${p.repo_name}`;
      }
      if (['ready', 'needs_review', 'failed'].includes(p.status)) {
        $('resultActions').classList.add('visible');
        return;
      }
    } catch (e) {
      status(`STATUS CHECK FAILED\n${e.message}`);
      return;
    }
  }
  status('Build še vedno teče. Osveži projektni status pozneje.');
}

$('newBuild').addEventListener('click', () => {
  activeProjectId = null;
  resetPipeline();
  $('resultActions').classList.remove('visible');
  status('Pripravljen za nov build.');
  window.scrollTo({top: 0, behavior: 'smooth'});
});

async function loadRecentProjects() {
  if (!token) return;
  try {
    const projects = await request('/projects');
    if (!projects.length) return;
    const p = projects[0];
    activeProjectId = p.id;
    if (p.status) updatePipeline(p.status);
    if (p.repo_name) {
      $('repoLink').href = `https://github.com/${GITHUB_OWNER}/${p.repo_name}`;
      $('resultActions').classList.add('visible');
    }
  } catch {}
}

function updatePreview() {
  const canvas = $('previewCanvas');
  canvas.style.setProperty('--preview-bg', $('background').value);
  canvas.style.setProperty('--preview-text', $('textColor').value);
  canvas.style.setProperty('--preview-primary', $('primary').value);
  canvas.style.setProperty('--preview-secondary', $('secondary').value);
  $('previewLogo').textContent = ($('organization').value || $('name').value || 'YOUR PROJECT').toUpperCase().slice(0, 28);
  $('previewEyebrow').textContent = ($('programme').value || 'PROJECT / DIGITAL EXPERIENCE').toUpperCase().slice(0, 42);
  $('previewTitle').textContent = $('heroTitle').value || $('name').value || 'Spletna stran, ki ima jasen namen.';
  $('previewSubtitle').textContent = $('heroSubtitle').value || $('goal').value || 'Agent bo iz tvojega briefa sestavil celotno informacijsko arhitekturo, vsebino in responsive frontend.';
  $('previewCta').textContent = $('cta').value || 'Kontaktirajte nas';
}

['name','organization','programme','goal','heroTitle','heroSubtitle','cta','primary','secondary','background','textColor'].forEach(id => $(id).addEventListener('input', updatePreview));

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
