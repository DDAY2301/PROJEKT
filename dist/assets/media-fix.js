(() => {
  const allowed = new Set(['image/jpeg','image/png','image/webp']);
  const maxBytes = 8 * 1024 * 1024;
  const maxImages = 12;

  const esc = value => String(value || '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));

  function validFiles(files) {
    const room = Math.max(0, maxImages - (Array.isArray(selectedImages) ? selectedImages.length : 0));
    return Array.from(files || []).filter(file => {
      if (!allowed.has(file.type)) {
        status(`SLIKA NI SPREJETA\n${file.name}: uporabi JPG, PNG ali WebP.`);
        return false;
      }
      if (file.size > maxBytes) {
        status(`SLIKA JE PREVELIKA\n${file.name}: največ 8 MB na sliko.`);
        return false;
      }
      return true;
    }).slice(0, room);
  }

  function fallbackAdd(files, kind='image') {
    if (!Array.isArray(selectedImages)) return;
    const accepted = validFiles(files);
    accepted.slice(0, kind === 'logo' ? 1 : accepted.length).forEach((file, index) => {
      selectedImages.push({
        file,
        kind,
        placement: kind === 'logo' ? 'logo' : (selectedImages.some(x => x.kind !== 'logo') || index > 0 ? 'auto' : 'hero'),
        alt: kind === 'logo' ? 'Logo' : file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim(),
        focalX: 50,
        focalY: 50,
        previewUrl: URL.createObjectURL(file)
      });
    });
    if (typeof renderImageQueue === 'function') renderImageQueue();
    syncMediaPreview();
    if (accepted.length) status(`SLIKE DODANE\n${accepted.length} datotek je pripravljenih. Določi stran, vlogo in focal point.`);
  }

  function ensurePreviewMedia() {
    const canvas = document.getElementById('previewCanvas');
    if (!canvas || document.getElementById('previewMedia')) return;
    const style = document.createElement('style');
    style.textContent = `
      .preview-media{display:none;position:relative;margin:1rem 0 1.15rem;border-radius:1rem;overflow:hidden;aspect-ratio:16/10;background:#e6eee9;box-shadow:0 16px 35px rgba(7,31,24,.12)}
      .preview-media.visible{display:block}.preview-media img{width:100%;height:100%;display:block;object-fit:cover}.preview-media .preview-media-label{position:absolute;left:.65rem;bottom:.65rem;padding:.3rem .45rem;border-radius:999px;background:rgba(4,26,19,.78);color:#fff;font-size:.56rem;font-weight:850;letter-spacing:.04em;text-transform:uppercase}
      .preview-logo-image{display:none;max-width:8rem;max-height:2.2rem;object-fit:contain}.preview-logo-image.visible{display:block}.preview-logo.has-image{font-size:0}
    `;
    document.head.appendChild(style);
    const media = document.createElement('div');
    media.id = 'previewMedia';
    media.className = 'preview-media';
    media.innerHTML = '<img id="previewMediaImage" alt=""><span class="preview-media-label">Project media preview</span>';
    const eyebrow = document.getElementById('previewEyebrow');
    eyebrow?.after(media);
    const logo = document.getElementById('previewLogo');
    if (logo) {
      const logoImg = document.createElement('img');
      logoImg.id = 'previewLogoImage';
      logoImg.className = 'preview-logo-image';
      logo.appendChild(logoImg);
    }
  }

  function syncMediaPreview() {
    ensurePreviewMedia();
    if (!Array.isArray(selectedImages)) return;
    const hero = selectedImages.find(x => x.kind !== 'logo' && (x.placement === 'hero' || String(x.placement || '').endsWith(':hero')))
      || selectedImages.find(x => x.kind !== 'logo');
    const media = document.getElementById('previewMedia');
    const img = document.getElementById('previewMediaImage');
    if (media && img) {
      if (hero?.previewUrl) {
        img.src = hero.previewUrl;
        img.alt = hero.alt || hero.file?.name || '';
        img.style.objectPosition = `${Number(hero.focalX ?? 50)}% ${Number(hero.focalY ?? 50)}%`;
        media.classList.add('visible');
      } else {
        media.classList.remove('visible');
        img.removeAttribute('src');
      }
    }
    const logo = selectedImages.find(x => x.kind === 'logo' || x.placement === 'logo');
    const logoHost = document.getElementById('previewLogo');
    const logoImg = document.getElementById('previewLogoImage');
    if (logoHost && logoImg) {
      if (logo?.previewUrl) {
        logoImg.src = logo.previewUrl;
        logoImg.alt = logo.alt || 'Logo';
        logoImg.classList.add('visible');
        logoHost.classList.add('has-image');
      } else {
        logoImg.classList.remove('visible');
        logoHost.classList.remove('has-image');
      }
    }
  }

  function ensureFallbackDropzone() {
    const input = document.getElementById('projectImages');
    if (!input || document.getElementById('mediaDropzone')) return;
    input.style.display = 'none';
    const drop = document.createElement('div');
    drop.id = 'mediaDropzone';
    drop.tabIndex = 0;
    drop.setAttribute('role','button');
    drop.style.cssText = 'display:grid;place-items:center;min-height:150px;border:1.5px dashed #91aa9f;border-radius:18px;background:#f3f8f5;padding:24px;text-align:center;cursor:pointer';
    drop.innerHTML = '<div><strong style="display:block;font-size:16px">Spusti fotografije sem ali klikni za izbor</strong><span style="display:block;margin-top:7px;color:#6a7d76;font-size:13px">JPG, PNG ali WebP · do 12 slik · samodejni WebP/AVIF + srcset</span></div>';
    input.before(drop);
    const logo = document.createElement('button');
    logo.type = 'button';
    logo.textContent = '+ Dodaj logotip';
    logo.style.cssText = 'margin-top:10px;border:1px solid #b9c8c1;border-radius:12px;background:#fff;padding:10px 14px;font-weight:800;cursor:pointer';
    const logoInput = document.createElement('input');
    logoInput.type = 'file';
    logoInput.accept = 'image/jpeg,image/png,image/webp';
    logoInput.hidden = true;
    drop.after(logo, logoInput);

    drop.addEventListener('click', () => input.click());
    drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    ['dragenter','dragover'].forEach(name => drop.addEventListener(name, e => { e.preventDefault(); drop.style.background = '#e6f3ec'; }));
    ['dragleave','drop'].forEach(name => drop.addEventListener(name, e => { e.preventDefault(); drop.style.background = '#f3f8f5'; }));
    drop.addEventListener('drop', e => fallbackAdd(e.dataTransfer?.files, 'image'));
    input.addEventListener('change', e => { fallbackAdd(e.target.files, 'image'); e.target.value = ''; });
    logo.addEventListener('click', () => logoInput.click());
    logoInput.addEventListener('change', e => { fallbackAdd(e.target.files, 'logo'); e.target.value = ''; });
  }

  function loadPostbuildPaymentFlow() {
    if (document.querySelector('script[data-pv-payment-flow]')) return;
    const script = document.createElement('script');
    script.src = 'assets/payment-flow-v2.js?v=20260914-1';
    script.defer = true;
    script.dataset.pvPaymentFlow = '1';
    document.body.appendChild(script);
  }

  function bind() {
    // workspace-upgrades.js normally creates the full drag/drop editor first.
    // This fallback guarantees that the GUI still works even if that enhancement
    // is unavailable or a cached browser version did not create it.
    ensureFallbackDropzone();
    ensurePreviewMedia();

    const queue = document.getElementById('imageQueue');
    if (queue) {
      new MutationObserver(() => syncMediaPreview()).observe(queue, {subtree:true, childList:true, characterData:true, attributes:true});
    }
    document.addEventListener('input', event => {
      if (event.target?.matches?.('[data-fx],[data-fy],[data-placement]')) syncMediaPreview();
    });
    document.addEventListener('change', event => {
      if (event.target?.matches?.('[data-placement]')) syncMediaPreview();
    });

    document.querySelectorAll('.stage').forEach(stage => {
      if (/Media studio|Videz/.test(stage.textContent || '')) {
        stage.style.cursor = 'pointer';
        stage.addEventListener('click', () => document.getElementById('mediaStudioCard')?.scrollIntoView({behavior:'smooth', block:'start'}));
      }
    });

    syncMediaPreview();
    loadPostbuildPaymentFlow();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
