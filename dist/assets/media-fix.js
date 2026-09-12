(() => {
  const allowed = new Set(['image/jpeg','image/png','image/webp']);
  const maxBytes = 8 * 1024 * 1024;
  const maxImages = 12;

  function addPickedFiles(files) {
    if (!Array.isArray(selectedImages)) return;
    const room = Math.max(0, maxImages - selectedImages.length);
    const accepted = Array.from(files || []).filter(file => {
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

    accepted.forEach((file, index) => {
      selectedImages.push({
        file,
        kind: 'image',
        placement: selectedImages.some(x => x.kind !== 'logo') || index > 0 ? 'auto' : 'hero',
        alt: file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim(),
        focalX: 50,
        focalY: 50,
        previewUrl: URL.createObjectURL(file)
      });
    });

    if (typeof renderImageQueue === 'function') renderImageQueue();
    if (accepted.length) status(`SLIKE DODANE\n${accepted.length} datotek je pripravljenih. Za vsako lahko nastaviš stran, vlogo in focal point.`);
  }

  function loadPostbuildPaymentFlow() {
    if (document.querySelector('script[data-pv-payment-flow]')) return;
    const script = document.createElement('script');
    script.src = 'assets/payment-flow-v2.js?v=20260912-3';
    script.defer = true;
    script.dataset.pvPaymentFlow = '1';
    document.body.appendChild(script);
  }

  function bind() {
    const input = document.getElementById('projectImages');
    if (input && input.dataset.pvPickerBound !== '1') {
      input.dataset.pvPickerBound = '1';
      input.addEventListener('change', event => {
        addPickedFiles(event.target.files);
        event.target.value = '';
      });
    }

    document.querySelectorAll('.stage').forEach(stage => {
      if (/Media studio|Videz/.test(stage.textContent || '')) {
        stage.style.cursor = 'pointer';
        stage.addEventListener('click', () => document.getElementById('mediaStudioCard')?.scrollIntoView({behavior:'smooth', block:'start'}));
      }
    });

    loadPostbuildPaymentFlow();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();