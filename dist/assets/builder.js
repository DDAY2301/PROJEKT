const API = localStorage.getItem('pv_api_url') || 'http://localhost:8000';
let token = localStorage.getItem('pv_token') || '';
const $ = id => document.getElementById(id);
const status = msg => $('status').textContent = msg;

async function request(path, options={}) {
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${API}${path}`, {...options, headers});
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = {detail:text}; }
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

function authBody(){ return {email:$('email').value.trim(), password:$('password').value}; }

$('register').addEventListener('click', async () => {
  try { const d=await request('/auth/register',{method:'POST',body:JSON.stringify(authBody())}); token=d.token; localStorage.setItem('pv_token',token); $('authState').textContent='Registriran in prijavljen.'; }
  catch(e){ status(`Napaka registracije: ${e.message}`); }
});

$('login').addEventListener('click', async () => {
  try { const d=await request('/auth/login',{method:'POST',body:JSON.stringify(authBody())}); token=d.token; localStorage.setItem('pv_token',token); $('authState').textContent='Prijavljen.'; }
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
  if(!token){ status('Najprej se prijavi.'); return; }
  const payload={
    name:$('name').value.trim(), organization:$('organization').value.trim(), package:$('package').value,
    programme:$('programme').value.trim(), goal:$('goal').value.trim(), audience:$('audience').value.trim(), tone:$('tone').value.trim(),
    brand:{primary_color:$('primary').value,secondary_color:$('secondary').value,background_color:$('background').value,text_color:$('textColor').value,font_style:$('fontStyle').value,mood:$('mood').value.trim()},
    pages:parsePages(), hero_title:$('heroTitle').value.trim(), hero_subtitle:$('heroSubtitle').value.trim(), cta_text:$('cta').value.trim(),
    contact_email:$('contact').value.trim()||null, image_direction:$('imageDirection').value.trim(), custom_requirements:$('requirements').value.trim()
  };
  try {
    status('Projekt oddan agentu …');
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
      if(['ready','needs_review'].includes(p.status)) return;
    }catch(e){ status(`Preverjanje statusa ni uspelo: ${e.message}`); return; }
  }
}

if(token) $('authState').textContent='Žeton prijave je shranjen v tem brskalniku.';
