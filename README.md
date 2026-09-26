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


## Local AI backends

The generation runtime is local-first and can use:

- Ollama with multiple local fallback models.
- Any local OpenAI-compatible server such as LM Studio, vLLM or SGLang.
- Ollama vision QA can remain active even when code generation uses a different local backend.

Ollama flow:

`./start-product.ps1`

OpenAI-compatible local flow:

`./start-openai-compatible-local.ps1 -BaseUrl "http://127.0.0.1:1234/v1" -Models "your-model-id"`

## Current advanced workflow

The current product includes safe ZIP drag-and-drop import, Git-backed standalone source editing, private preview, natural-language revision, version history and rollback, responsive WebP/AVIF media, smart focal crops, deterministic bundle QA, Chromium runtime/visual QA, local multimodal design review, persistent quality learning, model telemetry and Lighthouse regression budgets.

Optional future adapters such as GrapesJS/Monaco/tree-sitter/browser automation should preserve the existing Git source and QA gates rather than bypass them.


## Image Studio

Project Visibility includes a non-destructive Image Studio at `dist/image-studio.html`.

Current local capabilities:
- crop, rotate, horizontal/vertical flip
- brightness, contrast, saturation and blur
- subject/background separation with optional `rembg` and a deterministic fallback
- transparent, solid-colour, blurred, uploaded or project-image backgrounds
- soft-shadow composition
- image edit history and restore snapshots
- responsive WebP/AVIF regeneration after every saved edit
- brand-aware offline background generation
- optional local ComfyUI AI background generation

Install the optional local background-removal engine after the first normal start:

`./install-image-tools.ps1`

For local ComfyUI generation set `COMFYUI_BASE_URL` and `COMFYUI_CHECKPOINT` before starting the API. Without ComfyUI the generation endpoint automatically falls back to the local brand-aware procedural engine.
