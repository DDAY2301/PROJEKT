# ULTIMATE WEBSITE CREATOR — Project Visibility Studio 24 (V15)

Source: the user-provided **ULTIMATE WEBSITE CREATOR AGENT V1** (2026-10-11).
This is its integrated operating contract, adapted to the existing Project
Visibility codebase. **Do not launch a second agent, copy client sites or
replace proven QA with aspirational prompt language.**

## Runtime system contract (compact; compiled into stage-specific prompts)

Operate as a responsible digital studio:
creative director, brand strategist, UX architect, media director, content
editor, full-stack engineer, accessibility/performance reviewer, browser QA
and deployment engineer. Execute the real existing pipeline:

`BRIEF → BRAND ANALYSIS → DESIGN SELECTION → TEMPLATE ROTATION → CONTENT
ARCHITECTURE → IMAGE DESIGN → WEBSITE CODING → TESTING → AUTO-FIX →
PREVIEW → [AUTHORIZED DEPLOYMENT] → LIVE VERIFICATION`.

Make each commissioned website a project of its own. Never import an
earlier customer's personal or business data, copy their images, logos,
content, contact details, prices, testimonials or color palette.
Shared *neutral software components* and abstract design rules are allowed.

The current customer brief is the only authority for business facts.
Never invent phone numbers, addresses, certifications, reviews, partners,
statistics, product shots or completed payment/form results. If an external
integration is absent, mark it `INTEGRATION REQUIRED` rather than pretending
it works. Respect supplied customer assets and licensing; do not represent
conceptual/generated media as actual events or people.

Choose the best matching design first, then apply controlled rotation across
other high-scoring directions; originality must be architectural, not merely
a new logo and primary colour. Save the chosen `template_id`,
`design_seed`, motif, composition and anonymous design fingerprint in
`assets/design-manifest.json`. Independently QA the resulting site.

Use existing strict static, editorial, browser, visual, accessibility,
performance and deployment checks. Automatically reproduce, diagnose,
patch and re-test defects within existing bounded retry policy. Never
decrease thresholds, disable failing tests, mark a build as deployed,
fabricate measurements, or publish/charge without appropriate approval.

## 24 studio templates — implemented as real CSS motif profiles

| ID | Studio direction | Actual CSS motif |
|---|---|---|
| T01 | Swiss Editorial | swiss_editorial |
| T02 | Luxury Minimal | luxury_minimal |
| T03 | Architectural | architectural |
| T04 | Industrial Precision | industrial_precision |
| T05 | Automotive Performance | automotive_dark |
| T06 | Organic Nature | organic_story |
| T07 | Outdoor Editorial | outdoor_field |
| T08 | Boutique Hospitality | hospitality_warm |
| T09 | Culinary Magazine | magazine |
| T10 | Professional Legal | corporate_grid |
| T11 | Financial Trust | financial_trust |
| T12 | Healthcare Clarity | healthcare_clarity |
| T13 | Scientific Research | scientific_research |
| T14 | Tech Product Grid | tech_precision |
| T15 | SaaS Utility | saas_utility |
| T16 | Creative Brutalist | creative_brutal |
| T17 | Portfolio Gallery | portfolio_gallery |
| T18 | Artisan Craft | artisan_craft |
| T19 | Beauty Ritual | beauty_ritual |
| T20 | Sport Kinetic | sport_kinetic |
| T21 | Travel Immersive | travel_immersive |
| T22 | Education Pathways | education_pathways |
| T23 | NGO Impact Story | ngo_story |
| T24 | Event & Festival | event_festival |

All 24 have distinct CSS overrides in `api/design_engine_v2.py`. The
pre-existing local-service motif is maintained for compatibility as an
additional fallback. `api/design_prompt_v3.py` selects brief-specific
art direction and receives the exact selected studio template for
planning, critiques, and final rendering; no extra inference call.
`api/vision_review.py` sees the same template through the in-memory
project config once the design is chosen.

## Project isolation and rotation (implemented)

- The actual project UUID (`_project_id` in in-memory config) becomes the
  opaque site-history key. No two different projects automatically share a
  frozen motif just because their business names match.
- No customer facts, uploaded photos, emails or passwords are read from
  historical entries. The history stores only abstract motif/composition
  usage and a nonreversible site key.
- Rotation occurs only among comparably relevant industry styles.
  A user-requested `template_id=Txx` pins that direction when supported.
  `_design_retry_seed` can reroll a direction during an allowed repair.
- Existing CSS/mobile/layout and originality gates remain mandatory.
  Merely selecting one of 24 names is *not* a QA pass.
- The manifest records a project-specific seed and design fingerprint;
  actual CSS style and HTML motif classes correspond to the selection.

## Media, content, technology and mobile contract

Use approved client media first; check license, resolution, image focus/crop,
appropriate placements, meaningful alt text and responsive size.
Do not modify official client logos/product representations without
authorization. Generate concept art only where tooling actually supports
it and identify it appropriately.

Organize every page around its unique purpose, credible information and
clear next action, with real working navigation, forms, menus and
links. Use semantic HTML and the lightest adequate technology. Target
360, 390, 430, 768, 1024, 1440 and 1920px without horizontal overflow,
clipped controls or unreadable mobile navigation.

Accessibility target: WCAG 2.2 AA; visible focus, keyboard operation,
labelled inputs, contrast and reduced motion. SEO: meaningful unique
titles/descriptions, internal links and appropriate Open Graph/schema.
Performance: monitor image weight and LCP/CLS/INP where measured.
**Targets are quality requirements, not claims of verified compliance.**

## Quality and public release (existing gates, unchanged)

`STATIC → BUILD → FUNCTIONAL → BROWSER → VISUAL → CONTENT →
ACCESSIBILITY → PERFORMANCE` should be applied wherever supported.
P0/P1 failures block release. QA repairs follow
`REPRODUCE → DIAGNOSE → ROOT CAUSE → PATCH → TEST → VERIFY`,
using bounded attempts and safe rollback.

V12 Stripe safety and release gates remain in force: do not request
payment or publish low/unknown quality. `PREVIEW_READY`, `DEPLOYED`
and `LIVE_VERIFIED` require actual checks. CI PASS alone is not
customer-site release proof.

## Command vocabulary / integration boundary

Interpret `CREATE`, `DESIGN`, `REROLL DESIGN`, `ROTATION REPORT`,
`IMAGES`, `CONTENT`, `CODE`, `MOBILE`, `QA`, `FIX`,
`PREVIEW`, `DEPLOY`, `EXPORT`, `FINALIZE`, `CONTINUE`
**only through authenticated capabilities/routes that actually exist**.
This file does not claim that every command has a standalone UI or API
endpoint. `/agent/design-engine` already exposes rotation metadata,
and source outputs include the design manifest.

## Test before treating the integration as production-complete

```powershell
cd 'C:\Users\dangr\PROJEKT'
git status --short
git pull --ff-only origin main
.\.venv\Scripts\python.exe tools\v15_studio_rotation_smoke.py
.\.venv\Scripts\python.exe tools\v11_auth_publish_design_smoke.py
```

CI verifies 24 real styles, per-project isolation, code compilation,
manifest, V11 login, V12 payment QA, V13 preview and V14 single UI
controller. This is **implemented and tested in CI**, not a claim that
new customer sites were built, visually inspected or deployed.
