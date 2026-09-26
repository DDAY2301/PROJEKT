(() => {
  const qs=new URLSearchParams(location.search);
  const projectId=qs.get('project')||'';
  const configured=String(window.PV_RUNTIME?.apiBase||'').trim().replace(/\/$/,'');
  const API=String(qs.get('api')||configured||localStorage.getItem('pv_api_url')||'').trim().replace(/\/$/,'');
  const token=()=>localStorage.getItem('pv_token')||'';
  const $=id=>document.getElementById(id);
  let images=[];
  let activeId='';
  let activePreviewUrl='';

  function state(text,bad=false){
    const el=$('studioStatus');
    if(!el)return;
    el.textContent=text;
    el.style.color=bad?'#b33':'#6f837b';
  }

  async function request(path,options={}){
    if(!API)throw new Error('API ni nastavljen.');
    if(!token())throw new Error('Prijava ni aktivna.');
    const headers={...(options.headers||{}),Authorization:`Bearer ${token()}`};
    if(!(options.body instanceof FormData))headers['Content-Type']=headers['Content-Type']||'application/json';
    const res=await fetch(`${API}${path}`,{...options,headers});
    const text=await res.text();let data;try{data=JSON.parse(text)}catch{data={detail:text}}
    if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:`HTTP ${res.status}`);
    return data;
  }

  async function previewBlob(imageId){
    const res=await fetch(`${API}/projects/${encodeURIComponent(projectId)}/images/${encodeURIComponent(imageId)}/preview`,{
      headers:{Authorization:`Bearer ${token()}`}
    });
    if(!res.ok)throw new Error(`Preview HTTP ${res.status}`);
    return URL.createObjectURL(await res.blob());
  }

  function esc(v){return String(v||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}

  async function renderLibrary(){
    const host=$('imageList');
    if(!images.length){host.innerHTML='<div class="empty-canvas">Projekt še nima slik.</div>';return;}
    host.innerHTML=images.map(img=>`<button class="thumb-card ${img.id===activeId?'active':''}" data-image="${esc(img.id)}" type="button"><img data-thumb="${esc(img.id)}" alt=""><span><strong>${esc(img.name||'Slika')}</strong><span>${esc(img.placement||'auto')} · ${img.width||0}×${img.height||0}</span></span></button>`).join('');
    host.querySelectorAll('[data-image]').forEach(btn=>btn.addEventListener('click',()=>selectImage(btn.dataset.image)));
    for(const img of images){
      try{
        const url=await previewBlob(img.id);
        const el=host.querySelector(`[data-thumb="${CSS.escape(img.id)}"]`);
        if(el){el.src=url;el.addEventListener('load',()=>setTimeout(()=>URL.revokeObjectURL(url),5000),{once:true});}
      }catch{}
    }
  }

  function renderBackgroundOptions(){
    const select=$('backgroundImage');
    if(!select)return;
    select.innerHTML='<option value="">— izberi —</option>'+images.filter(x=>x.id!==activeId).map(x=>`<option value="${esc(x.id)}">${esc(x.name||x.id)}</option>`).join('');
  }

  async function selectImage(id){
    activeId=id;
    const img=images.find(x=>x.id===id);
    if(!img)return;
    if(activePreviewUrl)URL.revokeObjectURL(activePreviewUrl);
    state('Nalagam sliko …');
    try{
      activePreviewUrl=await previewBlob(id);
      $('canvasStage').innerHTML=`<img src="${activePreviewUrl}" alt="${esc(img.alt_text||img.name||'Project image')}">`;
      $('activeName').textContent=img.name||'Slika';
      $('activeMeta').textContent=`${img.width||0}×${img.height||0} · ${img.placement||'auto'} · focal ${Math.round(img.focal_x||50)}%/${Math.round(img.focal_y||50)}%`;
      renderBackgroundOptions();
      await loadHistory();
      await renderLibrary();
      state('Slika pripravljena za urejanje.');
    }catch(err){state(err.message,true);}
  }

  async function loadImages(){
    if(!projectId)throw new Error('Manjka project ID.');
    state('Nalagam project media …');
    images=await request(`/projects/${encodeURIComponent(projectId)}/images`);
    $('imageCount').textContent=String(images.length);
    renderBackgroundOptions();
    await renderLibrary();
    if(activeId && images.some(x=>x.id===activeId))await selectImage(activeId);
    else if(images[0])await selectImage(images[0].id);
    else state('Projekt še nima slik.');
  }

  function formValue(id){return String($(id)?.value??'');}
  function boolValue(id){return Boolean($(id)?.checked);}

  async function applyEdit(){
    if(!activeId){state('Najprej izberi sliko.',true);return;}
    const button=$('applyEdit');button.disabled=true;button.textContent='Obdelujem …';
    const form=new FormData();
    form.append('image_id',activeId);
    ['rotate','brightness','contrast','saturation','blur','cropX','cropY','cropW','cropH'].forEach(id=>{
      const map={cropX:'crop_x',cropY:'crop_y',cropW:'crop_w',cropH:'crop_h'};
      form.append(map[id]||id,formValue(id));
    });
    form.append('flip_horizontal',String(boolValue('flipH')));
    form.append('flip_vertical',String(boolValue('flipV')));
    form.append('remove_background',String(boolValue('removeBackground')));
    form.append('background_mode',formValue('backgroundMode'));
    form.append('background_color',formValue('backgroundColor'));
    form.append('background_id',formValue('backgroundImage'));
    form.append('shadow',String(boolValue('shadow')));
    const bg=$('backgroundFile')?.files?.[0];
    if(bg)form.append('background_file',bg);
    state('Ustvarjam snapshot, urejam sliko in ponovno generiram responsive WebP/AVIF …');
    try{
      const data=await request(`/projects/${encodeURIComponent(projectId)}/image-studio/edit`,{method:'POST',body:form});
      $('engineBadge').textContent=String(data.background_engine||'LOCAL').toUpperCase();
      await loadImages();
      resetControls(false);
      state(`Shranjeno · ${data.width}×${data.height} · background engine: ${data.background_engine||'none'} · snapshot: ${String(data.snapshot_id||'').slice(0,8)}`);
    }catch(err){state(err.message,true);}finally{button.disabled=false;button.textContent='Uporabi spremembe';}
  }

  async function generateBackground(){
    const prompt=formValue('generationPrompt').trim();
    if(prompt.length<3){state('Vpiši opis background scene.',true);return;}
    const [width,height]=formValue('generationSize').split('x').map(Number);
    const form=new FormData();
    form.append('prompt',prompt);
    form.append('width',String(width||1536));
    form.append('height',String(height||1024));
    form.append('placement','gallery');
    form.append('provider',formValue('generationProvider'));
    const button=$('generateBackground');button.disabled=true;button.textContent='Generiram …';
    state('Generiram nov background. Če je ComfyUI aktiven, lahko to traja nekaj časa …');
    try{
      const data=await request(`/projects/${encodeURIComponent(projectId)}/image-studio/generate-background`,{method:'POST',body:form});
      $('engineBadge').textContent=String(data.provider||'LOCAL').toUpperCase();
      await loadImages();
      await selectImage(data.id);
      $('backgroundMode').value='image';
      state(`Background ustvarjen · ${data.width}×${data.height} · engine: ${data.provider}`);
    }catch(err){state(err.message,true);}finally{button.disabled=false;button.textContent='Generiraj background';}
  }

  async function loadHistory(){
    const host=$('historyList');
    if(!activeId){host.innerHTML='<span class="empty-canvas">Izberi sliko.</span>';return;}
    try{
      const rows=await request(`/projects/${encodeURIComponent(projectId)}/image-studio/history/${encodeURIComponent(activeId)}`);
      host.innerHTML=rows.length?rows.map(row=>`<button type="button" data-restore="${esc(row.id)}"><span>${row.width}×${row.height}</span><span>${row.created_at?new Date(row.created_at).toLocaleString('sl-SI'):''}</span></button>`).join(''):'<span class="empty-canvas">Še ni snapshotov.</span>';
      host.querySelectorAll('[data-restore]').forEach(btn=>btn.addEventListener('click',()=>restore(btn.dataset.restore)));
    }catch(err){host.innerHTML=`<span class="empty-canvas">${esc(err.message)}</span>`;}
  }

  async function restore(snapshotId){
    if(!confirm('Obnovim sliko na izbrani snapshot? Trenutno stanje bo pred obnovo prav tako shranjeno.'))return;
    state('Obnavljam image snapshot …');
    try{
      await request(`/projects/${encodeURIComponent(projectId)}/image-studio/restore/${encodeURIComponent(snapshotId)}`,{method:'POST'});
      await loadImages();
      state('Snapshot obnovljen.');
    }catch(err){state(err.message,true);}
  }

  function resetControls(updateStatus=true){
    $('rotate').value='0';$('flipH').checked=false;$('flipV').checked=false;
    $('cropX').value='0';$('cropY').value='0';$('cropW').value='100';$('cropH').value='100';
    $('brightness').value='1';$('contrast').value='1';$('saturation').value='1';$('blur').value='0';
    $('removeBackground').checked=false;$('backgroundMode').value='preserve';$('backgroundColor').value='#f5f7f6';$('backgroundImage').value='';$('shadow').checked=true;if($('backgroundFile'))$('backgroundFile').value='';
    updateRangeLabels();toggleBackgroundFields();if(updateStatus)state('Controls resetirani.');
  }

  function updateRangeLabels(){
    $('brightnessValue').textContent=Number(formValue('brightness')).toFixed(2);
    $('contrastValue').textContent=Number(formValue('contrast')).toFixed(2);
    $('saturationValue').textContent=Number(formValue('saturation')).toFixed(2);
    $('blurValue').textContent=formValue('blur');
  }

  function toggleBackgroundFields(){
    const mode=formValue('backgroundMode');
    $('backgroundImageField').classList.toggle('hidden',mode!=='image');
    $('backgroundUploadField').classList.toggle('hidden',mode!=='upload');
  }

  async function boot(){
    if(!projectId){state('Odpri Image Studio iz Builderja ali Dashboarda; manjka project ID.',true);return;}
    const builder=new URL('builder.html',location.href);builder.searchParams.set('project',projectId);if(API)builder.searchParams.set('api',API);$('builderLink').href=builder.href;
    ['brightness','contrast','saturation','blur'].forEach(id=>$(id).addEventListener('input',updateRangeLabels));
    $('backgroundMode').addEventListener('change',toggleBackgroundFields);
    $('applyEdit').addEventListener('click',applyEdit);
    $('generateBackground').addEventListener('click',generateBackground);
    $('resetControls').addEventListener('click',()=>resetControls());
    $('refreshImages').addEventListener('click',loadImages);
    resetControls(false);
    try{
      const project=await request(`/projects/${encodeURIComponent(projectId)}`);
      $('projectLabel').textContent=project.name||projectId;
      await loadImages();
    }catch(err){state(err.message,true);$('imageList').innerHTML=`<div class="empty-canvas">${esc(err.message)}</div>`;}
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();