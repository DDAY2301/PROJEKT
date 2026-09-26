(() => {
  const STORAGE_KEY='pv_language';
  const params=new URLSearchParams(location.search);
  const initial=(params.get('lang')||localStorage.getItem(STORAGE_KEY)||document.documentElement.lang||'sl').toLowerCase()==='en'?'en':'sl';
  let language=initial;

  const dict=new Map(Object.entries({
    'Preskoči na vsebino':'Skip to content',
    'Zmogljivosti':'Capabilities',
    'Proces':'Process',
    'Paketi':'Packages',
    'Odpri builder →':'Open builder →',
    'Od ideje do':'From idea to',
    'objavljive strani.':'a publish-ready website.',
    'Project Visibility združi brief, tvoje fotografije, vizualno identiteto, responsive izdelavo, Visual QA, self-fix, plačilo in GitHub objavo v en sam workflow.':'Project Visibility combines your brief, photos, visual identity, responsive build, Visual QA, self-fix, payment and GitHub publishing in one workflow.',
    'Začni projekt →':'Start project →',
    'Moji projekti':'My projects',
    'Drag & drop fotografije':'Drag & drop photos',
    'Logo + focal point':'Logo + focal point',
    'Desktop / tablet / mobile QA':'Desktop / tablet / mobile QA',
    'Lastna koda':'Your own source code',
    'Brief + paket':'Brief + package',
    'cilj, publika, struktura':'goal, audience, structure',
    'fotografije, logo, crop, strani':'photos, logo, crop, pages',
    'Build + Visual QA':'Build + Visual QA',
    'responsive render in self-fix':'responsive render and self-fix',
    'Domov → Hero':'Home → Hero',
    'GitHub source + live stran':'GitHub source + live site',
    'Dashboard + revizije':'Dashboard + revisions',
    'Ne samo generator. Celoten website workflow.':'Not just a generator. A complete website workflow.',
    'Ključni cilj ni samo ustvariti HTML, ampak uporabniku predati stran, ki jo lahko dejansko uporabi: z lastnimi slikami, preverjenim layoutom, objavo, izvorno kodo in možnostjo nadaljnjih sprememb.':'The goal is not only to generate HTML, but to deliver a website the customer can actually use: with their own images, a verified layout, publishing, source code and future revisions.',
    'Fotografije in logotip naložiš neposredno v builder.':'Upload photos and your logo directly in the builder.',
    'hero / vsebina / galerija':'hero / content / gallery',
    'točno določena stran':'specific page placement',
    'focal point in responsive crop':'focal point and responsive crop',
    'Stran se pred objavo dejansko renderira v več velikostih.':'The website is rendered at multiple viewport sizes before publishing.',
    'desktop, tablet, mobile':'desktop, tablet, mobile',
    'overflow, kontrast, CTA, slike':'overflow, contrast, CTA, images',
    'lokalni vision art director':'local vision art director',
    'self-fix in ponovni render':'self-fix and re-render',
    'Customer dashboard':'Customer dashboard',
    'Po izdelavi projekt ne izgine v GitHubu.':'Your project remains manageable after delivery.',
    'live URL in status':'live URL and status',
    'Visual QA rezultat':'Visual QA result',
    'revision history':'revision history',
    'download source':'download source',
    'Od vnosa do live strani brez ročnega preskakovanja med orodji.':'From input to a live website without manually jumping between tools.',
    'Plačilo in objava sta del istega toka. Ko je build uspešen, uporabnik dobi live povezavo, GitHub source in dashboard za nadaljnje spremembe.':'Payment and publishing are part of the same flow. After a successful build, the user gets a live link, GitHub source and a dashboard for future changes.',
    'cilj, publika, paket, strani':'goal, audience, package, pages',
    'logo, fotografije, crop, lokacije':'logo, photos, crop, placement',
    'struktura, copy, responsive frontend':'structure, copy, responsive frontend',
    'render, screenshots, self-fix':'render, screenshots, self-fix',
    'GitHub, Pages, dashboard, revizije':'GitHub, Pages, dashboard, revisions',
    'Končni rezultat':'Final result',
    'Stran mora izgledati kot naročen produkt, ne kot AI osnutek.':'The website should look like a finished product, not an AI draft.',
    'Generator uporablja premium design floor in media engine. Fotografije niso dodatek na koncu, ampak del layouta, responsive pravil in QA procesa.':'The generator uses a premium design floor and media engine. Photos are part of the layout, responsive rules and QA process from the start.',
    'Premium editorial hierarchy, jasen CTA in vsebina, ki je pripravljena za javno uporabo.':'Premium editorial hierarchy, a clear CTA and content ready for public use.',
    'Vsaka slika dobi optimalne variante za različne širine.':'Every image receives optimized variants for different widths.',
    'Screenshot pregled pred objavo.':'Screenshot review before publishing.',
    'Spremeni že objavljeno stran z navadno zahtevo.':'Revise a published website with a simple request.',
    'Začni tukaj':'Start here',
    'Izberi paket in shrani prvi brief.':'Choose a package and save your first brief.',
    'Vnos se shrani lokalno in nadaljuje v builderju brez ponovnega prepisovanja.':'Your input is saved locally and continues in the builder without retyping.',
    'Za manjši projekt ali jasno poslovno predstavitev.':'For a smaller project or a focused business presentation.',
    'brez DDV':'excl. VAT',
    'do 3 strani':'up to 3 pages',
    'lastne fotografije in logo':'your own photos and logo',
    'responsive media engine':'responsive media engine',
    'GitHub source + live URL':'GitHub source + live URL',
    'Izberi Start':'Choose Start',
    'Za več vsebine, partnerjev, rezultatov in galerij.':'For more content, partners, results and galleries.',
    'do 6 strani':'up to 6 pages',
    'media placement po straneh':'media placement by page',
    'desktop/tablet/mobile QA':'desktop/tablet/mobile QA',
    'revision workflow':'revision workflow',
    'Izberi Standard':'Choose Standard',
    'Za večji projekt ali produkt z obsežnejšo arhitekturo.':'For a larger project or product with a more complex architecture.',
    'do 12 strani':'up to 12 pages',
    'več fotografij in sekcij':'more photos and sections',
    'naprednejša struktura':'advanced structure',
    'Visual QA + revizije':'Visual QA + revisions',
    'GitHub source + daljša podpora':'GitHub source + extended support',
    'Izberi Premium':'Choose Premium',
    'Brief, fotografije, build, QA in objava v enem toku.':'Brief, photos, build, QA and publishing in one flow.',
    'Začni na landing strani ali neposredno odpri builder. Osnutek ostane shranjen v tvojem brskalniku.':'Start on the landing page or open the builder directly. Your draft stays saved in your browser.',
    'Odpri Website Builder →':'Open Website Builder →',

    'Landing':'Landing',
    'Website workspace':'Website workspace',
    'Zgradi stran, ki je':'Build a website that is',
    'pripravljena za uporabo.':'ready to use.',
    'Brief, vizualna smer, tvoje fotografije, responsive media, private preview pred plačilom, Visual QA in objava so v enem toku. Fotografije lahko spustiš neposredno v media studio in določiš točno stran, vlogo ter focal point.':'Brief, visual direction, your photos, responsive media, private preview before payment, Visual QA and publishing are all in one flow. Drop photos directly into Media Studio and choose the exact page, role and focal point.',
    'Private preview pred plačilom':'Private preview before payment',
    'E-mail handoff':'E-mail handoff',
    'Stanje sistema':'System status',
    'Pred začetkom preveri povezavo, izdelavo in objavo.':'Check the connection, build engine and publishing before you start.',
    'Storitev':'Service',
    'Preverjam':'Checking',
    'Izdelava':'Build',
    'Objava':'Publishing',
    'Nastavitve povezave':'Connection settings',
    'Poveži':'Connect',
    'Naslov se shrani samo v tem brskalniku.':'The address is saved only in this browser.',
    'Potek projekta':'Project flow',
    'Račun':'Account',
    'Prijava uporabnika':'User login',
    'Projekt':'Project',
    'Cilj, publika, paket':'Goal, audience, package',
    'Drag & drop, logo, fotografije':'Drag & drop, logo, photos',
    'Struktura':'Structure',
    'Strani in vsebina':'Pages and content',
    'Build, preview, QA, objava':'Build, preview, QA, publish',
    'Nasvet:':'Tip:',
    'najprej vpiši želene strani, nato pri vsaki sliki izberi hero, vsebino ali galerijo na konkretni strani.':'first enter the desired pages, then assign each image to hero, content or gallery on a specific page.',
    'Prijavi se ali ustvari račun. Projekti, revizije in dashboard ostanejo vezani na ta račun.':'Sign in or create an account. Projects, revisions and dashboard remain linked to this account.',
    'E-pošta':'E-mail',
    'Geslo':'Password',
    'Najmanj 8 znakov.':'At least 8 characters.',
    'Registracija':'Register',
    'Prijava':'Sign in',
    'Odjava':'Sign out',
    'Nisi prijavljen.':'Not signed in.',
    'Osnovni brief določi namen, obseg in prodajno smer. Podatki z landing strani se prenesejo samodejno.':'The basic brief defines purpose, scope and direction. Data from the landing page is transferred automatically.',
    'Paket Start omogoča največ 3 strani.':'Start package allows up to 3 pages.',
    'Ime projekta':'Project name',
    'Organizacija / podjetje':'Organization / company',
    'Program ali dejavnost':'Programme or activity',
    'Ciljna publika':'Target audience',
    'Glavni cilj strani':'Main website goal',
    'Ton komunikacije':'Communication tone',
    'Spusti fotografije neposredno v workspace. Vsaki določi stran, hero/content/gallery vlogo in focal point; sistem nato izdela WebP/AVIF različice ter jih vključi v končno kodo.':'Drop photos directly into the workspace. Assign each image to a page and hero/content/gallery role; the system creates WebP/AVIF variants and integrates them into the final code.',
    'Primarna':'Primary',
    'Poudarek':'Accent',
    'Ozadje':'Background',
    'Besedilo':'Text',
    'Slog':'Style',
    'Vizualna smer':'Visual direction',
    'Smer fotografij / slik':'Photo / image direction',
    'Fotografije in logotip':'Photos and logo',
    'Drag & drop ali klik. Določi točno mesto vsake slike pred začetkom izdelave.':'Drag & drop or click. Choose the exact placement of each image before building.',
    'JPG, PNG ali WebP · do 12 slik · največ 8 MB na sliko. Slike se pokažejo tudi v live predogledu smeri.':'JPG, PNG or WebP · up to 12 images · max 8 MB per image. Images also appear in the live direction preview.',
    'Vsaka vrstica pomeni eno stran. Za znak | dodaj njen namen; ta seznam se uporablja tudi pri postavitvi slik.':'Each row represents one page. After | add its purpose; this list is also used for image placement.',
    'Želene strani':'Desired pages',
    'Glavni naslov':'Main heading',
    'CTA gumb':'CTA button',
    'Podnaslov':'Subtitle',
    'Kontaktni e-mail':'Contact e-mail',
    'Dodatne zahteve':'Additional requirements',
    'Najprej se izdela celotna stran in Visual QA. Nato dobiš zasebni predogled. Plačilo sprosti točno pregledano verzijo v javno objavo.':'The complete website and Visual QA are built first. Then you receive a private preview. Payment releases the exact reviewed version for public publishing.',
    'Začni izdelavo →':'Start build →',
    'Predogled smeri':'Direction preview',
    'v živo':'live',
    'O projektu':'About',
    'Novice':'News',
    'Kontakt':'Contact',
    'Spletna stran, ki ima jasen namen.':'A website with a clear purpose.',
    'Vpiši vsebino in dodaj slike; predogled se sproti prilagaja.':'Enter content and add images; the preview updates as you work.',
    'Kontaktirajte nas':'Contact us',
    'Potek izdelave':'Build progress',
    'Prejem briefa':'Brief received',
    'čaka':'waiting',
    'Izdelava strani':'Website build',
    'Popravki':'Fixes',
    'Dnevnik procesa':'Process log',
    'Pripravljen.':'Ready.',
    'Odpri GitHub repo ↗':'Open GitHub repo ↗',
    'Nov projekt':'New project',

    'Nov projekt →':'New project →',
    'Vse tvoje strani. En workspace.':'All your websites. One workspace.',
    'Status izdelave, private preview pred plačilom, plačilo, live URL, Visual QA, revizije, e-mail handoff, domena in izvorna koda so zbrani na enem mestu.':'Build status, private preview before payment, payment, live URL, Visual QA, revisions, e-mail handoff, domain and source code are collected in one place.',
    'Prijavi se z istim računom kot v builderju.':'Sign in with the same account you use in the builder.',
    'Preverjam sejo …':'Checking session …',
    'Projekti':'Projects',
    'Objavljeno':'Published',
    'Revizije':'Revisions',
    'Preglej zasebno verzijo, prenesi source, pošlji deployment napotke ali odpri live stran.':'Review the private version, download source, send deployment instructions or open the live site.',
    'Osveži':'Refresh',
    'Prijavi se za prikaz projektov.':'Sign in to view projects.',

    'Nalaganje projekta …':'Loading project …',
    'Osveži preview':'Refresh preview',
    'Izberi datoteko':'Select a file',
    'shranjeno':'saved',
    'Shrani · Ctrl+S':'Save · Ctrl+S',
    'Izberi datoteko na levi …':'Select a file on the left …',
    'Private preview':'Private preview',
    'AI sprememba':'AI revision',
    'lokalni agent':'local agent',
    'Pošlji agentu →':'Send to agent →',
    'Agent čaka.':'Agent waiting.',
    'Verzije':'Versions',
    'Repository map':'Repository map',
    'Kratek zemljevid datotek in pomembnih simbolov, ki ga agent uporablja kot kontekst pred spremembo kode.':'A compact map of files and important symbols used by the agent as context before changing code.',
    'Poišči datoteko …':'Search file …',
    'Repo map / agent context':'Repo map / agent context',
    'Nalaganje …':'Loading …',

    'Izberi sliko za urejanje ali background.':'Select an image to edit or use as a background.',
    'Predogled':'Preview',
    'Izberi sliko na levi.':'Select an image on the left.',
    'Izberi sliko za urejanje.':'Select an image to edit.',
    'Image Studio pripravljen.':'Image Studio ready.',
    'Image controls':'Image controls',
    'Spremembe so non-destructive; pred shranjevanjem se ustvari snapshot.':'Edits are non-destructive; a snapshot is created before saving.',
    'Transformacija':'Transform',
    'Rotacija':'Rotation',
    'horizontalno':'horizontal',
    'vertikalno':'vertical',
    'Crop širina %':'Crop width %',
    'Crop višina %':'Crop height %',
    'Videz':'Appearance',
    'Background integration':'Background integration',
    'odstrani originalno ozadje':'remove original background',
    'Novo ozadje':'New background',
    'Ohrani original':'Keep original',
    'Barva':'Color',
    'Blur originala':'Blur original',
    'Druga projektna slika':'Another project image',
    'Naloži background':'Upload background',
    'Projektna background slika':'Project background image',
    '— izberi —':'— select —',
    'Uporabi spremembe':'Apply changes',
    'Reset controls':'Reset controls',
    'Generate background':'Generate background',
    'Opis scene':'Scene description',
    'Format':'Format',
    'Engine':'Engine',
    'Brand procedural':'Brand procedural',
    'Generiraj background':'Generate background',
    'Če je ComfyUI konfiguriran, lahko Auto uporabi lokalno AI generacijo. Brez ComfyUI se ustvari brand-aware lokalni background, zato funkcija vedno ostane uporabna.':'If ComfyUI is configured, Auto can use local AI generation. Without ComfyUI, a brand-aware local background is generated, so the feature remains available.',
    'Zgodovina slike':'Image history',
    'Še ni snapshotov.':'No snapshots yet.'
  }));

  const placeholders=new Map(Object.entries({
    'npr. Erasmus+ KA2, storitev, produkt':'e.g. Erasmus+ KA2, service, product',
    'Kaj mora obiskovalec razumeti, narediti ali kupiti?':'What should the visitor understand, do or buy?',
    'Domov | ključna predstavitev\nO projektu | cilji in aktivnosti\nGalerija | fotografije\nKontakt | kontaktni podatki':'Home | key introduction\nAbout | goals and activities\nGallery | photos\nContact | contact details',
    'Npr. premium editorial hero, večji poudarek na rezultatih, FAQ, zemljevid, partnerji ...':'E.g. premium editorial hero, stronger focus on results, FAQ, map, partners ...',
    'Npr. Na domači strani naredi hero bolj minimalističen, ohrani fotografije in ne spreminjaj drugih strani.':'E.g. Make the homepage hero more minimal, keep the photos and do not change other pages.',
    'Npr. elegant forest-green editorial background, soft natural light, subtle depth, clean center composition':'E.g. elegant forest-green editorial background, soft natural light, subtle depth, clean center composition'
  }));

  const originals=new WeakMap();
  const attrOriginals=new WeakMap();
  const skipParent=(el)=>el && ['SCRIPT','STYLE','CODE','PRE','TEXTAREA'].includes(el.tagName);

  function translateTextNode(node){
    if(!node || node.nodeType!==Node.TEXT_NODE || skipParent(node.parentElement))return;
    const raw=node.nodeValue;
    if(!raw || !raw.trim())return;
    if(!originals.has(node)) originals.set(node,raw);
    const source=originals.get(node);
    if(language==='sl'){ if(node.nodeValue!==source)node.nodeValue=source; return; }
    const trimmed=source.trim();
    const translated=dict.get(trimmed);
    if(!translated)return;
    const lead=source.match(/^\s*/)?.[0]||'';
    const tail=source.match(/\s*$/)?.[0]||'';
    node.nodeValue=lead+translated+tail;
  }

  function translateElement(el){
    if(!(el instanceof Element))return;
    if(!attrOriginals.has(el)) attrOriginals.set(el,{});
    const store=attrOriginals.get(el);
    for(const attr of ['placeholder','title','aria-label']){
      if(!el.hasAttribute(attr))continue;
      if(!(attr in store))store[attr]=el.getAttribute(attr);
      const source=store[attr];
      if(language==='sl'){el.setAttribute(attr,source);continue;}
      el.setAttribute(attr,placeholders.get(source)||dict.get(source)||source);
    }
    for(const node of el.childNodes)if(node.nodeType===Node.TEXT_NODE)translateTextNode(node);
  }

  function walk(root=document.body){
    if(!root)return;
    if(root.nodeType===Node.TEXT_NODE){translateTextNode(root);return;}
    if(root instanceof Element)translateElement(root);
    root.querySelectorAll?.('*').forEach(translateElement);
  }

  function updateMeta(){
    document.documentElement.lang=language;
    const landing=location.pathname.endsWith('/')||location.pathname.endsWith('/index.html');
    if(landing){
      document.title=language==='en'?'Project Visibility | AI Website Studio':'Project Visibility | Website Studio';
      const desc=document.querySelector('meta[name="description"]');
      if(desc)desc.content=language==='en'
        ?'Project Visibility is an AI website studio for briefs, images, build, Visual QA and publishing in one workflow.'
        :'Project Visibility je website studio: paket, brief, slike, izdelava, Visual QA in objava v enem toku.';
    }
  }

  function ensureSwitcher(){
    if(!document.getElementById('pvLanguageStyles')){
      const style=document.createElement('style');
      style.id='pvLanguageStyles';
      style.textContent=`.pv-language-switch{display:inline-flex;align-items:center;gap:2px;padding:3px;border:1px solid rgba(99,122,112,.28);border-radius:999px;background:rgba(255,255,255,.9);box-shadow:0 6px 20px rgba(5,29,22,.06);flex:0 0 auto}.pv-language-switch button{appearance:none;border:0!important;background:transparent!important;color:#61756d!important;border-radius:999px!important;padding:.34rem .48rem!important;min-width:auto!important;font:800 .62rem/1 system-ui,sans-serif!important;cursor:pointer!important}.pv-language-switch button.active{background:#071d17!important;color:#fff!important}.pv-language-switch button:focus-visible{outline:2px solid #75a894;outline-offset:2px}`;
      document.head.appendChild(style);
    }
    let wrap=document.getElementById('pvLanguageSwitch');
    if(!wrap){
      wrap=document.createElement('div');
      wrap.id='pvLanguageSwitch';
      wrap.className='pv-language-switch';
      wrap.setAttribute('aria-label','Language / Jezik');
      wrap.innerHTML='<button type="button" data-lang="sl">SL</button><button type="button" data-lang="en">EN</button>';
      const target=document.querySelector('.top-actions,.nav-links,.topbar .top-actions,.editor-top .top-actions,.top .top-actions');
      if(target)target.prepend(wrap);else document.body.prepend(wrap);
    }
    if(!wrap.dataset.bound){
      wrap.dataset.bound='1';
      wrap.addEventListener('click',e=>{const b=e.target.closest('[data-lang]');if(b)setLanguage(b.dataset.lang);});
    }
    updateSwitcher();
  }

  function updateSwitcher(){
    document.querySelectorAll('#pvLanguageSwitch [data-lang]').forEach(b=>{
      const active=b.dataset.lang===language;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));
    });
  }

  function setLanguage(next){
    language=next==='en'?'en':'sl';
    localStorage.setItem(STORAGE_KEY,language);
    updateMeta();walk();updateSwitcher();
    window.dispatchEvent(new CustomEvent('pv:languagechange',{detail:{language}}));
  }

  let pending=false;
  const observer=new MutationObserver(mutations=>{
    if(pending)return;
    pending=true;
    queueMicrotask(()=>{
      pending=false;
      for(const mutation of mutations){
        if(mutation.type==='characterData')translateTextNode(mutation.target);
        for(const node of mutation.addedNodes){
          if(node.nodeType===Node.TEXT_NODE)translateTextNode(node);
          else if(node instanceof Element)walk(node);
        }
      }
    });
  });

  function boot(){
    ensureSwitcher();updateMeta();walk();updateSwitcher();
    observer.observe(document.body,{subtree:true,childList:true,characterData:true});
    window.PV_I18N={get language(){return language},setLanguage,translate:walk};
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();