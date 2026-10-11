# Project Visibility V8 — cleanup, host efficiency and design direction

## State and trust boundaries

This repo owns the Project Visibility website factory. BlogLab is production
(`DDAY2301/blog-lab`) and is **not** modified. The user requested removal of
generated test website repositories, not deletion of unrelated code projects.

An inventory of **29** repositories under `DDAY2301` identified **21**
repositories with `generated-site-` names on 2026-10-11. Their exact names
are pinned in `tools/generated-site-cleanup-manifest.json`.

**Explicitly protected:** `DDAY2301/blog-lab`, `DDAY2301/PROJEKT`.
**Not automatically targeted:** `Black-Raven`, `dalija-website`,
`Agrilo`, `agrilo-app`, `agrilo-backend`, `WM`.
They require separate review and explicit consent before any deletion.

## Cleanup (manual, destructive, backup first)

The connected GitHub integration cannot delete repositories; the following
PowerShell script must be run by the authenticated operator after obtaining
a **fresh PAT** with Administration: Read and write on the target repositories.
Never paste the token in chat or commit it.

```powershell
cd 'C:\Users\dangr\PROJEKT'
git pull --ff-only origin main
.\tools\cleanup-generated-github.ps1           # inspect exact list only
.\tools\cleanup-generated-github.ps1 -Execute  # confirmation + PAT
```

`-Execute` requires typing the complete phrase
`DELETE 21 GENERATED REPOSITORIES` and entering the PAT in a hidden input.
For each repo, it checks owner/name, runs `git clone --mirror`, verifies the
backup and writes repository metadata BEFORE GitHub DELETE.
The local recovery directory is in
`$env:LOCALAPPDATA\ProjectVisibility\CleanupReports\<timestamp>`.
If cloning or deletion fails, the script stops. Consult the local report.
This cleanup is intentionally not scheduled or triggered by production AI.

**Do not delete first and back up afterwards.** GitHub API permissions and
network access will determine whether deletions can actually proceed. Never
claim deletion until actual GitHub DELETE succeeds and repos are absent.

## Actual V8 design prompt

`api/design_prompt_v3.py` selects a concise domain-specific design direction
using the current brief. It is used by:
- `api/robust_generation.py` during information-architecture planning;
- `api/design_critic.py` during plan review when needed;
- `api/vision_review.py` during the existing screenshot critique.

There is no second generator or permanent extra LLM worker. The prompt
favours real imagery, typographic hierarchy, compositional variety, effective
mobile layouts, truthful content, and domain-appropriate interaction.

The existing `api/design_engine_v2.py` still owns deterministic CSS and
motif variety; existing QA thresholds remain unchanged.

## Stable host profile

Measured host startup output previously reported **15.7 GB physical RAM**.
V8 therefore starts with the conservative profile on systems with <=20 GB:

- `PRODUCTION_WORKERS=1`
- `MODEL_CONCURRENCY=1`
- `VISUAL_QA_CONCURRENCY=1`
- `OLLAMA_MAX_LOADED_MODELS=1` **when the Ollama service is started with
  that environment**.
- `OLLAMA_VISION_KEEP_ALIVE=15s`
- Fast website builds avoid automatically loading a giant expert fallback;
  explicitly expert-routed operations retain access to installed experts.

Operator-supplied environment values override these defaults. Avoid running
a massive optional expert model on a small shared machine while building sites.
This profile may reduce benchmark throughput; it is prioritised for stability,
and must be evaluated against identical real briefs.

`start-product.ps1` and `api/start-local.ps1` no longer kill arbitrary
Python processes occupying port 8000: they check the owning command line
before restarting their own API. Other Windows applications/services and
Windows Defender remain untouched.

Inspect the live host (read-only, with no Windows changes):

```powershell
.\tools\inspect-agent-host.ps1
.\tools\inspect-agent-host.ps1 -AsJson
```

These scripts **do not** optimise Windows settings themselves, disable
services or create scheduled tasks. Actual CPU/RAM improvements require a
before/after run on the user's physical machine. Running Ollama *already*
started with an older configuration will not necessarily apply new environment
variables until Ollama itself is restarted by the operator.

## Next test sequence (after operator cleanup and API startup)

1. Ensure the local git tree is clean. Pull `main`.
2. Read-only host audit and RAM snapshot.
3. `python tools/v7_policy_smoke.py`
4. `python tools/v8_design_cleanup_smoke.py`
5. `python tools/editorial_smoke.py`
6. Start the API with `api/start-local.ps1 -SkipGitHub`, using a new
   **isolated SQLite DB_PATH**. Verify `/health`.
7. Run a real 10-site benchmark **without `--with-delivery`**, collect
   p50/p95, memory, CPU, repair rate and visual/originality scores.
8. Only with explicit approval, test deployment to one dedicated, disposable
   **test repo** and verify the live URL.
9. After 10-site QA passes and memory is stable, run 50-site benchmark.

Do not recreate dozens of GitHub test repositories just after cleanup.
Do not treat passing CI, a staged build, or public Project Visibility shell
as proof that generated customer websites were deployed.

Statuses: VERIFIED DONE / IMPLEMENTED BUT UNVERIFIED / FAILED / BLOCKED.


## V9 adaptive memory headroom (2026-10-11)

The observed Windows host reported 15.73 GB total / 5.29 GB free,
66.4% used, Project Visibility API ~112 MB working set, Ollama runtime
~63 MB working set and **no loaded Ollama model**. Many Chrome processes
were present, but their existence alone does not indicate browser QA
leaks. GitHub CI cannot measure the user's actual workstation.

**Implemented:**
- `api/resource_guard.py` uses Windows GlobalMemoryStatusEx (or Linux
  MemAvailable) for a read-only free RAM measurement.
- Existing `api/production_queue.py` now defers **claiming new**
  persisted jobs when available memory drops below configured reserve.
  Existing active work is never interrupted. The queue exposes
  `resource_admission` through its authenticated status endpoint.
- `PV_RESOURCE_GUARD_ENABLED=1` (default); set `0` for rollback.
- `PV_MIN_FREE_RAM_MB=1536` (default on >12 GB physical RAM),
  `768` on smaller machines. These are starting reserves, not an
  empirically proven optimum; override after measuring real load.
- On <=20 GB machines, Ollama coder `keep_alive` is 90 seconds by
  default instead of 10 minutes; the visual model keeps its existing
  short 15-second residency. Model concurrency, number of queue
  workers, and visual concurrency remain one by default on this host.
- The host inspection script now reports groups and top consumers by
  private committed MB; it hides command lines and is strictly
  read-only. Run `.\\tools\\inspect-agent-host.ps1 -Detailed` for
  a more complete report.

**Important constraints:**
- `OLLAMA_MAX_LOADED_MODELS` and `OLLAMA_NUM_PARALLEL` are **server
  configuration** variables. Settings in the API launcher do not
  change an Ollama server already running on port 11434. Plan a
  controlled Ollama restart *after active work finishes* if needed;
  verify using `ollama ps`. Do not force-kill a shared Ollama process.
- Memory guard is an admission controller, not a hard RAM quota and
  does not guarantee a 7B model will fit in RAM.
- Closing or pausing unneeded tabs or enabling Chrome Memory Saver
  is a manual, reversible browser action. Do not kill arbitrary Chrome
  processes, disable Windows security, or delete Windows paging.
- V9 defaults prioritize stable operation; lower resource usage and
  quality parity must be verified through a controlled loaded-model
  benchmark, not inferred from startup numbers alone.

**After code update and safe restart:**

```powershell
cd 'C:\\Users\\dangr\\PROJEKT'
git status --short
git pull --ff-only origin main
.\\tools\\inspect-agent-host.ps1
.\\.venv\\Scripts\\python.exe tools\\v9_resource_smoke.py
Invoke-RestMethod http://127.0.0.1:8000/health
```

If the API is already running, its process must be restarted to load
these imports and worker settings. `start-product.ps1` requires a valid
GitHub PAT and Cloudflare for the full remote product; local-only
testing can use `api/start-local.ps1 -SkipGitHub`. Run the real 10-site
load test with a **separate DB_PATH** only after health and resource
admission are verified. Do not recreate 21 test GitHub repositories.

### Expert-model safety on a 16 GB host

The launchers discover optional KAT/Qwen expert models. When RAM is
<=20 GB they now **do not auto-route** to installed expert models, to
avoid accidentally loading a very large model alongside Chrome/Chromium.
The standard `qwen2.5-coder:7b` remains the default. An operator can opt
back in by setting `$env:PV_ENABLE_LARGE_EXPERT_MODELS='1'` before
startup, only after confirming enough headroom in real tests.
This applies to the API process environment on restart and does not
uninstall or delete any Ollama model.


## V10 — safe URL, truthful backend status, reliable local startup

### Incident (2026-10-11)
Browser displayed **Dangerous** for a random `*.trycloudflare.com` URL.
Host check showed `127.0.0.1:8000` not listening; Ollama at 11434 was
listening but with no loaded model. Browser kept a stale “Online” badge.

Do **not** override Safe Browsing or enter credentials on the flagged URL.
These addresses are randomly assigned and disposable, not production
identities. Neither HTTPS nor a successful `/health` alone proves a
hostname has a good reputation or is safe for credential entry.

### Safe default and stable public access
- `start-product.ps1 -LocalOnly` launches the same existing local
  `api/start-local.ps1 -SkipGitHub` without needing a PAT, DNS, Cloudflare
  or any public browser URL. It leaves the server in the foreground.
- `start-product.ps1` with a valid PAT launches the API but defaults to
  **http://127.0.0.1:8000/builder.html** when no stable public API URL
  is explicitly provided. No random Cloudflare Quick Tunnel is started.
- For public access, first configure an account-owned, long-lived HTTPS
  hostname using a **named Cloudflare tunnel** or another supported
  TLS reverse proxy. Configure the DNS/tunnel **outside** this script,
  verify that endpoint's identity, then launch:
  `./start-product.ps1 -PublicApiUrl https://api.your-domain.example`
  (or set `PV_PUBLIC_API_URL`). The launcher refuses `trycloudflare.com`,
  checks remote `/health` and opens the canonical GitHub Pages builder.
- `dist/runtime.html` is now a legacy safety notice that can only link
  to the GitHub Pages builder. It never redirects users to an arbitrary
  external hostname.
- On temporary tunnel origins the builder disables its account inputs.
  When the API address is supplied by a link, the user must manually
  confirm it in Connection settings unless `PV_RUNTIME.apiBase` was
  explicitly configured for the hosted site.
- Backend health identifies the service as `project_visibility`, probes
  Ollama `/api/tags` without loading a model, and reports
  `ollama_online`, `model_installed` and `model_ready`. GitHub
  `github_configured` still means token **present**, not end-to-end
  deployment proven.
- Builder refreshes health every 30 seconds while the tab is visible.
  An offline API no longer stays green indefinitely.

### Recommended recovery steps on the affected Windows host

Close the flagged browser tab; do not bypass its warning.
After confirming no Project Visibility job is running, open PowerShell:

```powershell
cd 'C:\Users\dangr\PROJEKT'
git status --short
git pull --ff-only origin main

# Read-only regressions before the heavy model starts.
.\.venv\Scripts\python.exe tools\v10_safe_url_smoke.py
.\.venv\Scripts\python.exe tools\v9_resource_smoke.py

# No PAT, no random public domain. Leave this window running.
.\start-product.ps1 -LocalOnly
```

In another PowerShell window:
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
.\tools\inspect-agent-host.ps1
```
`ok=True` and `product=project_visibility` confirm the API identity.
`model_ready=True` indicates Ollama responds and the configured
model is installed; it does **not** certify generation quality.
Use `http://127.0.0.1:8000/builder.html` while testing locally.

If a local smoke script raises `AssertionError`, capture its **entire
Python traceback including the failing file and line**; the single
word `AssertionError` does not identify which condition failed.
Check `git rev-parse --short HEAD` before attributing it to the
latest version.

### Not yet verified
Remote Cloudflare DNS/named tunnel provisioning, Chrome Safe Browsing
reputation, public authentication and real end-to-end delivery all
require operator-side configuration/testing. GitHub CI cannot confirm
the user's Windows port is listening.


## V11 — login recovery, safe GitHub delivery and design V4

### Why health was green but login/publishing failed

A successful `/health` proves only the process responds. When started
with `start-product.ps1 -LocalOnly`, the API intentionally reports
`github_configured: false`; no GitHub repository can be created or
published in that mode. A cached browser token can also be invalid
after the operator switches SQLite `DB_PATH` or signs in to another
API instance. A registered account in one SQLite database does not
exist in a newly created isolated benchmark database.

### Supported local operating modes

```powershell
cd 'C:\Users\dangr\PROJEKT'
git status --short
git pull --ff-only origin main
.\.venv\Scripts\python.exe tools\v11_auth_publish_design_smoke.py

# No PAT, suitable for isolated smoke / model and design tests:
.\start-product.ps1 -LocalOnly

# Full LOCAL factory with authorized GitHub repository delivery:
# First stop the former API gracefully with Ctrl+C.
.\start-product.ps1 -LocalOnly -EnablePublishing
```

The second mode **keeps the UI strictly on**
`http://127.0.0.1:8000/builder.html`. It calls the existing
`api/start-local.ps1` without `-SkipGitHub`, requests a current PAT
in a hidden terminal prompt when required, and verifies authentication
with GitHub. It does **not** create a Cloudflare public tunnel, place
tokens in URLs or alter Windows firewall settings. Avoid exposing
the local backend to the internet.

The PAT requires appropriate Contents write, Pages access and, for
new repository creation, Administration write to the allowed account
repositories. Token acceptance by `/user` alone does **not** prove
creation or Pages publication permissions. Use the UI's new
**Preveri prijavo in objavo** diagnostic control while signed in to
check preflight; an authorized end-to-end disposable test repository is
still required to verify actual publication. Do not recreate dozens
of GitHub repositories during initial smoke tests.

### Login and database guidance

- The API now exposes authenticated `GET /auth/session`, validating
  both the JWT and the user's presence in the active SQLite DB.
- The Builder saves a token's API origin, validates sessions after
  refresh and clears stale sessions when they belong to a different
  backend or no longer correspond to a user. This prevents false
  “prijavljen” status.
- Use the same persistent `DB_PATH` when returning from testing to
  regular operation; the default is `api/data/agent.db`.
- If the chosen database contains no account for your email, register
  **once** in that local Builder; do not delete the previous DB to
  recover a password or account.
- No API token, password, personal email, or secret should be sent in
  a chat, GitHub issue or diagnostic report.

### Design agent V4

The existing `api/design_prompt_v3.py` now uses the internal
`art-direction-v4` contract, without creating a second generator.
A deterministic, brief-scoped motif encourages different content
layouts across client websites without adding inference calls.
The contract feeds the planner, design critic, visual reviewer and
actual CSS/HTML model calls, preserving customer colours, language,
authentic available images, accessibility and working CTA/navigation.
Originality, editorial QA and visual release gates remain unchanged.

### Acceptance criteria

- `/health` reports `ok=True`, `product=project_visibility`,
  `model_ready=True`. For publishing mode, `github_configured=True`.
- `GET /auth/session` succeeds with a valid browser login and returns
  HTTP 401 for an old token from a fresh DB.
- The UI preflight returns `READY` only if mandatory checks pass;
  it may report concrete GitHub/worker/disk blockers.
- An actual publication is marked verified **only** after the
  intended test repository and public URL are inspected.
- Test job and site throughput are measured separately from GitHub CI.


## V12 — Payment must never outrun the latest quality gate

Reported Alpine Field Lab screen: code generated, nine render checks,
Visual QA 64/100, twenty findings, `payment_pending`. This score is
below the backend minimum release floor of 90 (configurable only upward).
The UI also displayed a generic 'Testni način' banner while a saved
project remained in an earlier Stripe payment state.

**Safe interpretation:** The page is **not verified publish-ready**.
`payment_pending` means a Stripe Checkout session was opened, not that
Stripe marked the purchase paid or the site was deployed. An old
payment state does not prove the latest quality audit passed.

V12 adds three release protections:

1. `POST /billing/checkout` re-evaluates the latest stored visual QA,
   severe issues and release threshold **on the server** before creating
   any Stripe session. If missing/low QA, return HTTP 409; no new charge.
2. If a previous Stripe checkout does complete despite a subsequently
   failing QA audit, record the confirmed payment accurately, **hold
   the website in needs_review** and do not dispatch public delivery.
   The operator must repair the site and resolve billing fairly;
   never erase a real payment or quietly re-charge.
3. The served Builder explicitly includes `payment-flow-v2.js` and
   displays any failing QA status **before** payment instructions.
   A generic no-Stripe banner no longer promises free publication
   of saved projects. Checkout return URL is not treated as
   independent confirmation of a payment.

Neither opening a private preview nor creating a repository means
the release quality gate is passed. The existing Stripe billing
entitlements, visual thresholds, original QA checks and payment
fulfilment obligations remain in place.

**Operator-side follow-up:** Do not enter payment for a 64/100 build.
Use the authenticated project details and last_audit issues to
identify the blocking visual problems. After a fix and complete
re-review, re-test the same project (without losing customer media
or an already paid transaction). Re-run `tools/v12_payment_qa_smoke.py`
locally after pulling; restart the running API only when no
production job is in progress.
