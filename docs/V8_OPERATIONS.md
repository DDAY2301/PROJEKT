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
