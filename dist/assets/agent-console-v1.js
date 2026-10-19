(() => {
  const $ = id => document.getElementById(id);
  let inflight = false;
  let lastLoadedSignature = '';
  let lastLoadedAt = 0;
  let refreshTimer = null;
  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      if (document.visibilityState === 'hidden') return;
      const signature = apiBase() + ':' + Boolean(authToken());
      // A transient "Preverjam" -> "Online" signal or ordinary status poll
      // must not trigger four expensive agent/preflight API calls again.
      if (signature !== lastLoadedSignature || Date.now() - lastLoadedAt > 120000) load();
    }, 350);
  }

  function apiBase() {
    try {
      if (typeof API !== 'undefined' && API) return String(API).replace(/\/$/,'');
    } catch {}
    return String(window.PV_RUNTIME?.apiBase || localStorage.getItem('pv_api_url') || '').replace(/\/$/,'');
  }
  function authToken() {
    try {
      if (typeof token !== 'undefined' && token) return token;
    } catch {}
    return localStorage.getItem('pv_token') || '';
  }
  async function get(path) {
    const api=apiBase(), jwt=authToken();
    if(!api) throw new Error('API ni povezan.');
    if(!jwt) throw new Error('Prijavi se za pregled lokalnega agenta.');
    const res=await fetch(api+path,{headers:{Authorization:`Bearer ${jwt}`}});
    const text=await res.text(); let data; try{data=JSON.parse(text)}catch{data={detail:text}}
    if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:`HTTP ${res.status}`);
    return data;
  }
  function styles(){
    if($('pvAgentConsoleStyles'))return;
    const s=document.createElement('style');s.id='pvAgentConsoleStyles';s.textContent=`
      .agent-console{padding:.95rem;border:1px solid var(--line);border-radius:1.2rem;background:#071d17;color:#fff;box-shadow:var(--shadow)}
      .agent-console-head{display:flex;align-items:flex-start;justify-content:space-between;gap:.6rem}.agent-console h3{margin:0;color:#fff;font-size:.88rem}.agent-console p{margin:.2rem 0 0;color:#8fa79e;font-size:.62rem;line-height:1.4}
      .agent-refresh{border:1px solid rgba(255,255,255,.15);border-radius:.55rem;background:rgba(255,255,255,.04);color:#fff;padding:.38rem .5rem;font-size:.58rem;font-weight:850;cursor:pointer}
      .agent-summary{display:grid;grid-template-columns:1fr 1fr;gap:.42rem;margin-top:.7rem}.agent-metric{padding:.55rem;border:1px solid rgba(255,255,255,.08);border-radius:.65rem;background:rgba(255,255,255,.025)}.agent-metric span{display:block;color:#789188;font-size:.53rem;text-transform:uppercase;letter-spacing:.06em}.agent-metric strong{display:block;margin-top:.13rem;color:var(--lime);font-size:.67rem;word-break:break-word}
      .agent-runtime{display:flex;gap:.3rem;flex-wrap:wrap;margin-top:.6rem}.agent-pill{padding:.28rem .4rem;border-radius:999px;background:rgba(255,255,255,.06);color:#9eb3aa;font-size:.52rem;font-weight:800}.agent-pill.ok{background:rgba(217,255,101,.1);color:var(--lime)}
      .agent-model-list{display:grid;gap:.3rem;margin-top:.4rem}.agent-model-row{display:flex;justify-content:space-between;gap:.5rem;padding:.38rem .45rem;border:1px solid rgba(255,255,255,.08);border-radius:.5rem;font-size:.55rem}.agent-model-row b{font-weight:850;color:#fff;overflow-wrap:anywhere}.agent-model-status{flex-shrink:0;color:#96aea5;font-size:.51rem}.agent-model-status.running{color:var(--lime)}.agent-features{margin-top:.65rem;padding-top:.6rem;border-top:1px solid rgba(255,255,255,.08);color:#b7c8c1;font-size:.57rem;line-height:1.5}.agent-error{margin-top:.65rem;color:#ffb2b2;font-size:.6rem;white-space:pre-wrap}
      @media(max-width:1220px){.agent-console{grid-column:auto}}@media(max-width:520px){.agent-summary{grid-template-columns:1fr}}
    `;document.head.appendChild(s);
  }
  function install(){
    const side=document.querySelector('.side');if(!side||$('pvAgentConsole'))return;styles();
    const card=document.createElement('section');card.id='pvAgentConsole';card.className='agent-console';card.innerHTML=`
      <div class="agent-console-head"><div><h3>Local Agent Engine</h3><p>Modeli, runtime in odprtokodne zmogljivosti, ki so dejansko aktivne na tem računalniku.</p></div><button class="agent-refresh" id="pvAgentRefresh" type="button">Osveži</button></div>
      <div id="pvAgentBody"><div class="agent-error">Prijavi se in poveži API za pregled.</div></div>`;
    const readiness=$('projectReadiness'); readiness?.after(card) || side.prepend(card);
    $('pvAgentRefresh').addEventListener('click', () => load(true));
    const auth=$('authState'); if(auth)new MutationObserver(scheduleRefresh).observe(auth,{childList:true,subtree:true});
    const api=$('apiState'); if(api)new MutationObserver(scheduleRefresh).observe(api,{childList:true,subtree:true});
    setTimeout(() => load(true),500);
  }
  function escapeHtml(value){
    return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function runtimeState(value){
    if(typeof value==='boolean') return {active:value,label:value?'ON':'OFF'};
    if(typeof value==='number') return {active:Number.isFinite(value)&&value>0,label:String(value)};
    if(value && typeof value==='object'){
      if('available' in value) return {active:Boolean(value.available),label:value.available?'ON':'OFF'};
      return {active:true,label:'ON'};
    }
    if(typeof value==='string') return {active:value.trim().length>0,label:value.trim()||'OFF'};
    return {active:false,label:'OFF'};
  }
  async function load(force = false){
    const body=$('pvAgentBody');
    if(!body || inflight) return;
    const signature = apiBase() + ':' + Boolean(authToken());
    if(!force && signature === lastLoadedSignature && Date.now() - lastLoadedAt < 120000) return;
    inflight = true;
    lastLoadedSignature = signature;
    lastLoadedAt = Date.now();
    body.innerHTML='<div class="agent-error">Preverjam lokalni agent …</div>';
    try{
      const [caps,models,supervisor,preflight,localModels]=await Promise.all([get('/agent/capabilities'),get('/agent/models'),get('/agent/supervisor'),get('/agent/preflight'),get('/agent/models/local').catch(()=>null)]);
      const runtime=caps.runtime||{};const features=caps.features||{};
      const available=Object.entries(runtime).filter(([,v])=>runtimeState(v).active);
      const enabled=Object.entries(features).filter(([,v])=>Boolean(v));
      const providers=[...new Set((models.backends||[]).map(x=>x.provider))];
      const inventory=Array.isArray(localModels?.models)?localModels.models:[];
      const localPanel=localModels?`
        <div class="agent-features"><strong>Lokalni Ollama · ${localModels.ollama_online?'dosegljiv':'nedosegljiv'}</strong> · izbrani model: ${escapeHtml(localModels.active_model||'—')}. Nameščen model še ni nujno naložen v RAM ali uspešno uporabljen.</div>
        <div class="agent-model-list">${inventory.filter(m=>m.installed||m.selected).slice(0,14).map(m=>`<div class="agent-model-row"><b>${escapeHtml(m.name)}</b><span class="agent-model-status ${m.loaded?'running':''}">${m.loaded?'V RAM-u':m.installed?'Nameščen':'Ni nameščen'}${m.selected?' · IZBRAN':''}</span></div>`).join('')||'<div class="agent-error">Ni zaznanih lokalnih modelov.</div>'}</div>
        <div class="agent-features">Zadnji dejanski klici: ${(localModels.recent||[]).slice(0,5).map(x=>`${escapeHtml(x.model)} · ${x.status==='ok'?'OK':'NAPAKA'} · ${Number(x.latency_ms)||0} ms`).join(' · ')||'še ni podatkov'}</div>` : '<div class="agent-features">Podatki o lokalnih modelih še niso dosegljivi.</div>';
      body.innerHTML=`
        <div class="agent-summary">
          <div class="agent-metric"><span>Fast model</span><strong>${models.primary||caps.agent?.primary_model||'—'}</strong></div>
          <div class="agent-metric"><span>Expert model</span><strong>${models.expert||caps.agent?.expert_model||'—'}</strong></div>
          <div class="agent-metric"><span>Routing</span><strong>${models.routing||caps.agent?.model_routing||'adaptive'}</strong></div>
          <div class="agent-metric"><span>Model backend</span><strong>${providers.join(' + ')||models.mode||'—'}</strong></div>
          <div class="agent-metric"><span>Capabilities</span><strong>${enabled.length} aktivnih</strong></div>
          <div class="agent-metric"><span>Runtime tools</span><strong>${available.length}/${Object.keys(runtime).length}</strong></div>
          <div class="agent-metric"><span>Supervisor</span><strong>${supervisor.enabled?'ON':'OFF'} · ${supervisor.active_recoveries?.length||0} recovery</strong></div>
          <div class="agent-metric"><span>Recovery policy</span><strong>${supervisor.max_recoveries||'—'} max · ${supervisor.interval_seconds||'—'}s</strong></div>
          <div class="agent-metric"><span>Production readiness</span><strong>${preflight.ready?'READY':'BLOCKED'}</strong></div>
          <div class="agent-metric"><span>Queue</span><strong>${preflight.checks?.queue?.running??0} running · ${preflight.checks?.queue?.queued??0} queued</strong></div>
        </div>
        <div class="agent-runtime">${Object.entries(runtime).map(([name,val])=>{const state=runtimeState(val);return `<span class="agent-pill ${state.active?'ok':''}">${name} · ${state.label}</span>`}).join('')}</div>
        <div class="agent-features">${enabled.map(([name])=>name.replaceAll('_',' ')).join(' · ')}</div>
        <div class="agent-features">supervisor: ${Object.entries(supervisor.decision_counts||{}).map(([k,v])=>`${k} ${v}`).join(' · ')||'no decisions yet'} · model ${supervisor.runtime?.model_online?'online':'offline'} · disk ${supervisor.runtime?.disk_free_gb??'—'} GB</div>
        <div class="agent-features">${preflight.blockers?.length ? 'BLOCKERS: '+preflight.blockers.join(' · ') : 'preflight OK'}${preflight.warnings?.length ? ' · warnings: '+preflight.warnings.join(' · ') : ''}</div>${localPanel}`;
    }catch(err){body.textContent = String(err.message || err);}
    finally{inflight = false;}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();