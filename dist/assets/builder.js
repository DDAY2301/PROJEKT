const params = new URLSearchParams(window.location.search);
const apiParam = params.get('api');
if (apiParam) localStorage.setItem('pv_api_url', apiParam.replace(/\/$/, ''));
const API = localStorage.getItem('pv_api_url') || ((location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? location.origin : 'http://localhost:8000');
let token = localStorage.getItem('pv_token') || '';
const $ = id => document.getElementById(id);
const status = msg => $('status').textContent = msg;

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

async function request(path, options={}) {
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${API}${path}`, {...options, headers});
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = {detail:text}; }
  if (!r.ok) throw new Error(errorMessage(data, `HTTP ${r.status}`));
  return data;
}

async function checkHealth(){
  try {
    const h = await request('/health');
    status(`API povezan. Model: ${h.model}. GitHub publishing: ${h.github_configured ? 'DA' : 'NE'}.`);
  } catch(e) {
    status(`API ni dosegljiv na ${API}. ${e.message}`);
  }
}

function authBody(){
  return {email:$('email').value.trim(), password:$('password').value};
}

function validateAuth(){
  const email = $('email').value.trim();
  const password = $('password').value;
  if (!email) throw new Error('Vpiši e-poštni naslov.');
  if (!email.includes('@')) throw new Error('Vpiši veljaven e-poštni naslov.');
  if (password.length < 8) throw new Error('Geslo mora imeti najmanj 8 znakov.');
}

$('register').addEventListener('click', async () => {
  try {
    validateAuth();
    status('Ustvarjam račun ...');
    const d=await request('/auth/register',{method:'POST',body:JSON.stringify(authBody())});
    token=d.token; localStorage.setItem('pv_token',token);
    $('authState').textContent='Registriran in prijavljen.';
    status('Račun je pripravljen. Zdaj lahko oddaš projekt agentu.');
  }
  catch(e){ status(`Napaka registracije: ${e.message}`); }
});

$('login').addEventListener('click', async () => {
  try {
    validateAuth();
    status('Prijavljam ...');
    const d=await request('/auth/login',{method:'POST',body:JSON.stringify(authBody())});
    token=d.token; localStorage.setItem('pv_token',token);
    $('authState').textContent='Prijavljen.';
    status('Prijava uspešna.');
  }
  catch(e){ status(`Napaka prijave: ${e.message}`); }
});

function parsePages(){
  return $('pages').value.split('\n').map(x=>x.trim()).filter(Boolean).map((line,i)=>{
    const [title,purpose=''] = line.split('|').map(x=>x.trim());
    const slug = i===0 ? 'index' : title.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
    return {slug,title,purpose};
  });
}

$('generate').addEventListener('click', async () => {
  if(!token){ status('Najprej se registriraj ali prijavi.'); return; }
  const payload={
    name:$('name').value.trim(), organization:$('organization').value.trim(), package:$('package').value,
    programme:$('programme').value.trim(), goal:$('goal').value.trim(), audience:$('audience').value.trim(), tone:$('tone').value.trim(),
    brand:{primary_color:$('primary').value,secondary_color:$('secondary').value,background_color:$('background').value,text_color:$('textColor').value,font_style:$('fontStyle').value,mood:$('mood').value.trim()},
    pages:parsePages(), hero_title:$('heroTitle').value.trim(), hero_subtitle:$('heroSubtitle').value.trim(), cta_text:$('cta').value.trim(),
    contact_email:$('contact').value.trim()||null, image_direction:$('imageDirection').value.trim(), custom_requirements:$('requirements').value.trim()
  };
  try {
    status('Projekt oddan agentu … načrtovanje se začenja.');
    const created=await request('/projects',{method:'POST',body:JSON.stringify(payload)});
    status(`Projekt ${created.id} je v čakalni vrsti.\nAgent načrtuje, gradi, preverja in popravlja stran.`);
    watch(created.id);
  } catch(e){ status(`Napaka: ${e.message}`); }
});

async function watch(id){
  for(let i=0;i<120;i++){
    await new Promise(r=>setTimeout(r,5000));
    try{
      const p=await request(`/projects/${id}`);
      const issues=p.last_audit?.issues||[];
      status(`Status: ${p.status}\nGitHub repo: ${p.repo_name||'še ni ustvarjen'}\nSamodejni popravki: ${p.auto_fix_attempts}\nQA težave: ${issues.length}\n${issues.slice(0,8).map(x=>`- ${x.severity}: ${x.message}`).join('\n')}`);
      if(['ready','needs_review','failed'].includes(p.status)) return;
    }catch(e){ status(`Preverjanje statusa ni uspelo: ${e.message}`); return; }
  }
}

const requestedPackage = params.get('paket');
if(['Start','Standard','Premium'].includes(requestedPackage)) $('package').value=requestedPackage;

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
    if (['Start','Standard','Premium'].includes(p.package)) $('package').value = p.package;
    const extras = [];
    if (p.contact_name) extras.push(`Kontaktna oseba: ${p.contact_name}`);
    if (p.deadline) extras.push(`Želeni rok: ${p.deadline}`);
    if (p.existing_url) extras.push(`Obstoječa povezava: ${p.existing_url}`);
    if (extras.length && !$('requirements').value) $('requirements').value = extras.join('\n');
    localStorage.removeItem('pv_prefill');
  }
} catch {}

if(token) $('authState').textContent='Žeton prijave je shranjen v tem brskalniku.';
checkHealth();
