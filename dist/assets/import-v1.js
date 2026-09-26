(() => {
  const inputId='pvZipImportInput';
  const stateId='pvZipImportState';
  let selectedZip=null;

  function esc(v){return String(v||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
  function styles(){
    if(document.getElementById('pvImportStyles'))return;
    const s=document.createElement('style');s.id='pvImportStyles';s.textContent=`
      .zip-import{padding:1.15rem;border:1px solid #cddbd4;border-radius:1.2rem;background:#fff;box-shadow:var(--shadow);min-width:0;overflow:hidden}
      .zip-import-head{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.zip-import-head strong{display:block;font-size:.82rem}.zip-import-head span{display:block;margin-top:.12rem;color:var(--muted);font-size:.65rem;line-height:1.4}.zip-badge{display:inline-flex!important;margin:0!important;padding:.28rem .48rem;border-radius:999px;background:#071d17;color:var(--lime)!important;font-size:.55rem!important;font-weight:900}
      .zip-drop{display:grid;place-items:center;min-height:6.25rem;margin-top:.75rem;padding:1rem;border:1.5px dashed #93aa9f;border-radius:.85rem;background:#f5f9f7;text-align:center;cursor:pointer;transition:.18s}.zip-drop.drag{background:#e5f2eb;border-color:var(--good)}.zip-drop b{display:block;font-size:1rem}.zip-drop span{display:block;margin-top:.25rem;color:var(--muted);font-size:.62rem}.zip-actions{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:.7rem;margin-top:.65rem;min-width:0}.zip-state{min-width:0;max-width:100%;color:var(--muted);font-size:.62rem;white-space:normal;overflow-wrap:anywhere;line-height:1.45}.zip-state.ready{color:var(--good);font-weight:800}.zip-import button{border:0;border-radius:.65rem;background:var(--ink);color:#fff;padding:.62rem .8rem;font-size:.65rem;font-weight:850;cursor:pointer}.zip-import button:disabled{opacity:.45;cursor:not-allowed}
      @media(max-width:650px){.zip-import-head,.zip-actions{align-items:stretch;flex-direction:column}.zip-import button{width:100%}}
    `;document.head.appendChild(s);
  }
  function apiBase(){try{return String(API||'').replace(/\/$/,'')}catch{return String(window.PV_RUNTIME?.apiBase||localStorage.getItem('pv_api_url')||'').replace(/\/$/,'')}}
  function authToken(){try{return String(token||'')}catch{return localStorage.getItem('pv_token')||''}}
  function validate(file){
    if(!file)return 'Izberi ZIP.';
    if(!/\.zip$/i.test(file.name))return 'Datoteka mora biti .zip.';
    if(file.size>32*1024*1024)return 'ZIP je večji od 32 MB.';
    return '';
  }
  function setState(text,ready=false){const el=document.getElementById(stateId);if(el){el.textContent=text;el.classList.toggle('ready',ready);}}
  function pick(file){
    const error=validate(file);if(error){selectedZip=null;setState(error);document.getElementById('pvImportZip')?.setAttribute('disabled','');return;}
    selectedZip=file;setState(`${file.name} · ${(file.size/1024/1024).toFixed(1)} MB`,true);document.getElementById('pvImportZip')?.removeAttribute('disabled');
  }
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function waitForImport(projectId,api,jwt){
    const started=Date.now();
    let transientErrors=0;
    while(Date.now()-started<240000){
      try{
        const res=await fetch(`${api}/projects/${encodeURIComponent(projectId)}?pv=${Date.now()}`,{
          headers:{Authorization:`Bearer ${jwt}`},cache:'no-store'
        });
        const raw=await res.text();
        let project;
        try{project=JSON.parse(raw)}catch{project=null}
        if(!res.ok||!project){
          transientErrors++;
          if(transientErrors>5)throw new Error('Status importa trenutno ni dosegljiv.');
          await sleep(1800);
          continue;
        }
        transientErrors=0;
        const state=String(project.status||'');
        const audit=project.last_audit||{};
        if(state==='failed'){
          const issue=(audit.issues||[])[0];
          throw new Error(issue?.message||'ZIP import ni uspel.');
        }
        if(state==='ready'||state==='needs_review'){
          return project;
        }
        const labels={
          importing:'ZIP sprejet · pripravljam Git repozitorij …',
          repository_ready:'Git repozitorij pripravljen · začenjam pregled …',
          auditing:'Izvajam Visual QA in preverjam uvoženo stran …'
        };
        setState(labels[state]||`Import v teku · ${state||'obdelava'} …`,true);
      }catch(err){
        if(/ZIP import ni uspel|Status importa/.test(String(err.message||'')))throw err;
      }
      await sleep(1800);
    }
    return null;
  }

  async function runImport(){
    if(!selectedZip)return;
    const api=apiBase(),jwt=authToken();if(!api){setState('Najprej poveži API.');return}if(!jwt){setState('Najprej se prijavi.');return}
    const button=document.getElementById('pvImportZip');button.disabled=true;button.textContent='Uvažam in preverjam …';setState('Varno razširjam ZIP, izvajam audit in Visual QA …');
    try{
      const form=new FormData();form.append('file',selectedZip);form.append('name',document.getElementById('name')?.value.trim()||selectedZip.name.replace(/\.zip$/i,''));
      form.append('organization',document.getElementById('organization')?.value.trim()||'');form.append('package',document.getElementById('package')?.value||'Standard');
      form.append('goal',document.getElementById('goal')?.value.trim()||'Improve and maintain this imported website.');form.append('audience',document.getElementById('audience')?.value.trim()||'');form.append('programme',document.getElementById('programme')?.value.trim()||'Existing website import');
      const res=await fetch(`${api}/imports/site`,{method:'POST',headers:{Authorization:`Bearer ${jwt}`},body:form,cache:'no-store'});
      const raw=await res.text();
      let data=null;
      try{data=JSON.parse(raw)}catch{}
      if(!res.ok){
        if(/^\s*<(?:!doctype|html)/i.test(raw)){
          throw new Error(`Gateway je vrnil HTML namesto API odgovora (HTTP ${res.status}). Ponovi po restartu agenta; ZIP ni problem.`);
        }
        throw new Error(typeof data?.detail==='string'?data.detail:`HTTP ${res.status}`);
      }
      if(!data?.id){
        throw new Error('API ni vrnil ID-ja uvoženega projekta.');
      }
      setState(`ZIP sprejet: ${data.files} datotek · import teče v ozadju …`,true);
      const project=await waitForImport(data.id,api,jwt);
      if(!project){
        setState('Import še teče v ozadju. Projekt lahko spremljaš v Dashboardu.',true);
        button.disabled=false;button.textContent='Preveri / uvozi znova';
        return;
      }
      const score=project.last_audit?.visual_qa?.score;
      setState(`Uvoženo · Visual QA ${score??'—'}/100 · odpiram Source Editor …`,true);
      const url=new URL('editor.html',location.href);url.searchParams.set('project',data.id);if(api)url.searchParams.set('api',api);location.href=url.href;
    }catch(err){setState('NAPAKA: '+err.message);button.disabled=false;button.textContent='Uvozi ZIP →';}
  }
  function install(){
    const card=document.getElementById('mediaStudioCard');const main=document.querySelector('.maincol');if(!card||!main||document.getElementById('pvZipImport'))return;styles();
    const box=document.createElement('section');box.id='pvZipImport';box.className='zip-import';box.innerHTML=`
      <div class="zip-import-head"><div><strong>Uvozi obstoječo spletno stran</strong><span>Spusti ZIP s statičnim HTML/CSS/JS projektom. Uvoz se shrani takoj, Git + Visual QA pa tečeta v ozadju, zato povezava ne timeouta.</span></div><span class="zip-badge">ZIP → WORKSPACE</span></div>
      <input id="${inputId}" type="file" accept=".zip,application/zip" hidden>
      <div class="zip-drop" id="pvZipDrop" role="button" tabindex="0"><div><b>Spusti website.zip sem</b><span>do 32 MB · varen static-site import · executables in server-side koda se zavrnejo</span></div></div>
      <div class="zip-actions"><div class="zip-state" id="${stateId}">Ni izbranega ZIP-a.</div><button id="pvImportZip" type="button" disabled>Uvozi ZIP →</button></div>`;
    main.insertBefore(box,card);
    const input=document.getElementById(inputId),drop=document.getElementById('pvZipDrop');
    drop.addEventListener('click',()=>input.click());drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click()}});
    input.addEventListener('change',()=>pick(input.files?.[0]));
    ['dragenter','dragover'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.add('drag')}));
    ['dragleave','drop'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.remove('drag')}));
    drop.addEventListener('drop',e=>pick(Array.from(e.dataTransfer?.files||[]).find(f=>/\.zip$/i.test(f.name))||e.dataTransfer?.files?.[0]));
    document.getElementById('pvImportZip').addEventListener('click',runImport);

    // Clipboard image paste enhancement for the existing media studio.
    document.addEventListener('paste',event=>{
      const files=Array.from(event.clipboardData?.files||[]).filter(f=>/^image\//.test(f.type));if(!files.length)return;
      const imageInput=document.getElementById('projectImages');if(!imageInput)return;
      try{const dt=new DataTransfer();files.forEach(f=>dt.items.add(f));imageInput.files=dt.files;imageInput.dispatchEvent(new Event('change',{bubbles:true}));if(typeof status==='function')status(`SLIKA IZ ODLOŽIŠČA\nDodano: ${files.length}`)}catch{}
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();