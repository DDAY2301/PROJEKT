(() => {
  const STORAGE_KEY = 'pv_draft_v1';
  const API_STORAGE_KEY = 'pv_api_url';
  const validPackages = new Set(['Start','Standard','Premium']);
  const prices = {Start:'490 €', Standard:'890 €', Premium:'1.490 €'};

  function cleanApi(value) { return String(value || '').trim().replace(/\/$/, ''); }
  function apiFromLanding() {
    const params = new URLSearchParams(location.search);
    const fromUrl = cleanApi(params.get('api'));
    if (fromUrl && /^https?:\/\//i.test(fromUrl)) { localStorage.setItem(API_STORAGE_KEY, fromUrl); return fromUrl; }
    const saved = cleanApi(localStorage.getItem(API_STORAGE_KEY));
    return /^https?:\/\//i.test(saved) ? saved : '';
  }
  const activeApi = apiFromLanding();

  function readDraft() { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {}; } catch { return {}; } }
  function writeDraft(patch = {}) { const next={...readDraft(),...patch,updated_at:new Date().toISOString()}; localStorage.setItem(STORAGE_KEY,JSON.stringify(next)); return next; }
  function chosenPackage() { const draft=readDraft(); return validPackages.has(draft.package) ? draft.package : 'Standard'; }
  function builderUrl(pkg) {
    const url = new URL('builder.html', location.href); url.search=''; url.hash=''; url.searchParams.set('paket',pkg); if(activeApi)url.searchParams.set('api',activeApi); url.searchParams.set('v','landing-flow'); return url.href;
  }
  function dashboardUrl() { const url=new URL('dashboard.html',location.href); url.search=''; if(activeApi)url.searchParams.set('api',activeApi); return url.href; }

  const navLinks=document.querySelector('.nav-links');
  if(navLinks && !navLinks.querySelector('[data-dashboard-link]')){
    const a=document.createElement('a'); a.href=dashboardUrl(); a.dataset.dashboardLink='1'; a.textContent='Moji projekti';
    const button=navLinks.querySelector('.button'); navLinks.insertBefore(a,button||null);
  }

  const packageSection = document.querySelector('#paketi .wrap');
  const priceGrid = packageSection?.querySelector('.prices');
  if (!packageSection || !priceGrid) return;

  const style = document.createElement('style');
  style.textContent = `
    .landing-start{margin:1.4rem 0 2rem;padding:clamp(1.2rem,3vw,2rem);border:1px solid var(--line);border-radius:1.5rem;background:#fff;box-shadow:0 18px 55px rgba(10,42,34,.07)}
    .landing-start-head{display:grid;grid-template-columns:1fr auto;gap:1rem;align-items:end;margin-bottom:1rem}.landing-start h3{margin:.2rem 0 0;font-size:clamp(1.6rem,3vw,2.6rem);letter-spacing:-.045em}.landing-start p{margin:.35rem 0 0;color:var(--muted);max-width:54rem}.landing-start-badge{padding:.45rem .65rem;border-radius:999px;background:var(--green-light);color:var(--green);font-size:.72rem;font-weight:900;white-space:nowrap}
    .landing-start-grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}.landing-field{display:grid;gap:.3rem}.landing-field.full{grid-column:1/-1}.landing-field label{font-size:.76rem;font-weight:850}.landing-field input,.landing-field textarea{width:100%;padding:.75rem .8rem;border:1px solid var(--line);border-radius:.75rem;background:#fbfcfa;font:inherit;color:var(--ink)}.landing-field textarea{min-height:6.5rem;resize:vertical}.landing-field input:focus,.landing-field textarea:focus{outline:3px solid rgba(27,118,95,.1);border-color:var(--green)}
    .landing-package-row{display:flex;gap:.55rem;flex-wrap:wrap;margin:1rem 0}.landing-package{border:1px solid var(--line);border-radius:.75rem;background:#fff;padding:.65rem .8rem;cursor:pointer;text-align:left;min-width:9rem}.landing-package strong,.landing-package span{display:block}.landing-package strong{font-size:.78rem}.landing-package span{margin-top:.1rem;color:var(--muted);font-size:.68rem}.landing-package.active{border-color:var(--green);background:#eaf5f0;box-shadow:0 0 0 2px rgba(27,118,95,.08)}
    .landing-start-actions{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem;padding-top:1rem;border-top:1px solid var(--line)}.landing-saved{color:var(--muted);font-size:.72rem}.landing-start .button{cursor:pointer}
    @media(max-width:760px){.landing-start-head,.landing-start-grid{grid-template-columns:1fr}.landing-start-actions{align-items:stretch;flex-direction:column}.landing-start .button{width:100%}.landing-start-badge{justify-self:start}}
  `;
  document.head.appendChild(style);

  const draft = readDraft();
  const card = document.createElement('div');
  card.className = 'landing-start';
  card.innerHTML = `
    <div class="landing-start-head"><div><div class="eyebrow">Začni že na prvi strani</div><h3>Osnovni brief se prenese v builder.</h3><p>Vpiši ključne podatke, izberi paket in nadaljuj. Vnos se shrani samo v tvojem brskalniku in se v builderju samodejno izpolni.</p></div><span class="landing-start-badge">SHRANI IN NADALJUJ</span></div>
    <div class="landing-start-grid">
      <div class="landing-field"><label for="landingName">Ime projekta</label><input id="landingName" autocomplete="off"></div>
      <div class="landing-field"><label for="landingOrg">Organizacija / podjetje</label><input id="landingOrg" autocomplete="organization"></div>
      <div class="landing-field"><label for="landingAudience">Ciljna publika</label><input id="landingAudience" autocomplete="off"></div>
      <div class="landing-field"><label for="landingProgramme">Program / dejavnost</label><input id="landingProgramme" placeholder="npr. storitev, Erasmus+, produkt"></div>
      <div class="landing-field full"><label for="landingGoal">Kaj mora spletna stran doseči?</label><textarea id="landingGoal" placeholder="Na kratko opiši namen, ponudbo in želeni rezultat."></textarea></div>
    </div>
    <div class="landing-package-row" aria-label="Izbira paketa">${['Start','Standard','Premium'].map(name=>`<button type="button" class="landing-package" data-landing-package="${name}"><strong>${name}</strong><span>${prices[name]}</span></button>`).join('')}</div>
    <div class="landing-start-actions"><span class="landing-saved" id="landingSaved">Osnutek se shranjuje samodejno.</span><button class="button" id="landingContinue" type="button">Nadaljuj v builder →</button></div>`;
  priceGrid.parentNode.insertBefore(card, priceGrid);

  const fields={name:document.getElementById('landingName'),organization:document.getElementById('landingOrg'),audience:document.getElementById('landingAudience'),programme:document.getElementById('landingProgramme'),goal:document.getElementById('landingGoal')};
  Object.entries(fields).forEach(([key,el])=>{el.value=draft[key]||'';el.addEventListener('input',()=>{writeDraft({[key]:el.value});const saved=document.getElementById('landingSaved');if(saved)saved.textContent='Shranjeno v tem brskalniku.';});});
  let pkg=chosenPackage();
  function paintPackage(){document.querySelectorAll('[data-landing-package]').forEach(btn=>btn.classList.toggle('active',btn.dataset.landingPackage===pkg));}
  paintPackage();
  document.querySelectorAll('[data-landing-package]').forEach(btn=>btn.addEventListener('click',()=>{pkg=btn.dataset.landingPackage;writeDraft({package:pkg});paintPackage();}));
  document.getElementById('landingContinue')?.addEventListener('click',()=>{writeDraft({package:pkg,name:fields.name.value,organization:fields.organization.value,audience:fields.audience.value,programme:fields.programme.value,goal:fields.goal.value});location.href=builderUrl(pkg);});
  document.querySelectorAll('a[href*="builder.html"]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();const href=new URL(link.href,location.href);const explicit=href.searchParams.get('paket');const selected=validPackages.has(explicit)?explicit:pkg;writeDraft({package:selected});location.href=builderUrl(selected);}));
})();
