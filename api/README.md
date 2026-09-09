# Autonomous Website Agent API

Ta backend spremeni Project Visibility Sprint iz statične prodajne strani v samostojni sistem za izdelavo spletnih strani.

## Tok

1. Uporabnik se registrira ali prijavi.
2. Izbere paket Start / Standard / Premium.
3. Določi barve, slog, strani, ciljno publiko, besedilo, CTA, smer slik in posebne zahteve.
4. API pošlje brief lokalnemu Ollama modelu.
5. Design korak pripravi informacijsko arhitekturo.
6. Build korak generira statične HTML/CSS/JS datoteke.
7. Statični QA preveri osnovne napake, skrivnosti, SEO in dostopnost.
8. AI QA preveri UX, navigacijo, skladnost z briefom in očitne napake.
9. Če so napake critical/high, agent naredi največ MAX_AUTO_FIX_ATTEMPTS popravkov.
10. Rezultat se shrani v lasten GitHub repozitorij uporabnikovega projekta.
11. Scheduler periodično ponovno obdela projekte v stanju needs_review.

## Lokalni zagon brez plačljivih AI tokenov

Namesti Python 3.11+ in Ollama.

```bash
ollama pull qwen2.5-coder:7b
cp api/.env.example api/.env
pip install -r api/requirements.txt
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Builder je na `dist/builder/` in privzeto kliče `http://localhost:8000`.

## GitHub

Za avtomatsko ustvarjanje projektnih repozitorijev nastavi `GITHUB_TOKEN` kot strežniško okoljsko spremenljivko. Token nikoli ne sme biti v frontend kodi ali commitu. Za produkcijo je priporočljiv GitHub App z najmanjšimi potrebnimi dovoljenji namesto osebnega tokena.

## Pomembna omejitev

"Samostojno" pomeni nadzorovan agentni cikel, ne neomejenega spreminjanja produkcije. Agent omeji število samodejnih popravkov, blokira očitne skrivnosti v generirani kodi in problematičen build označi `needs_review` namesto da bi neskončno prepisoval projekt.

## Naslednja produkcijska plast

Pred javnim zagonom je treba dodati:
- pravo podatkovno bazo (PostgreSQL/Supabase namesto SQLite),
- Stripe checkout + webhook, ki odklene paket,
- object storage za uporabniške slike in logotipe,
- production worker/queue (Redis + worker ali podoben sistem),
- deployment provider (Cloudflare Pages/Vercel/Netlify ali lasten server),
- image pipeline,
- rate limiting, email verification, reset gesla in audit log,
- GitHub App namesto širokega PAT tokena.
