# Project Visibility — Product Leadership Roadmap

Last updated: 2026-09-10

## Product promise

A customer describes the website they need, configures the visual direction and receives a tested, published, editable website with source ownership. After launch, the same website can be changed through plain-language requests without rebuilding from scratch.

## North-star workflow

Brief → structure → design → build → technical QA → visual QA → self-fix → publish → live verification → edit/revise → republish → ownership handoff.

## Product scorecard

The product is not considered market-leading until the following can be measured repeatedly on a benchmark set of at least 50 websites.

| Area | Target |
|---|---|
| Successful build rate | >= 95% without manual developer intervention |
| Successful revision rate | >= 95% for scoped text/design/content changes |
| Median time to first published site | <= 5 minutes for Start sites |
| Median time to revision publish | <= 3 minutes |
| Lighthouse Performance | >= 90 desktop, >= 80 mobile on benchmark set |
| Lighthouse Accessibility | >= 95 |
| Lighthouse Best Practices | >= 95 |
| Lighthouse SEO | >= 95 |
| Critical/high QA findings at handoff | 0 |
| Broken internal links at handoff | 0 |
| Source ownership | 100% of delivered sites have customer-accessible source |
| Live URL verification | 100% before UI reports READY |
| Infrastructure uptime | >= 99.9% once production backend is hosted |
| AI cost per successful Start build | target <= €1 before support/hosting |
| Human intervention | target <= 10 minutes median per standard website |

## Competitive parity gates

### Gate A — Reliable autonomous delivery
- [x] User authentication
- [x] Structured website brief
- [x] Responsive static generation
- [x] Technical + model QA
- [x] Self-fix loop
- [x] GitHub source publishing
- [x] GitHub Pages publishing
- [x] Live deployment check
- [x] Natural-language post-build revision engine
- [ ] Production queue with retries and idempotency
- [ ] Persistent hosted database
- [ ] Hosted API with stable domain and TLS
- [ ] Structured logging, error tracking and uptime monitoring
- [ ] Rate limiting and abuse controls

### Gate B — Best-in-class editing
- [x] Live visual direction preview before build
- [x] Plain-language edits after publishing
- [x] Revision history
- [ ] Click/select an element in the live preview and edit only that element
- [ ] Version snapshots and one-click rollback
- [ ] Before/after visual diff
- [ ] Page/section reorder controls
- [ ] Image upload, replace, crop and focal-point controls
- [ ] Reusable brand kit (logo, fonts, palette, tone)

### Gate C — Design quality
- [ ] Multi-pass design critic before code generation
- [ ] Screenshot-based visual QA at desktop/tablet/mobile widths
- [ ] Layout collision/overflow detection
- [ ] Typography scale and spacing-system validator
- [ ] Contrast validation against WCAG targets
- [ ] Strong curated component/design-pattern library
- [ ] Vertical-specific art direction for business, NGO, Erasmus+, CERV, Horizon, events and campaigns

### Gate D — Content system
- [ ] User-managed pages after launch
- [ ] News/blog collections
- [ ] Gallery/media library
- [ ] Team/partner/result collections
- [ ] Search
- [ ] Forms + spam protection
- [ ] Localization workflow
- [ ] EU-project visibility/compliance preset library

### Gate E — Commercial SaaS
- [ ] Stripe checkout and package enforcement
- [ ] Customer dashboard with sites, status and invoices
- [ ] Usage/credit accounting
- [ ] Custom domains
- [ ] Automatic SSL/DNS onboarding
- [ ] Email delivery and notifications
- [ ] Team/client roles
- [ ] White-label/reseller mode
- [ ] Analytics dashboard

### Gate F — Model and cost architecture
- [x] Local model execution for development
- [ ] Model router: cheap local → stronger local → premium cloud only when needed
- [ ] Per-stage token/compute accounting
- [ ] Prompt/result caching
- [ ] Build benchmark harness
- [ ] Automatic model fallback on invalid JSON or low QA score
- [ ] Parallelizable QA stages

## Current priority order

1. Production hosting and stable API endpoint.
2. Element-level editing + version snapshots/rollback.
3. Screenshot visual QA and objective performance testing.
4. Brand assets and image workflow.
5. Persistent CMS/content editing.
6. Payments, account dashboard and package enforcement.
7. Custom domains and automated DNS.
8. Model routing and cost optimization.
9. Vertical-specific EU/NGO website intelligence.
10. White-label/reseller API.

## Release rule

No feature is labelled production-ready merely because it works once. It must have an automated test or a repeatable acceptance test, observable failure behavior and a recovery path.
