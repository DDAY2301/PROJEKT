(() => {
  const inputId='pvBriefInput';
  const stateId='pvBriefState';
  let selectedFile=null;

  function esc(v){return String(v||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
  function apiBase(){try{return String(API||'').replace(/\/$/,'')}catch{return String(window.PV_RUNTIME?.apiBase||localStorage.getItem('pv_api_url')||'').replace(/\/$/,'')}}
  function authToken(){try{return String(token||'')}catch{return localStorage.getItem('pv_token')||''}}

  function styles(){
    if(document.getElementById('pvBriefStyles'))return;
    const s=document.createElement('style');
    s.id='pvBriefStyles';
    s.textContent='.brief-import{padding:1.2rem;border:1px solid #cddbd4;border-radius:1.2rem;background:linear-gradient(145deg,#fff,#f6faf8);box-shadow:var(--shadow);min-width:0;overflow:hidden}.brief-import-head{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start}.brief-import-head strong{display:block;font-size:.9rem}.brief-import-head span{display:block;margin-top:.15rem;color:var(--muted);font-size:.66rem;line-height:1.45}.brief-badge{display:inline-flex!important;margin:0!important;padding:.3rem .5rem;border-radius:999px;background:#071d17;color:var(--lime)!important;font-size:.56rem!important;font-weight:900;white-space:nowrap}.brief-tabs{display:grid;grid-template-columns:1fr 1fr;gap:.55rem;margin-top:.8rem}.brief-drop,.brief-command{min-width:0;border:1.5px dashed #93aa9f;border-radius:.9rem;background:#f7faf8}.brief-drop{display:grid;place-items:center;min-height:8.3rem;padding:1rem;text-align:center;cursor:pointer;transition:.18s}.brief-drop.drag{border-color:var(--good);background:#e6f3ec;transform:translateY(-1px)}.brief-drop b{display:block;font-size:.95rem}.brief-drop span{display:block;margin-top:.3rem;color:var(--muted);font-size:.62rem;line-height:1.45}.brief-command{padding:.75rem}.brief-command label{display:block;font-size:.68rem;font-weight:850}.brief-command textarea{width:100%;min-height:5.3rem;margin-top:.4rem;border:1px solid #b9c8c1;border-radius:.72rem;background:#fff;padding:.65rem;resize:vertical;color:var(--ink);font-size:.68rem;line-height:1.45}.brief-command textarea:focus{outline:0;border-color:var(--good);box-shadow:0 0 0 4px rgba(29,123,98,.08)}.brief-command button,.brief-actions button{border:0;border-radius:.65rem;background:var(--ink);color:#fff;padding:.6rem .78rem;font-size:.64rem;font-weight:850;cursor:pointer}.brief-command button{margin-top:.45rem;width:100%}.brief-actions{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.7rem;align-items:center;margin-top:.7rem}.brief-state{min-width:0;color:var(--muted);font-size:.63rem;line-height:1.5;overflow-wrap:anywhere}.brief-state.ready{color:var(--good);font-weight:800}.brief-state.warn{color:#91670a}.brief-actions button:disabled,.brief-command button:disabled{opacity:.45;cursor:not-allowed}.brief-result{display:none;margin-top:.7rem;padding:.7rem;border-radius:.75rem;background:#edf5f1;color:#315448;font-size:.64rem;line-height:1.45}.brief-result.visible{display:block}@media(max-width:760px){.brief-tabs{grid-template-columns:1fr}.brief-import-head{flex-direction:column}.brief-actions{grid-template-columns:1fr}.brief-actions button{width:100%}}';
    document.head.appendChild(s);
  }

  function validate(file){
    if(!file)return 'Izberi TXT, MD ali JSON dokument.';
    if(!/\.(txt|md|json)$/i.test(file.name))return 'Podprti so .txt, .md in .json dokumenti.';
    if(file.size>256*1024)return 'Dokument je večji od 256 KB.';
    return '';
  }

  function setState(text,kind){
    const el=document.getElementById(stateId);
    if(!el)return;
    el.textContent=text;
    el.classList.toggle('ready',kind==='ready');
    el.classList.toggle('warn',kind==='warn');
  }

  function pick(file){
    const error=validate(file);
    const btn=document.getElementById('pvApplyBrief');
    if(error){selectedFile=null;setState(error,'warn');if(btn)btn.disabled=true;return}
    selectedFile=file;
    setState(file.name+' · '+Math.max(1,Math.round(file.size/1024))+' KB · pripravljen za analizo','ready');
    if(btn)btn.disabled=false;
  }

  function setField(id,value){
    if(value===undefined||value===null||value==='')return false;
    const el=document.getElementById(id);
    if(!el)return false;
    el.value=String(value);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    return true;
  }

  function applyPackage(value){
    if(!['Start','Standard','Premium'].includes(value))return false;
    const button=document.querySelector('.pkg[data-package="'+value+'"]');
    if(button){button.click();return true}
    return setField('package',value);
  }

  function pagesText(pages){
    if(!Array.isArray(pages))return '';
    return pages.map(function(p){
      if(typeof p==='string')return p.trim();
      const title=String((p&&p.title)||'').trim();
      const purpose=String((p&&p.purpose)||'').trim();
      return title+(purpose?' | '+purpose:'');
    }).filter(Boolean).join('\n');
  }

  function applyFields(data){
    const f=(data&&data.fields)||{};
    let count=0;
    if(applyPackage(f.package))count++;
    const mapping={name:'name',organization:'organization',programme:'programme',audience:'audience',goal:'goal',tone:'tone',hero_title:'heroTitle',hero_subtitle:'heroSubtitle',cta_text:'cta',contact_email:'contact',image_direction:'imageDirection',custom_requirements:'requirements'};
    Object.entries(mapping).forEach(function(entry){if(setField(entry[1],f[entry[0]]))count++});
    if(setField('pages',pagesText(f.pages)))count++;
    const brand=f.brand||{};
    const brandMap={primary_color:'primary',secondary_color:'secondary',background_color:'background',text_color:'textColor',font_style:'fontStyle',mood:'mood'};
    Object.entries(brandMap).forEach(function(entry){if(setField(entry[1],brand[entry[0]]))count++});

    const result=document.getElementById('pvBriefResult');
    if(result){
      const warnings=(data.warnings||[]).map(esc).join(' ');
      result.innerHTML='<strong>Auto-fill končan.</strong> Izpolnjenih/posodobljenih polj: '+count+'. Parser: '+esc(data.parser||'—')+'.'+(warnings?'<br>'+warnings:'');
      result.classList.add('visible');
    }
    try{
      if(typeof status==='function')status('TEXT BRIEF AUTO-FILL\n'+(data.source_name||'Dokument')+'\nIzpolnjena polja: '+count+'\nPreglej brief in nato zaženi izdelavo.');
    }catch{}
  }

  async function send(file){
    const api=apiBase(),jwt=authToken();
    if(!api)throw new Error('Najprej poveži API.');
    if(!jwt)throw new Error('Najprej se prijavi.');
    const form=new FormData();
    form.append('file',file);
    const res=await fetch(api+'/imports/brief',{method:'POST',headers:{Authorization:'Bearer '+jwt},body:form,cache:'no-store'});
    const raw=await res.text();
    let data=null;
    try{data=JSON.parse(raw)}catch{}
    if(!res.ok)throw new Error(typeof (data&&data.detail)==='string'?data.detail:'HTTP '+res.status);
    if(!data||!data.fields)throw new Error('API ni vrnil strukturiranega briefa.');
    return data;
  }

  async function runFile(){
    if(!selectedFile)return;
    const btn=document.getElementById('pvApplyBrief');
    btn.disabled=true;btn.textContent='Analiziram …';setState('Berem dokument in pripravljam celoten website brief …');
    try{
      const data=await send(selectedFile);
      applyFields(data);
      setState(selectedFile.name+' · auto-fill uspešen','ready');
    }catch(err){
      setState('NAPAKA: '+String(err.message||err),'warn');
    }finally{
      btn.disabled=false;btn.textContent='Izpolni celoten brief →';
    }
  }

  async function runCommand(){
    const el=document.getElementById('pvBriefCommand');
    const text=(el&&el.value.trim())||'';
    if(!text){setState('Najprej napiši opis ali ukaz za stran.','warn');return}
    const btn=document.getElementById('pvBriefCommandApply');
    btn.disabled=true;btn.textContent='Analiziram …';
    try{
      const file=new File([text],'website-brief.txt',{type:'text/plain;charset=utf-8'});
      const data=await send(file);
      applyFields(data);
      setState('Tekstovni ukaz je izpolnil website brief.','ready');
    }catch(err){
      setState('NAPAKA: '+String(err.message||err),'warn');
    }finally{
      btn.disabled=false;btn.textContent='Uporabi tekstovni ukaz';
    }
  }

  function install(){
    const media=document.getElementById('mediaStudioCard');
    const main=document.querySelector('.maincol');
    if(!media||!main||document.getElementById('pvBriefImport'))return;
    styles();
    const box=document.createElement('section');
    box.id='pvBriefImport';
    box.className='brief-import';
    box.innerHTML='<div class="brief-import-head"><div><strong>Auto-fill iz tekstovnega briefa</strong><span>Spusti TXT/MD/JSON ali napiši prost opis. Sistem sam izpolni projekt, strani, hero, CTA, barve, font, vizualno smer, fotografije in dodatne zahteve.</span></div><span class="brief-badge">TEXT → FULL WEBSITE BRIEF</span></div><div class="brief-tabs"><div><input id="'+inputId+'" type="file" accept=".txt,.md,.json,text/plain,text/markdown,application/json" hidden><div class="brief-drop" id="pvBriefDrop" role="button" tabindex="0"><div><b>Spusti brief.txt sem</b><span>TXT · MD · JSON · do 256 KB<br>Deluje tudi z navadnim prostim opisom, ne samo s točno določenim formatom.</span></div></div></div><div class="brief-command"><label for="pvBriefCommand">Ali napiši ukaz / opis strani</label><textarea id="pvBriefCommand" placeholder="Primer: Naredi moderno premium spletno stran za čistilni servis DALIJA. Uporabi temno zeleno in belo, 5 strani: Domov, Storitve, Cenik, O nas, Kontakt. Hero naj poudari zanesljivost in hitro ponudbo."></textarea><button id="pvBriefCommandApply" type="button">Uporabi tekstovni ukaz</button></div></div><div class="brief-actions"><div class="brief-state" id="'+stateId+'">Ni izbranega dokumenta.</div><button id="pvApplyBrief" type="button" disabled>Izpolni celoten brief →</button></div><div class="brief-result" id="pvBriefResult"></div>';
    main.insertBefore(box,media);

    const input=document.getElementById(inputId);
    const drop=document.getElementById('pvBriefDrop');
    drop.addEventListener('click',function(){input.click()});
    drop.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click()}});
    input.addEventListener('change',function(){pick(input.files&&input.files[0])});
    ['dragenter','dragover'].forEach(function(name){drop.addEventListener(name,function(e){e.preventDefault();drop.classList.add('drag')})});
    ['dragleave','drop'].forEach(function(name){drop.addEventListener(name,function(e){e.preventDefault();drop.classList.remove('drag')})});
    drop.addEventListener('drop',function(e){
      const files=Array.from((e.dataTransfer&&e.dataTransfer.files)||[]);
      pick(files.find(function(f){return /\.(txt|md|json)$/i.test(f.name)})||files[0]);
    });
    document.getElementById('pvApplyBrief').addEventListener('click',runFile);
    document.getElementById('pvBriefCommandApply').addEventListener('click',runCommand);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();