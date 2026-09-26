# Project Visibility

Project Visibility is a website studio for turning a structured brief, brand direction and project media into a tested, publishable and editable website.

## Public frontend

The deployable frontend lives in `dist/`. GitHub Pages publishes that directory from `main` through `.github/workflows/pages.yml`.

Current public product URL supplied for the project:

`https://project-visibility.dan-grmusa.chatgpt.site/`

Builder and dashboard remain `noindex`; the landing page is indexable and includes canonical metadata, robots.txt and sitemap.xml.

## Runtime architecture

- `dist/index.html` — landing + package/brief entry
- `dist/builder.html` — account, brief, media studio, preview and build flow
- `dist/dashboard.html` — customer projects, QA, revisions and delivery
- `api/` — authentication, generation, media, billing, preview, revisions, notifications and QA
- `dist/assets/runtime-config.js` — central public API base URL
- `start-product.ps1` — local development launcher with verified Cloudflare Quick Tunnel fallback

For a production backend, set the stable HTTPS endpoint once in:

```js
window.PV_RUNTIME = Object.freeze({
  apiBase: "https://api.example.com"
});
```

Do not place API keys, GitHub tokens, Stripe secrets or e-mail credentials in `runtime-config.js` or any public frontend file.

## Quality gates

Every push to `main` validates the public builder and performs JavaScript syntax checks before the Pages artifact is deployed. The backend also contains deterministic Chromium visual QA for desktop, tablet and mobile renders.

## Local development

Use `start-product.ps1` for the complete local product flow. Quick Tunnel URLs are development fallbacks and are disposable; production should use a persistent hosted API with TLS.

See `PRODUCT_NO1_ROADMAP.md` for product targets and remaining production gates.
