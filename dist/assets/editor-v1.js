(() => {
  const qs=new URLSearchParams(location.search);
  const projectId=qs.get('project') || '';
  const configured=String(window.PV_RUNTIME?.apiBase || '').trim().replace(/\/$/,'');
  const API=String(qs.get('api') || configured || localStorage.getItem('pv_api_url') || '').trim().replace(/\/$/,'');
  const token=()=>localStorage.getItem('pv_token') || '';
  const $=id=>document.getElementById(id);
  let files=[];
  let activePath='';
  let savedContent='';
  let revisionPoll=0;

  function state(text,bad=false){$('editorStatus').textContent=text;$('editorStatus').style.color=bad?'#ff9292':'#82988f';}
  async function request(path,options={}){
    if(!API) throw new Error('API ni nastavljen. Odpri editor prek dashboarda ali nastavi runtime-config.');
    if(!token()) throw new Error('Prijava ni aktivna. Vrni se v dashboard in se prijavi.');
    const headers={...(options.headers||{}),Authorization:`Bearer ${token()}`};
    if(!(options.body instanceof FormData)) headers['Content-Type']=headers['Content-Type']||'application/json';
    const res=await fetch(`${API}${path}`,{...options,headers});
    const text=await res.text(); let data; try{data=JSON.parse(text)}catch{data={detail:text}}
    if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:`HTTP ${res.status}`);
    return data;
  }
  function ext(path){return (path.split('.').pop()||'').toLowerCase();}
  function dirty(){
    const changed=$('codeEditor').value!==savedContent;
    $('dirtyState').textContent=changed?'neshranjeno':'shranjeno';
    $('dirtyState').classList.toggle('changed',changed);
    $('saveFile').disabled=!activePath||!changed;
  }
  function renderFiles(){
    const q=$('fileSearch').value.trim().toLowerCase();
    const visible=files.filter(x=>!q||x.path.toLowerCase().includes(q));
    $('fileTree').innerHTML=visible.length?visible.map(x=>`<button class="file ${x.path===activePath?'active':''}" data-path="${x.path.replace(/"/g,'&quot;')}" data-ext="${ext(x.path)}" type="button">${x.path}</button>`).join(''):'<div class="empty">Ni zadetkov.</div>';
    $('fileTree').querySelectorAll('[data-path]').forEach(btn=>btn.addEventListener('click',()=>openFile(btn.dataset.path)));
  }
  async function loadFiles(openDefault=true){
    state('Nalagam datoteke …');
    const data=await request(`/projects/${encodeURIComponent(projectId)}/editor/files`);
    files=data.files||[];$('repoName').textContent=data.repo_name||'—';
    renderFiles();
    if(openDefault&&!activePath&&files.length){
      const pick=files.find(x=>x.path==='index.html')||files[0]; await openFile(pick.path);
    }
    state(`Naloženih ${files.length} editable datotek · ${String(data.head||'').slice(0,10)}`);
  }
  async function openFile(path){
    if(activePath&&$('codeEditor').value!==savedContent&&!confirm('Trenutna datoteka ima neshranjene spremembe. Zavrnem spremembe in odprem drugo datoteko?'))return;
    state(`Odpiram ${path} …`);
    const data=await request(`/projects/${encodeURIComponent(projectId)}/editor/file?path=${encodeURIComponent(path)}`);
    activePath=data.path;savedContent=data.content||'';$('codeEditor').disabled=false;$('codeEditor').value=savedContent;
    $('activePath').textContent=activePath;$('fileMeta').textContent=`${savedContent.length.toLocaleString('sl-SI')} znakov · ${String(data.sha||'').slice(0,10)}`;
    dirty();renderFiles();state(`${activePath} odprt.`);
  }
  async function save(){
    if(!activePath||$('codeEditor').value===savedContent)return;
    $('saveFile').disabled=true;state(`Preverjam in shranjujem ${activePath} …`);
    try{
      const data=await request(`/projects/${encodeURIComponent(projectId)}/editor/file`,{method:'PUT',body:JSON.stringify({path:activePath,content:$('codeEditor').value,message:`Manual editor: ${activePath}`})});
      savedContent=$('codeEditor').value;dirty();
      const warnings=(data.warnings||[]).join(' ');
      state(`Shranjeno · ${String(data.version||'').slice(0,10)}${warnings?' · '+warnings:''}`);
      await Promise.all([loadVersions(),loadFiles(false)]);
      await refreshPreview();
    }catch(err){state(err.message,true);dirty();}
  }
  async function refreshPreview(){
    $('previewState').textContent='nalagam';
    try{
      const session=await request(`/projects/${encodeURIComponent(projectId)}/preview-session`,{method:'POST'});
      if(!session.url)throw new Error('Preview URL ni na voljo.');
      $('previewFrame').src=session.url + (session.url.includes('?')?'&':'?') + 'editor=' + Date.now();
      $('previewState').textContent='live';
    }catch(err){$('previewState').textContent='napaka';state(err.message,true);}
  }
  async function loadVersions(){
    try{
      const versions=await request(`/projects/${encodeURIComponent(projectId)}/versions`);
      $('versions').innerHTML=versions.length?versions.map((v,i)=>`<div class="version"><div><strong>${(v.message||'Version').replace(/[<>&]/g,'')}</strong><span>${String(v.sha||'').slice(0,10)} · ${v.date?new Date(v.date).toLocaleString('sl-SI'):''}</span></div>${i===0?'':`<button type="button" data-rollback="${v.sha}">Rollback</button>`}</div>`).join(''):'<div class="empty">Ni verzij.</div>';
      $('versions').querySelectorAll('[data-rollback]').forEach(btn=>btn.addEventListener('click',()=>rollback(btn.dataset.rollback)));
    }catch(err){$('versions').innerHTML=`<div class="empty">${err.message}</div>`;}
  }
  async function rollback(sha){
    if(!confirm(`Obnovim spletno stran na verzijo ${sha.slice(0,10)}? Trenutna verzija ostane v Git zgodovini.`))return;
    state(`Rollback na ${sha.slice(0,10)} …`);
    try{
      const data=await request(`/projects/${encodeURIComponent(projectId)}/rollback`,{method:'POST',body:JSON.stringify({sha})});
      state(data.rolled_back?`Rollback objavljen · ${String(data.version||'').slice(0,10)}`:'Projekt je že na tej verziji.');
      activePath='';savedContent='';$('codeEditor').value='';$('codeEditor').disabled=true;
      await Promise.all([loadFiles(true),loadVersions(),refreshPreview()]);
    }catch(err){state(err.message,true);}
  }
  async function runRevision(){
    const instruction=$('revisionInstruction').value.trim();if(instruction.length<3){$('agentState').textContent='Vpiši konkretno zahtevo.';return;}
    $('runRevision').disabled=true;$('agentState').textContent='Agent sprejema nalogo …';
    try{
      const created=await request(`/projects/${encodeURIComponent(projectId)}/revise`,{method:'POST',body:JSON.stringify({instruction})});
      revisionPoll++;const mine=revisionPoll;
      for(let i=0;i<160;i++){
        await new Promise(r=>setTimeout(r,2500));if(mine!==revisionPoll)return;
        const p=await request(`/projects/${encodeURIComponent(projectId)}`);
        $('agentState').textContent=`Status: ${p.status}\nRevision: ${String(created.id||'').slice(0,8)}\nVisual QA: ${p.last_audit?.visual_qa?.score??'—'}`;
        if(['ready','needs_review','failed'].includes(p.status)){
          if(p.status==='failed')throw new Error(p.last_audit?.issues?.[0]?.message||'Revizija ni uspela.');
          $('revisionInstruction').value='';
          await Promise.all([loadFiles(false),loadVersions(),refreshPreview()]);
          $('agentState').textContent=`Revizija zaključena · ${p.status} · Visual QA ${p.last_audit?.visual_qa?.score??'—'}`;
          return;
        }
      }
      $('agentState').textContent='Revizija še teče; stanje ostaja shranjeno na strežniku.';
    }catch(err){$('agentState').textContent='NAPAKA: '+err.message;}finally{$('runRevision').disabled=false;}
  }
  async function showContext(){
    const dialog=$('contextDialog');dialog.showModal();$('repoMap').textContent='Nalaganje …';
    try{const data=await request(`/projects/${encodeURIComponent(projectId)}/editor/context`);$('repoMap').textContent=data.repo_map||'Repo map ni na voljo.';}catch(err){$('repoMap').textContent=err.message;}
  }
  async function boot(){
    if(!projectId){state('Manjka project ID.',true);return;}
    $('projectLabel').textContent=projectId;$('workspaceLink').href=`builder.html?project=${encodeURIComponent(projectId)}${API?'&api='+encodeURIComponent(API):''}`;
    $('fileSearch').addEventListener('input',renderFiles);$('refreshFiles').addEventListener('click',()=>loadFiles(false));$('saveFile').addEventListener('click',save);$('codeEditor').addEventListener('input',dirty);
    $('codeEditor').addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save();}if(e.key==='Tab'){e.preventDefault();const t=e.target,s=t.selectionStart,n=t.selectionEnd;t.value=t.value.slice(0,s)+'  '+t.value.slice(n);t.selectionStart=t.selectionEnd=s+2;dirty();}});
    $('previewButton').addEventListener('click',refreshPreview);$('runRevision').addEventListener('click',runRevision);$('refreshVersions').addEventListener('click',loadVersions);$('contextButton').addEventListener('click',showContext);
    try{
      const p=await request(`/projects/${encodeURIComponent(projectId)}`);$('projectLabel').textContent=p.name||projectId;
      await Promise.all([loadFiles(true),loadVersions(),refreshPreview()]);
    }catch(err){state(err.message,true);$('fileTree').innerHTML=`<div class="empty">${err.message}</div>`;}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();