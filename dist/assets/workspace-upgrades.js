(() => {
  const DRAFT_KEY = 'pv_draft_v1';
  const allowedImageTypes = new Set(['image/jpeg','image/png','image/webp']);
  const maxImageBytes = 8 * 1024 * 1024;
  const maxImages = 12;
  const esc = value => String(value || '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const slugify = value => String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'') || 'page';

  function readDraft() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') || {}; } catch { return {}; } }
  function writeDraft(patch) { const next={...readDraft(),...patch,updated_at:new Date().toISOString()}; localStorage.setItem(DRAFT_KEY,JSON.stringify(next)); return next; }

  function restoreLandingDraft() {
    const draft=readDraft();
    const requested=new URLSearchParams(location.search).get('paket');
    const pkg=packageLimits?.[requested] ? requested : (packageLimits?.[draft.package] ? draft.package : null);
    if (pkg) selectPackage(pkg);
    const mapping={name:'name',organization:'organization',audience:'audience',programme:'programme',goal:'goal'};
    Object.entries(mapping).forEach(([key,id])=>{
      const el=document.getElementById(id);
      if (el && !el.value.trim() && draft[key]) el.value=draft[key];
      el?.addEventListener('input',()=>writeDraft({[key]:el.value}));
    });
    document.querySelectorAll('.pkg').forEach(btn=>btn.addEventListener('click',()=>writeDraft({package:btn.dataset.package})));
    syncPreview();
  }

  function installDashboardLink() {
    const actions=document.querySelector('.top-actions');
    if (!actions || actions.querySelector('[data-dashboard-link]')) return;
    const a=document.createElement('a');
    a.dataset.dashboardLink='1';
    a.textContent='Moji projekti';
    const url=new URL('dashboard.html',location.href);
    if (API) url.searchParams.set('api',API);
    a.href=url.href;
    actions.insertBefore(a,actions.firstChild);
  }

  function configuredPages() {
    const raw=document.getElementById('pages')?.value || '';
    return raw.split('\n').map(x=>x.trim()).filter(Boolean).map((line,index)=>{
      const title=(line.split('|')[0] || `Page ${index+1}`).trim();
      return {title,slug:index===0?'index':slugify(title)};
    });
  }

  function placementOptions(selected, kind='image') {
    const base=[
      ['auto','Samodejno — agent določi'],
      ['hero','Domov — hero'],
      ['content','Domov — vsebina'],
      ['gallery','Domov — galerija'],
      ['logo','Logotip — glava in noga']
    ];
    const page=[];
    configuredPages().forEach(p=>{
      if (p.slug==='index') return;
      page.push([`page:${p.slug}:hero`,`${p.title} — hero`],[`page:${p.slug}:content`,`${p.title} — vsebina`],[`page:${p.slug}:gallery`,`${p.title} — galerija`]);
    });
    const options=kind==='logo' ? [['logo','Logotip — glava in noga']] : [...base,...page];
    return options.map(([v,l])=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(l)}</option>`).join('');
  }

  function validateIncomingFiles(files) {
    const accepted=[];
    for (const file of files) {
      if (!allowedImageTypes.has(file.type)) { status(`SLIKA NI SPREJETA\n${file.name}: uporabi JPG, PNG ali WebP.`); continue; }
      if (file.size>maxImageBytes) { status(`SLIKA JE PREVELIKA\n${file.name}: največ 8 MB na sliko.`); continue; }
      accepted.push(file);
    }
    return accepted;
  }

  function makeImageItem(file,{logo=false,index=0}={}) {
    return {
      file,
      kind:logo?'logo':'image',
      placement:logo?'logo':(index===0 && !selectedImages.some(x=>x.kind!=='logo')?'hero':'auto'),
      alt:logo?'Logo':file.name.replace(/\.[^.]+$/,'').replace(/[-_]+/g,' ').trim(),
      focalX:50,
      focalY:50,
      previewUrl:URL.createObjectURL(file)
    };
  }

  function mediaStyles() {
    if (document.getElementById('pvMediaStyles')) return;
    const style=document.createElement('style'); style.id='pvMediaStyles';
    style.textContent=`
      .media-studio{margin-top:.85rem}.media-actions{display:flex;gap:.5rem;flex-wrap:wrap}.media-drop{display:grid;place-items:center;min-height:9rem;padding:1.1rem;border:1.5px dashed #9eb6ac;border-radius:1rem;background:linear-gradient(135deg,#f7fbf8,#eef5f1);text-align:center;cursor:pointer;transition:.2s}.media-drop:hover,.media-drop.dragging{border-color:var(--good);background:#e8f4ee;box-shadow:0 0 0 4px rgba(27,118,95,.06)}.media-drop strong{display:block;font-size:.88rem}.media-drop span{display:block;margin-top:.2rem;color:var(--muted);font-size:.7rem}.media-drop b{display:grid;place-items:center;width:2.3rem;height:2.3rem;margin:0 auto .55rem;border-radius:.7rem;background:var(--ink);color:var(--lime);font-size:1.1rem}.logo-add{margin-top:.55rem;border:1px solid var(--line);border-radius:.65rem;background:#fff;padding:.55rem .7rem;font-size:.7rem;font-weight:850;cursor:pointer}.media-queue{display:grid;gap:.6rem;margin-top:.7rem}.media-row{display:grid;grid-template-columns:5.2rem minmax(0,1fr) minmax(12rem,.6fr) 2.2rem;gap:.6rem;align-items:center;padding:.62rem;border:1px solid var(--line);border-radius:.85rem;background:#fff}.media-thumb-wrap{position:relative}.media-thumb{width:5.2rem;height:4.4rem;border-radius:.65rem;object-fit:cover;background:#edf2ef}.media-kind{position:absolute;left:.3rem;bottom:.3rem;padding:.18rem .3rem;border-radius:999px;background:rgba(5,22,17,.82);color:#fff;font-size:.52rem;font-weight:900}.media-copy strong{display:block;font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.media-copy input,.media-row select{width:100%;margin-top:.28rem;border:1px solid #b9c8c1;border-radius:.55rem;padding:.48rem;background:#fff;font:inherit;font-size:.7rem}.media-advanced{grid-column:2/4;display:grid;grid-template-columns:auto 1fr auto 1fr;gap:.4rem;align-items:center;color:var(--muted);font-size:.6rem}.media-advanced input[type=range]{width:100%;accent-color:var(--good)}.media-remove{border:0;background:transparent;color:#6e7f79;font-size:1.25rem;cursor:pointer}.media-help{margin-top:.5rem;color:var(--muted);font-size:.67rem;line-height:1.45}
      @media(max-width:760px){.media-row{grid-template-columns:4.3rem 1fr 2rem}.media-thumb{width:4.3rem;height:4rem}.media-row>select{grid-column:2/4}.media-advanced{grid-column:1/-1;grid-template-columns:auto 1fr}.media-remove{grid-column:3;grid-row:1}}
    `;
    document.head.appendChild(style);
  }

  function enhanceMediaUi() {
    const input=document.getElementById('projectImages');
    if (!input || document.getElementById('mediaDropzone')) return;
    mediaStyles();
    input.style.display='none';
    const parent=input.parentElement; parent.classList.add('media-studio');
    const actions=document.createElement('div'); actions.className='media-actions';
    const drop=document.createElement('div'); drop.id='mediaDropzone'; drop.className='media-drop'; drop.tabIndex=0; drop.setAttribute('role','button');
    drop.innerHTML='<div><b>＋</b><strong>Spusti fotografije sem ali klikni za izbor</strong><span>Do 12 slik · JPG, PNG ali WebP · največ 8 MB · samodejni WebP/AVIF + srcset</span></div>';
    const logoBtn=document.createElement('button'); logoBtn.type='button'; logoBtn.className='logo-add'; logoBtn.textContent='＋ Dodaj logotip';
    const logoInput=document.createElement('input'); logoInput.type='file'; logoInput.accept='image/jpeg,image/png,image/webp'; logoInput.hidden=true;
    input.before(drop); drop.after(logoBtn,logoInput);
    const help=document.createElement('div'); help.className='media-help'; help.textContent='Vsaki sliki določi stran in vlogo. Focal point pove, kateri del fotografije mora ostati viden pri cropanju. Logotip se uporabi v navigaciji in footerju.';
    const queue=document.getElementById('imageQueue'); queue?.classList.add('media-queue'); queue?.after(help);

    const addFiles=(incoming,logo=false)=>{
      const accepted=validateIncomingFiles(Array.from(incoming||[]));
      const room=Math.max(0,maxImages-selectedImages.length);
      accepted.slice(0,logo?1:room).forEach((file,i)=>selectedImages.push(makeImageItem(file,{logo,index:i})));
      if (accepted.length>room && !logo) status(`OMEJITEV SLIK\nUporabiš lahko največ ${maxImages} slik na projekt.`);
      renderImageQueue();
    };
    drop.addEventListener('click',()=>input.click());
    drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}});
    ['dragenter','dragover'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.add('dragging');}));
    ['dragleave','drop'].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.remove('dragging');}));
    drop.addEventListener('drop',e=>addFiles(e.dataTransfer?.files,false));
    logoBtn.addEventListener('click',()=>logoInput.click());
    logoInput.addEventListener('change',e=>addFiles(e.target.files,true));
    input.addEventListener('change',()=>setTimeout(()=>{
      selectedImages.forEach((item,index)=>{
        item.kind=item.kind||'image'; item.focalX=Number.isFinite(item.focalX)?item.focalX:50; item.focalY=Number.isFinite(item.focalY)?item.focalY:50;
        if(!item.previewUrl&&item.file)item.previewUrl=URL.createObjectURL(item.file);
        if(!item.placement)item.placement=index===0?'hero':'auto';
      }); renderImageQueue();
    },0));

    window.renderImageQueue=renderImageQueue=function(){
      const host=document.getElementById('imageQueue'); if(!host)return; host.innerHTML='';
      selectedImages.forEach((item,index)=>{
        item.kind=item.kind||'image'; item.focalX=Number.isFinite(item.focalX)?item.focalX:50; item.focalY=Number.isFinite(item.focalY)?item.focalY:50;
        if(!item.previewUrl&&item.file)item.previewUrl=URL.createObjectURL(item.file);
        if(item.kind==='logo')item.placement='logo';
        const row=document.createElement('div'); row.className='media-row';
        row.innerHTML=`<div class="media-thumb-wrap"><img class="media-thumb" src="${esc(item.previewUrl||'')}" alt=""><span class="media-kind">${item.kind==='logo'?'LOGO':'IMAGE'}</span></div><div class="media-copy"><strong>${esc(item.file?.name||'Slika')}</strong><input data-alt="${index}" value="${esc(item.alt||'')}" aria-label="Opis slike" placeholder="Opis / alt text"></div><select data-placement="${index}" aria-label="Mesto slike">${placementOptions(item.placement||'auto',item.kind)}</select><button class="media-remove" type="button" data-remove="${index}" aria-label="Odstrani sliko">×</button>${item.kind==='logo'?'':`<div class="media-advanced"><span>Fokus X <b data-fx-label="${index}">${Math.round(item.focalX)}%</b></span><input type="range" min="0" max="100" value="${item.focalX}" data-fx="${index}"><span>Fokus Y <b data-fy-label="${index}">${Math.round(item.focalY)}%</b></span><input type="range" min="0" max="100" value="${item.focalY}" data-fy="${index}"></div>`}`;
        host.appendChild(row);
      });
      host.querySelectorAll('[data-alt]').forEach(el=>el.addEventListener('input',e=>{selectedImages[Number(e.target.dataset.alt)].alt=e.target.value;}));
      host.querySelectorAll('[data-placement]').forEach(el=>el.addEventListener('change',e=>{const item=selectedImages[Number(e.target.dataset.placement)]; item.placement=e.target.value; if(e.target.value==='logo')item.kind='logo'; renderImageQueue();}));
      host.querySelectorAll('[data-fx]').forEach(el=>el.addEventListener('input',e=>{const i=Number(e.target.dataset.fx);selectedImages[i].focalX=Number(e.target.value);const l=host.querySelector(`[data-fx-label="${i}"]`);if(l)l.textContent=`${e.target.value}%`;}));
      host.querySelectorAll('[data-fy]').forEach(el=>el.addEventListener('input',e=>{const i=Number(e.target.dataset.fy);selectedImages[i].focalY=Number(e.target.value);const l=host.querySelector(`[data-fy-label="${i}"]`);if(l)l.textContent=`${e.target.value}%`;}));
      host.querySelectorAll('[data-remove]').forEach(el=>el.addEventListener('click',e=>{const i=Number(e.currentTarget.dataset.remove);const removed=selectedImages.splice(i,1)[0];if(removed?.previewUrl)URL.revokeObjectURL(removed.previewUrl);renderImageQueue();}));
    };
    document.getElementById('pages')?.addEventListener('input',()=>renderImageQueue());

    uploadSelectedImages=async function(projectId){
      if(!selectedImages.length)return[]; const uploaded=[];
      for(let i=0;i<selectedImages.length;i++){
        const item=selectedImages[i]; status(`OPTIMIZIRAM IN NALAGAM SLIKE\n${i+1}/${selectedImages.length}: ${item.file.name}`);
        const form=new FormData(); form.append('file',item.file); form.append('alt_text',item.alt||item.file.name); form.append('placement',item.placement||'auto'); form.append('kind',item.kind||'image'); form.append('focal_x',String(item.focalX??50)); form.append('focal_y',String(item.focalY??50));
        uploaded.push(await requestForm(`/projects/${projectId}/images`,form));
      }
      return uploaded;
    };
    renderImageQueue();
  }

  function installPreviewTerminal() {
    const preview=document.querySelector('.preview'); const top=preview?.querySelector('.preview-top');
    if(!preview||!top||document.getElementById('previewTerminal'))return;
    const style=document.createElement('style'); style.textContent=`.preview-tools{display:flex;align-items:center;gap:.4rem}.terminal-toggle{border:1px solid var(--line);border-radius:.55rem;background:#fff;color:var(--ink);padding:.38rem .55rem;font-size:.64rem;font-weight:850;cursor:pointer}.preview-terminal{display:none;border-top:1px solid var(--line);background:#051611;color:#d8e8e2;padding:.7rem}.preview-terminal.open{display:block}.terminal-screen{min-height:8rem;max-height:15rem;overflow:auto;white-space:pre-wrap;font:500 .65rem/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-line{display:grid;grid-template-columns:auto 1fr;gap:.45rem;align-items:center;margin-top:.55rem;border-top:1px solid rgba(255,255,255,.08);padding-top:.55rem}.terminal-line span{color:var(--lime);font:700 .72rem ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-line input{min-width:0;border:0;outline:0;background:transparent;color:#fff;font:500 .72rem ui-monospace,SFMono-Regular,Consolas,monospace}.terminal-hint{margin-top:.45rem;color:#78988e;font-size:.58rem}`; document.head.appendChild(style);
    const label=top.querySelector('span'); const tools=document.createElement('div'); tools.className='preview-tools'; if(label)tools.appendChild(label); const toggle=document.createElement('button');toggle.type='button';toggle.className='terminal-toggle';toggle.textContent='Terminal';tools.appendChild(toggle);top.appendChild(tools);
    const terminal=document.createElement('div');terminal.id='previewTerminal';terminal.className='preview-terminal';terminal.innerHTML='<div class="terminal-screen" id="terminalScreen">PROJECT VISIBILITY TERMINAL\nType help for commands.\nDraft commands change preview; free text revises a published project.</div><div class="terminal-line"><span>pv&gt;</span><input id="terminalInput" autocomplete="off" spellcheck="false" placeholder="npr. title Nova naslovna vrstica"></div><div class="terminal-hint">help · title · subtitle · cta · primary · accent · background · text · status · open · clear · ali naravna zahteva za revizijo</div>';preview.appendChild(terminal);
    const screen=terminal.querySelector('#terminalScreen'),input=terminal.querySelector('#terminalInput'); const log=line=>{screen.textContent+=`\n${line}`;screen.scrollTop=screen.scrollHeight;};
    const setField=(id,value)=>{const el=document.getElementById(id);if(!el)return false;el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));syncPreview();return true;}; const color=v=>/^#[0-9a-f]{6}$/i.test(v);
    async function projectStatus(){if(!activeProjectId||!token){log('No active authenticated project.');return null;}const p=await request(`/projects/${activeProjectId}`);log(`status=${p.status} repo=${p.repo_name||'-'} fixes=${p.auto_fix_attempts||0} visual=${p.last_audit?.visual_qa?.score??'-'}`);return p;}
    async function revise(instruction){if(!token){log('Login required.');return;}if(!activeProjectId){log('No active project.');return;}const p=await request(`/projects/${activeProjectId}`);if(!p.repo_name){log('Initial build must finish first.');return;}const created=await request(`/projects/${activeProjectId}/revise`,{method:'POST',body:JSON.stringify({instruction})});log(`revision ${created.id} queued`);for(let i=0;i<100;i++){await sleep(2500);const s=await request(`/projects/${activeProjectId}`);if(i%3===0)log(`... ${s.status}`);if(['ready','needs_review','failed'].includes(s.status)){log(s.status==='failed'?'Revision failed.':'Revision published and checked.');if(s.repo_name){const frame=document.getElementById('liveMiniFrame');if(frame)frame.src=`${finalSiteUrl(s.repo_name)}?terminal=${Date.now()}`;}return;}}log('Revision continues in background.');}
    async function run(raw){const cmd=raw.trim();if(!cmd)return;log(`pv> ${cmd}`);const [head,...rest]=cmd.split(/\s+/),arg=rest.join(' ').trim();switch(head.toLowerCase()){case'help':log('title <text> | subtitle <text> | cta <text> | primary/accent/background/text #RRGGBB | status | open | clear');return;case'title':log(arg&&setField('heroTitle',arg)?'Hero title updated.':'Usage: title <text>');return;case'subtitle':log(arg&&setField('heroSubtitle',arg)?'Hero subtitle updated.':'Usage: subtitle <text>');return;case'cta':log(arg&&setField('cta',arg)?'CTA updated.':'Usage: cta <text>');return;case'primary':log(color(arg)&&setField('primary',arg)?'Primary updated.':'Use #RRGGBB.');return;case'accent':log(color(arg)&&setField('secondary',arg)?'Accent updated.':'Use #RRGGBB.');return;case'background':log(color(arg)&&setField('background',arg)?'Background updated.':'Use #RRGGBB.');return;case'text':log(color(arg)&&setField('textColor',arg)?'Text updated.':'Use #RRGGBB.');return;case'status':await projectStatus();return;case'open':{const p=await projectStatus();if(p?.repo_name)window.open(finalSiteUrl(p.repo_name),'_blank','noopener');return;}case'clear':screen.textContent='PROJECT VISIBILITY TERMINAL';return;default:await revise(cmd);}}
    toggle.addEventListener('click',()=>{terminal.classList.toggle('open');toggle.textContent=terminal.classList.contains('open')?'Zapri terminal':'Terminal';if(terminal.classList.contains('open'))setTimeout(()=>input.focus(),0);}); input.addEventListener('keydown',async e=>{if(e.key!=='Enter')return;e.preventDefault();const v=input.value;input.value='';try{await run(v);}catch(err){log(`ERROR: ${err.message}`);}});
  }

  async function restoreProjectHandoff() {
    const id=new URLSearchParams(location.search).get('project'); if(!id||!token||!API)return;
    try{
      const p=await request(`/projects/${id}`); activeProjectId=id; updatePipeline(p.status); if(p.repo_name){setResultLinks(p.repo_name);document.getElementById('resultActions')?.classList.add('visible');}
      const qa=p.last_audit?.visual_qa; status(`PROJEKT ODPRT V WORKSPACE\n${p.name}\nStatus: ${p.status}\nVisual QA: ${qa?.score??'—'}${qa?.render_count?` / ${qa.render_count} renderjev`:''}\n${p.repo_name?`Repo: ${p.repo_name}`:''}`);
    }catch(err){status(`PROJEKTA NI BILO MOGOČE ODPRETI\n${err.message}`);}
  }

  if(typeof stageIndex==='object')stageIndex.visual_qa=3;
  if(typeof statusLabels==='object')statusLabels.visual_qa='Vizualni QA: desktop, tablet, mobile';
  restoreLandingDraft(); installDashboardLink(); enhanceMediaUi(); installPreviewTerminal(); setTimeout(restoreProjectHandoff,250);
})();