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
