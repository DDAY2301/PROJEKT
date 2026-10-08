#!/usr/bin/env python3
"""Real Project Visibility production load test.

Submits varied website briefs through the normal local API, observes the
persistent production queue, and writes JSON/CSV/Markdown reports with
throughput, queue wait, model latency, QA, repairs, originality and deployment.

Examples:
  python tools/production_load_test.py --count 10
  python tools/production_load_test.py --count 50 --timeout-minutes 240
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import secrets
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "api" / "data" / "agent.db"
REPORT_ROOT = ROOT / "load-test-results"
FINAL_STATES = {"ready", "needs_review", "failed", "ready_for_payment"}

BRIEFS = [
    ("Northline Legal","Northline Legal","B2B legal advisory","Generate qualified SME consultation enquiries.","Founders and SME directors","precise, calm, authoritative","#14213d","#e5b25d","#f6f3ed","#111827","classic","corporate editorial, precise, premium",["Domov","Storitve","Primeri","O nas","Kontakt"],"Clarity for decisions that carry weight.","Commercial legal guidance built around practical decisions, risk and momentum.","Book a consultation","architectural detail, quiet premium offices","Avoid gavels, handshakes and generic law-firm imagery."),
    ("Forest Run","Forest Run Outdoor","Outdoor education","Present field courses and convert visitors into enquiries.","Adults and young people interested in outdoor skills","direct, capable, grounded","#213a2d","#d6b25e","#e9eadf","#142018","modern","field journal, rugged, tactile",["Domov","Tečaji","Znanja","Zgodbe","Galerija","Kontakt"],"Learn outside. Stay capable.","Practical field skills taught through real conditions and clear instruction.","Explore courses","forest, tools, fire, shelter, real participants","No glossy adventure-tourism look."),
    ("Vector Works","Vector Works","Industrial automation","Explain automation services and generate B2B project enquiries.","Manufacturing managers and technical directors","technical, concise, credible","#0a2540","#35d0ba","#f3f7f8","#10212b","tech","precision engineering, technical grid",["Domov","Rešitve","Industrije","Proces","Kontakt"],"Automation engineered for the real production floor.","Control, integration and measurable reliability for industrial systems.","Discuss a project","machinery, controls, technical details","No sci-fi AI aesthetic."),
    ("Maison Luma","Maison Luma","Boutique interior design","Position the studio as premium and convert residential enquiries.","Premium residential clients","quiet, refined, editorial","#423a34","#d7c6ad","#f5f0e8","#2a2521","editorial","luxury minimal, tactile, warm",["Domov","Projekti","Studio","Proces","Kontakt"],"Rooms with rhythm, restraint and character.","Interiors shaped by material, proportion and the way people live.","Start a project","warm interiors, material details","Large whitespace and elegant typography; no SaaS layout."),
    ("DALIJA Clean","DALIJA","Professional cleaning services","Make services and pricing clear and drive quote requests.","Households and small businesses","friendly, trustworthy, efficient","#174f42","#cde7dd","#f8fbfa","#15312a","modern","clean local service, premium but approachable",["Domov","Storitve","Cenik","O nas","Galerija","Kontakt"],"Čist prostor brez kompliciranja.","Zanesljivo čiščenje domov in poslovnih prostorov z jasnim dogovorom.","Pridobi ponudbo","bright real interiors, cleaning details","Avoid sterile blue corporate cleaning clichés."),
    ("Atelier Grain","Atelier Grain","Furniture and wood craft","Show craftsmanship and convert custom furniture enquiries.","Homeowners, architects and boutique hospitality","craft-led, tactile, confident","#5b3b25","#c7925b","#eee5d8","#241a14","editorial","craft magazine, material-led",["Domov","Dela","Materiali","Proces","Studio","Kontakt"],"Made slowly. Built to stay.","Custom furniture where material, joinery and proportion do the talking.","Commission a piece","wood grain, workshop, hands, joints","Editorial asymmetric project imagery."),
    ("Relay Cloud","Relay Cloud","B2B SaaS","Explain workflow automation and generate demos.","Operations and customer-success teams","clear, technical, energetic","#5b4bff","#64f4ac","#090d17","#f5f7ff","tech","dark precision SaaS, product-led",["Domov","Platforma","Use Cases","Varnost","Cenik","Kontakt"],"Work moves. Relay keeps it connected.","A workflow layer for teams that need fewer handoffs and cleaner operations.","Request a demo","interface details and geometric product visuals","Avoid generic AI gradients and glassmorphism."),
    ("Common Ground","Common Ground Institute","Youth and community NGO","Explain programmes, evidence and participation pathways.","Young people, partners and municipalities","human, credible, active","#005f55","#f4c95d","#f3efe4","#18332f","modern","social-impact editorial, documentary",["Domov","Programi","Rezultati","Zgodbe","Partnerji","Kontakt"],"Local action. Shared capacity.","Programmes that give young people practical space to learn and participate.","Join the work","real workshops and community spaces","Avoid charity cliché; emphasize evidence."),
    ("Apex Detail","Apex Detail","Automotive detailing","Sell premium detailing packages and drive bookings.","Performance and premium car owners","sharp, premium, performance-led","#111318","#e64132","#07090c","#f4f5f6","modern","automotive dark, performance editorial",["Domov","Paketi","Proces","Galerija","Studio","Kontakt"],"Finish matters.","Paint correction, protection and detailing built around the car.","Book detailing","dark studio automotive photography","No neon cyberpunk."),
    ("Casa Alto","Casa Alto","Boutique hospitality","Present the stay, rooms and location and drive direct enquiries.","Couples and design-conscious travellers","warm, calm, sensory","#714b34","#d9b88f","#f3eadf","#33251e","classic","warm hospitality editorial",["Domov","Sobe","Doživetje","Lokacija","Galerija","Kontakt"],"Stay somewhere with a point of view.","A small house shaped by quiet rooms, local material and time well spent.","Check availability","warm architecture and landscape","Magazine-like hospitality, not booking-platform UI."),
    ("Signal Journal","Signal Journal","Independent digital magazine","Create a publication identity and surface stories clearly.","Readers interested in design, technology and culture","editorial, curious, intelligent","#111111","#ff4f38","#f7f6f2","#111111","editorial","independent magazine, bold hierarchy",["Domov","Design","Technology","Culture","About","Contact"],"Ideas worth looking at twice.","Independent stories on design, technology and the culture around them.","Read the latest","editorial photography and graphic crops","Avoid landing-page cards and SaaS language."),
    ("Field Table","Field Table","Seasonal restaurant","Communicate restaurant identity and reservation intent.","Local diners and food travellers","warm, direct, seasonal","#36513f","#d7aa63","#eee8db","#2c2a22","classic","food journal, organic, seasonal",["Domov","Meni","Kuhinja","Dobavitelji","Galerija","Kontakt"],"Cook the season you are in.","A small kitchen built around local produce and a changing table.","Reserve a table","natural food photography and kitchen process","No delivery-app aesthetic."),
    ("Forma Physio","Forma Physio","Physiotherapy clinic","Explain services clearly and generate appointment enquiries.","Active adults recovering from pain or injury","calm, evidence-aware, accessible","#285e61","#a9d8d1","#f5f8f6","#1f3433","minimal","clinical calm, human, clean",["Domov","Obravnave","Pristop","Ekipa","FAQ","Kontakt"],"Move with less uncertainty.","Clear assessment, practical treatment and a plan you understand.","Book an assessment","real clinic movement and natural light","No unsupported medical outcomes or cure claims."),
    ("Stone & Line","Stone & Line Architects","Architecture studio","Show projects and attract serious architecture commissions.","Private, commercial and cultural clients","architectural, restrained, exact","#272724","#b9b4a7","#efeee9","#242421","editorial","swiss architecture monograph",["Domov","Projekti","Studio","Proces","Novice","Kontakt"],"Space, structure, consequence.","Architecture shaped by site, use and discipline.","View projects","architectural photography and models","Strong Swiss grid, minimal rounded UI."),
    ("Civic Data Lab","Civic Data Lab","Public-interest data research","Present research, tools and partnership opportunities.","Municipalities, researchers, NGOs and policy teams","rigorous, open, understandable","#2541b2","#f7c548","#f3f5f7","#172038","tech","research publication meets data lab",["Domov","Raziskave","Orodja","Podatki","Partnerstva","Kontakt"],"Public problems deserve legible evidence.","Research and data tools that help institutions see conditions more clearly.","Explore the work","maps, charts and civic spaces","Evidence-first visual hierarchy, not startup marketing."),
    ("Black Current","Black Current Records","Independent music label","Create an expressive label site for releases, artists and shows.","Listeners, press, bookers and artists","confident, cultural, raw","#111111","#d6ff3f","#f2f0e8","#111111","editorial","brutalist music culture, poster-like",["Domov","Izvajalci","Izdaje","Dogodki","O založbi","Kontakt"],"Records with a pulse.","Independent releases, live energy and artists with something specific to say.","Hear the releases","live photography and album artwork","Poster energy, asymmetric grid, no polished SaaS layout."),
    ("Green Roots","Green Roots Youth","European youth sustainability project","Explain activities, partners, outputs and participation.","Young people, youth workers and European partners","active, credible, accessible","#1c6047","#b6db6f","#f0f0e6","#173328","modern","environmental youth editorial",["Domov","Aktivnosti","Rezultati","Partnerji","Galerija","Kontakt"],"Learn it. Test it. Bring it home.","Youth-led green action built around practical learning and local follow-up.","Explore activities","workshops, food systems and circular economy","No fake EU claims or invented metrics."),
    ("North Dock Coffee","North Dock Coffee","Specialty coffee roastery","Tell the roastery story and generate wholesale enquiries.","Cafes, restaurants and specialty coffee customers","craft-led, informed, unpretentious","#38251b","#e2a14a","#eee5d8","#2d211b","editorial","roastery journal, tactile, warm",["Domov","Kave","Izvor","Praženje","Wholesale","Kontakt"],"Coffee with a traceable point of view.","Small-batch roasting, clear sourcing and repeat quality.","Talk wholesale","roaster, beans and production details","No generic cafe template."),
    ("Kinetik","Kinetik Studio","Creative production studio","Show creative work and convert brand enquiries.","Brand teams, agencies and cultural organisations","bold, concise, visually literate","#ef3e23","#f4ff6a","#f3f0e8","#111111","modern","creative brutalism, graphic, high-energy",["Domov","Delo","Storitve","Studio","Journal","Kontakt"],"Make the work hard to ignore.","Creative direction, design and production with enough structure to move fast.","See the work","campaign crops and studio process","Bold composition, no generic glassmorphism."),
    ("Harbor Finance","Harbor Finance","SME finance advisory","Explain fractional finance support and generate discovery calls.","SME founders and managing directors","clear, commercial, steady","#17324d","#7eb6a1","#f2f4f1","#17212b","classic","financial editorial, credible, calm",["Domov","Storitve","Situacije","Pristop","O nas","Kontakt"],"Finance that helps you decide earlier.","Practical finance leadership for growing businesses.","Book a discovery call","business context and real working sessions","No fake charts or invented ROI figures."),
]

@dataclass
class Result:
    index: int
    project_id: str
    name: str
    submitted_at: str
    status: str = ""
    repo_name: str = ""
    queue_wait_s: float | None = None
    execution_s: float | None = None
    total_s: float | None = None
    visual_score: float | None = None
    deterministic_score: float | None = None
    browser_advisory_score: float | None = None
    aesthetic_score: float | None = None
    aesthetic_penalty: float | None = None
    critical: int = 0
    high: int = 0
    medium: int = 0
    repairs: int = 0
    originality_score: float | None = None
    nearest_similarity: float | None = None
    brief_coverage_score: float | None = None
    motif: str = ""
    composition: str = ""
    quality_gate_passed: bool | None = None
    benchmark_mode: bool = False
    repository_ready: bool | None = None
    payment_required: bool | None = None
    public_live: bool | None = None
    public_url: str = ""
    error: str = ""
    issue_codes: dict[str, int] = field(default_factory=dict)
    severe_codes: dict[str, int] = field(default_factory=dict)

def now() -> datetime:
    return datetime.now(timezone.utc)

def iso(value: datetime) -> str:
    return value.isoformat()

def dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except Exception:
        return None

def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs=sorted(values)
    if len(xs)==1:
        return xs[0]
    r=(len(xs)-1)*p
    a,b=math.floor(r),math.ceil(r)
    return xs[a] if a==b else xs[a]+(xs[b]-xs[a])*(r-a)

def slug(text: str) -> str:
    text=text.lower().replace("č","c").replace("š","s").replace("ž","z")
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-")

def expand(count: int) -> list[tuple]:
    out=[]
    for i in range(count):
        row=list(BRIEFS[i % len(BRIEFS)])
        cycle=i // len(BRIEFS)
        if cycle:
            row[0]=f"{row[0]} Test {cycle+1}"
            row[1]=f"{row[1]} Batch {cycle+1}"
            row[-1]=str(row[-1])+f" Batch variation {cycle+1}: vary composition."
        out.append(tuple(row))
    return out

def payload(row: tuple, *, benchmark_mode: bool = True) -> dict[str,Any]:
    name,org,programme,goal,audience,tone,primary,secondary,bg,text,font,mood,pages,hero,subtitle,cta,images,req=row
    page_rows=[]
    for i,title in enumerate(pages):
        page_rows.append({"slug":"index" if i==0 else slug(title),"title":title,"purpose":f"{title} page for {goal.lower()}"})
    package="Start" if len(page_rows)<=3 else "Standard" if len(page_rows)<=6 else "Premium"
    return {
        "name":name,"organization":org,"package":package,"programme":programme,"language":"en",
        "goal":goal,"audience":audience,"tone":tone,
        "brand":{"primary_color":primary,"secondary_color":secondary,"background_color":bg,"text_color":text,"font_style":font,"mood":mood},
        "pages":page_rows,"hero_title":hero,"hero_subtitle":subtitle,"cta_text":cta,
        "contact_email":None,"image_direction":images,"custom_requirements":req,"defer_build":False,
        "benchmark_mode": benchmark_mode,
    }

class Api:
    def __init__(self, base: str):
        self.base=base.rstrip("/")
        self.client=httpx.Client(timeout=45)
        self.token=""
    def close(self): self.client.close()
    def headers(self): return {"Authorization":f"Bearer {self.token}"} if self.token else {}
    @staticmethod
    def _checked(r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            detail=""
            try:
                payload=r.json()
                detail=json.dumps(payload,ensure_ascii=False)
            except Exception:
                detail=(r.text or "").strip()
            raise RuntimeError(f"API {r.request.method} {r.request.url.path} failed with HTTP {r.status_code}: {detail[:1200]}")
        return r
    def get(self,path):
        r=self.client.get(self.base+path,headers=self.headers()); self._checked(r); return r.json()
    def post(self,path,data):
        r=self.client.post(self.base+path,headers={**self.headers(),"Content-Type":"application/json"},json=data); self._checked(r); return r.json()
    def register(self,email,password):
        r=self.client.post(self.base+"/auth/register",json={"email":email,"password":password}); self._checked(r); self.token=r.json()["token"]
    def login(self,email,password):
        r=self.client.post(self.base+"/auth/login",json={"email":email,"password":password}); self._checked(r); self.token=r.json()["token"]

def ro_db(path: Path):
    con=sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True,timeout=15)
    con.row_factory=sqlite3.Row
    return con

def cleanup_old_loadtests(path: Path) -> dict[str,int]:
    """Delete only local load-test rows so a new benchmark starts with an empty test queue."""
    if not path.exists():
        return {"users":0,"projects":0,"jobs":0}
    con=sqlite3.connect(path,timeout=20)
    con.row_factory=sqlite3.Row
    try:
        users=con.execute(
            "SELECT id FROM users WHERE lower(email) LIKE 'pv.loadtest.%@gmail.com'"
        ).fetchall()
        user_ids=[str(row["id"]) for row in users]
        if not user_ids:
            return {"users":0,"projects":0,"jobs":0}
        placeholders=",".join("?" for _ in user_ids)
        projects=con.execute(
            f"SELECT id FROM projects WHERE user_id IN ({placeholders})",
            user_ids,
        ).fetchall()
        project_ids=[str(row["id"]) for row in projects]
        jobs=0
        if project_ids:
            pp=",".join("?" for _ in project_ids)
            for table in ("production_jobs","agent_supervisor_events","agent_supervisor_state","project_lifecycle"):
                try:
                    cur=con.execute(f"DELETE FROM {table} WHERE project_id IN ({pp})",project_ids)
                    if table=="production_jobs":
                        jobs=int(cur.rowcount or 0)
                except sqlite3.OperationalError:
                    pass
            con.execute(f"DELETE FROM projects WHERE id IN ({pp})",project_ids)
        con.execute(f"DELETE FROM users WHERE id IN ({placeholders})",user_ids)
        con.commit()
        return {"users":len(user_ids),"projects":len(project_ids),"jobs":jobs}
    finally:
        con.close()

def queue_metrics(path: Path, project_id: str) -> dict[str,Any]:
    if not path.exists(): return {}
    try:
        with ro_db(path) as con:
            r=con.execute("SELECT * FROM production_jobs WHERE project_id=?",(project_id,)).fetchone()
        if not r: return {}
        enq,start,finish=dt(r["enqueued_at"]),dt(r["started_at"]),dt(r["finished_at"])
        return {
            "queue_wait_s":(start-enq).total_seconds() if start and enq else None,
            "execution_s":(finish-start).total_seconds() if finish and start else None,
            "attempts":int(r["attempts"] or 0),
        }
    except Exception:
        return {}

def model_metrics(path: Path, since: datetime) -> dict[str,Any]:
    if not path.exists(): return {}
    try:
        with ro_db(path) as con:
            rows=con.execute("SELECT provider,model,status,latency_ms FROM agent_model_runs WHERE created_at>=?",(iso(since),)).fetchall()
        ok=[float(r["latency_ms"] or 0) for r in rows if r["status"]=="ok"]
        by=defaultdict(list); failures=Counter()
        for r in rows:
            key=f"{r['provider']}:{r['model']}"
            if r["status"]=="ok": by[key].append(float(r["latency_ms"] or 0))
            else: failures[key]+=1
        return {
            "calls":len(rows),"successes":len(ok),"failures":sum(failures.values()),
            "avg_latency_ms":round(statistics.mean(ok),1) if ok else None,
            "p50_latency_ms":round(pct(ok,.5),1) if ok else None,
            "p95_latency_ms":round(pct(ok,.95),1) if ok else None,
            "models":{k:{"successes":len(v),"failures":failures[k],"avg_latency_ms":round(statistics.mean(v),1) if v else None,"p95_latency_ms":round(pct(v,.95),1) if v else None} for k,v in by.items()},
        }
    except Exception as exc:
        return {"error":str(exc)}

def hydrate(r: Result, project: dict[str,Any], db: Path, submitted: datetime, at: datetime):
    r.status=str(project.get("status") or "")
    r.repo_name=str(project.get("repo_name") or "")
    # Preserve the timestamp of the first observed terminal state. The final
    # snapshot must not replace every project duration with full-test elapsed time.
    if r.total_s is None:
        r.total_s=round((at-submitted).total_seconds(),2)
    audit=project.get("last_audit") or {}
    visual=audit.get("visual_qa") if isinstance(audit.get("visual_qa"),dict) else {}
    r.visual_score=visual.get("score")
    r.deterministic_score=visual.get("deterministic_score", visual.get("score"))
    r.browser_advisory_score=visual.get("browser_advisory_score")
    r.aesthetic_score=visual.get("aesthetic_score")
    r.aesthetic_penalty=visual.get("aesthetic_penalty")
    issues=audit.get("issues") or []
    sev=Counter(str(x.get("severity") or "").lower() for x in issues if isinstance(x,dict))
    r.critical,r.high,r.medium=sev["critical"],sev["high"],sev["medium"]
    r.issue_codes=dict(sorted(Counter(str(x.get("code") or "UNKNOWN") for x in issues if isinstance(x,dict)).items()))
    r.severe_codes=dict(sorted(Counter(str(x.get("code") or "UNKNOWN") for x in issues if isinstance(x,dict) and str(x.get("severity") or "").lower() in {"critical","high"}).items()))
    r.repairs=int(project.get("auto_fix_attempts") or 0)
    originality=audit.get("originality") if isinstance(audit.get("originality"),dict) else {}
    r.originality_score=originality.get("score")
    r.nearest_similarity=originality.get("nearest_similarity")
    coverage=audit.get("brief_coverage") if isinstance(audit.get("brief_coverage"),dict) else {}
    r.brief_coverage_score=coverage.get("score")
    r.motif=str(originality.get("motif") or "")
    r.composition=str(originality.get("composition") or "")
    r.quality_gate_passed=audit.get("quality_gate_passed") if "quality_gate_passed" in audit else None
    r.benchmark_mode=bool(audit.get("benchmark_mode"))
    r.repository_ready=audit.get("repository_ready") if "repository_ready" in audit else None
    r.payment_required=audit.get("payment_required") if "payment_required" in audit else None
    r.public_live=audit.get("public_live") if "public_live" in audit else None
    r.public_url=str(audit.get("public_url") or "")
    qm=queue_metrics(db,r.project_id)
    r.queue_wait_s=qm.get("queue_wait_s")
    r.execution_s=qm.get("execution_s")

def summary(results: list[Result], started: datetime, finished: datetime, model: dict[str,Any]) -> dict[str,Any]:
    elapsed=max(.001,(finished-started).total_seconds())
    totals=[r.total_s for r in results if r.total_s is not None]
    waits=[r.queue_wait_s for r in results if r.queue_wait_s is not None]
    execs=[r.execution_s for r in results if r.execution_s is not None]
    visuals=[float(r.visual_score) for r in results if r.visual_score is not None]
    deterministic_scores=[float(r.deterministic_score) for r in results if r.deterministic_score is not None]
    browser_advisory_scores=[float(r.browser_advisory_score) for r in results if r.browser_advisory_score is not None]
    aesthetic_scores=[float(r.aesthetic_score) for r in results if r.aesthetic_score is not None]
    aesthetic_penalties=[float(r.aesthetic_penalty) for r in results if r.aesthetic_penalty is not None]
    sims=[float(r.nearest_similarity) for r in results if r.nearest_similarity is not None]
    coverages=[float(r.brief_coverage_score) for r in results if r.brief_coverage_score is not None]
    quality=[r for r in results if (r.visual_score or 0)>=90 and r.critical==0 and r.high==0]
    terminal=[r for r in results if r.status in FINAL_STATES]
    blockers=Counter(code for r in results for code in r.severe_codes)
    blocker_occurrences=Counter()
    for r in results:
        blocker_occurrences.update(r.severe_codes)
    return {
        "started_at":iso(started),"finished_at":iso(finished),"elapsed_s":round(elapsed,2),"projects":len(results),
        "terminal_projects":len(terminal),"incomplete_projects":len(results)-len(terminal),
        "severe_codes_by_project":dict(blockers.most_common()),
        "severe_code_occurrences":dict(blocker_occurrences.most_common()),
        "ready":sum(r.status=="ready" for r in results),"needs_review":sum(r.status=="needs_review" for r in results),
        "failed":sum(r.status=="failed" for r in results),"ready_for_payment":sum(r.status=="ready_for_payment" for r in results),
        "quality_pass_90":len(quality),"quality_pass_rate":round(len(quality)/max(1,len(results)),4),
        "build_ready":sum((r.quality_gate_passed is True) or (r.repository_ready is True) for r in results),
        "build_ready_rate":round(sum((r.quality_gate_passed is True) or (r.repository_ready is True) for r in results)/max(1,len(results)),4),
        "repository_ready":sum(r.repository_ready is True for r in results),
        "delivery_ready_rate":round(sum(r.repository_ready is True for r in results)/max(1,len(results)),4),
        "public_live":sum(r.public_live is True for r in results),
        "deployment_success_rate":round(sum(r.public_live is True for r in results)/max(1,len(results)),4),
        "throughput_sites_per_hour":round(len(terminal)/elapsed*3600,3),
        "ready_throughput_sites_per_hour":round(sum(r.status=="ready" for r in results)/elapsed*3600,3),
        "total_time_s":{"avg":round(statistics.mean(totals),2) if totals else None,"p50":round(pct(totals,.5),2) if totals else None,"p95":round(pct(totals,.95),2) if totals else None},
        "queue_wait_s":{"avg":round(statistics.mean(waits),2) if waits else None,"p50":round(pct(waits,.5),2) if waits else None,"p95":round(pct(waits,.95),2) if waits else None},
        "execution_s":{"avg":round(statistics.mean(execs),2) if execs else None,"p50":round(pct(execs,.5),2) if execs else None,"p95":round(pct(execs,.95),2) if execs else None},
        "visual":{
            "avg":round(statistics.mean(visuals),2) if visuals else None,
            "min":round(min(visuals),2) if visuals else None,
            "deterministic_avg":round(statistics.mean(deterministic_scores),2) if deterministic_scores else None,
            "deterministic_min":round(min(deterministic_scores),2) if deterministic_scores else None,
            "browser_advisory_avg":round(statistics.mean(browser_advisory_scores),2) if browser_advisory_scores else None,
            "browser_advisory_min":round(min(browser_advisory_scores),2) if browser_advisory_scores else None,
            "aesthetic_avg":round(statistics.mean(aesthetic_scores),2) if aesthetic_scores else None,
            "aesthetic_min":round(min(aesthetic_scores),2) if aesthetic_scores else None,
            "aesthetic_penalty_avg":round(statistics.mean(aesthetic_penalties),2) if aesthetic_penalties else None,
            "aesthetic_penalty_max":round(max(aesthetic_penalties),2) if aesthetic_penalties else None,
        },
        "repair_rate":round(sum(r.repairs>0 for r in results)/max(1,len(results)),4),
        "avg_repairs":round(statistics.mean([r.repairs for r in results]),3) if results else 0,
        "qa_failure_rate":round(sum((r.critical+r.high)>0 for r in results)/max(1,len(results)),4),
        "originality":{"avg_nearest_similarity":round(statistics.mean(sims),4) if sims else None,"max_nearest_similarity":round(max(sims),4) if sims else None,"near_duplicates":sum(x>=.93 for x in sims),"warnings":sum(.82<=x<.93 for x in sims)},
        "brief_coverage":{"avg":round(statistics.mean(coverages),4) if coverages else None,"min":round(min(coverages),4) if coverages else None,"below_full":sum(x<1.0 for x in coverages)},
        "motifs":dict(Counter(r.motif for r in results if r.motif)),
        "compositions":dict(Counter(r.composition for r in results if r.composition)),
        "model":model,
    }

def write_reports(folder: Path, results: list[Result], stats: dict[str,Any]):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"summary.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"projects.json").write_text(json.dumps([asdict(r) for r in results],ensure_ascii=False,indent=2),encoding="utf-8")
    fields=list(Result.__dataclass_fields__)
    with (folder/"projects.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in results: w.writerow(asdict(r))
    lines=[
        "# Production Load Test","",
        f"- Projects: **{stats['projects']}**",
        f"- Ready: **{stats['ready']}**",
        f"- Failed: **{stats['failed']}**",
        f"- Quality pass >=90: **{stats['quality_pass_rate']*100:.1f}%**",
        f"- Local build/quality ready: **{stats['build_ready_rate']*100:.1f}%**",
        f"- GitHub delivery ready: **{stats['delivery_ready_rate']*100:.1f}%**",
        f"- Public live (may be payment-gated): **{stats['deployment_success_rate']*100:.1f}%**",
        f"- Terminal throughput (includes needs_review): **{stats['throughput_sites_per_hour']:.2f} sites/hour**",
        f"- Ready throughput: **{stats['ready_throughput_sites_per_hour']:.2f} sites/hour**",
        f"- Incomplete at timeout: **{stats['incomplete_projects']}**",
        f"- QA failure rate: **{stats['qa_failure_rate']*100:.1f}%**",
        f"- Repair rate: **{stats['repair_rate']*100:.1f}%**","",
        "## Timing","",
        f"- Total p50 / p95: {stats['total_time_s']['p50']} / {stats['total_time_s']['p95']} s",
        f"- Queue p50 / p95: {stats['queue_wait_s']['p50']} / {stats['queue_wait_s']['p95']} s",
        f"- Execution p50 / p95: {stats['execution_s']['p50']} / {stats['execution_s']['p95']} s","",
        "## Quality and originality","",
        f"- Release visual avg / min: {stats['visual']['avg']} / {stats['visual']['min']}",
        f"- Release browser avg / min: {stats['visual']['deterministic_avg']} / {stats['visual']['deterministic_min']}",
        f"- Raw browser advisory avg / min: {stats['visual']['browser_advisory_avg']} / {stats['visual']['browser_advisory_min']}",
        f"- Aesthetic vision avg / min: {stats['visual']['aesthetic_avg']} / {stats['visual']['aesthetic_min']}",
        f"- Aesthetic penalty avg / max: {stats['visual']['aesthetic_penalty_avg']} / {stats['visual']['aesthetic_penalty_max']}",
        f"- Max nearest similarity: {stats['originality']['max_nearest_similarity']}",
        f"- Near duplicates: {stats['originality']['near_duplicates']}",
        f"- Brief coverage avg / min: {stats['brief_coverage']['avg']} / {stats['brief_coverage']['min']}",
        f"- Brief coverage below 100%: {stats['brief_coverage']['below_full']}",
        f"- Motifs: {json.dumps(stats['motifs'],ensure_ascii=False)}",
        f"- Compositions: {json.dumps(stats['compositions'],ensure_ascii=False)}","",
        "## Blocking QA codes (affected projects)","",
        *(f"- `{code}`: {count} project(s)" for code,count in stats["severe_codes_by_project"].items()),
        *([] if stats["severe_codes_by_project"] else ["- No critical/high issue codes recorded."]),
        "",
        "## Per project","",
        "| # | Project | Status | Total s | Queue s | Exec s | Release | Browser | Browser advisory | Aesthetic | Penalty | Repairs | Motif | Composition | Similarity | Brief | Repo ready | Live | Blockers |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.index} | {r.name} | {r.status} | {r.total_s or ''} | {r.queue_wait_s if r.queue_wait_s is not None else ''} | {r.execution_s if r.execution_s is not None else ''} | {r.visual_score if r.visual_score is not None else ''} | {r.deterministic_score if r.deterministic_score is not None else ''} | {r.browser_advisory_score if r.browser_advisory_score is not None else ''} | {r.aesthetic_score if r.aesthetic_score is not None else ''} | {r.aesthetic_penalty if r.aesthetic_penalty is not None else ''} | {r.repairs} | {r.motif} | {r.composition} | {r.nearest_similarity if r.nearest_similarity is not None else ''} | {r.brief_coverage_score if r.brief_coverage_score is not None else ''} | {'yes' if r.repository_ready else 'no'} | {'yes' if r.public_live else 'no'} | {', '.join(r.severe_codes) or '-'} |")
    (folder/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--api",default=os.getenv("PV_API_URL","http://127.0.0.1:8000"))
    p.add_argument("--count",type=int,default=10)
    p.add_argument("--poll-seconds",type=float,default=3)
    p.add_argument("--timeout-minutes",type=float,default=120)
    p.add_argument("--db",default=os.getenv("DB_PATH",str(DEFAULT_DB)))
    p.add_argument("--email",default=os.getenv("PV_LOADTEST_EMAIL",""))
    p.add_argument("--password",default=os.getenv("PV_LOADTEST_PASSWORD",""))
    p.add_argument("--output",default="")
    p.add_argument("--submit-delay",type=float,default=.12)
    p.add_argument("--keep-old-loadtests",action="store_true",help="Do not clear prior local pv.loadtest.* rows before this run")
    p.add_argument("--with-delivery",action="store_true",help="Also create GitHub repositories during the benchmark. Default is local benchmark mode.")
    a=p.parse_args()
    if not 1<=a.count<=100: p.error("--count must be 1..100")

    db=Path(a.db).resolve()
    started=now(); stamp=started.strftime("%Y%m%d-%H%M%S")
    folder=Path(a.output).resolve() if a.output else REPORT_ROOT/stamp
    if db.exists() and not a.keep_old_loadtests:
        cleaned=cleanup_old_loadtests(db)
        if any(cleaned.values()):
            print(f"[CLEAN] removed old local load-test state: {cleaned}")

    api=Api(a.api)
    try:
        health=api.get("/health")
        if not health.get("ok"): raise RuntimeError("API health is not ok")
        if a.email and a.password:
            api.login(a.email,a.password); account=a.email
        else:
            # Pydantic EmailStr/email-validator intentionally rejects special-use
            # domains such as .test/.local. Registration is local-only, but the
            # address still has to pass normal email syntax validation.
            account=f"pv.loadtest.{stamp.lower()}@gmail.com"
            api.register(account,"PV!"+secrets.token_urlsafe(18))
        print(f"API={a.api} account={account} projects={a.count} db_metrics={db.exists()} benchmark_mode={not a.with_delivery}")

        results=[]; submitted={}
        for i,row in enumerate(expand(a.count),1):
            at=now(); data=api.post("/projects",payload(row, benchmark_mode=not a.with_delivery)); pid=str(data["id"])
            submitted[pid]=at; results.append(Result(i,pid,str(row[0]),iso(at)))
            print(f"[SUBMIT {i:02d}/{a.count}] {row[0]} -> {pid[:8]}")
            time.sleep(max(0,a.submit_delay))

        deadline=time.monotonic()+a.timeout_minutes*60; last=0.0
        while True:
            done=0; states=Counter(); active_codes=Counter(); active_stages=Counter()
            for r in results:
                if r.status in FINAL_STATES:
                    done+=1; states[r.status]+=1; continue
                try: project=api.get(f"/projects/{r.project_id}")
                except Exception as exc:
                    r.error=str(exc)[:300]; continue
                state=str(project.get("status") or ""); states[state]+=1
                audit=project.get("last_audit") or {}
                stage=str(audit.get("build_stage") or "")
                if stage:
                    active_stages[stage]+=1
                for item in (audit.get("issues") or [])[:20]:
                    if isinstance(item,dict) and item.get("severity") in {"critical","high"}:
                        active_codes[str(item.get("code") or "UNKNOWN")]+=1
                if state in FINAL_STATES:
                    hydrate(r,project,db,submitted[r.project_id],now()); done+=1
                    print(f"[DONE {done:02d}/{a.count}] {r.name}: {r.status} visual={r.visual_score} motif={r.motif or '-'} total={r.total_s:.0f}s")
            if done==len(results): break
            if time.monotonic()>=deadline:
                print("TIMEOUT: collecting current state",file=sys.stderr); break
            if time.monotonic()-last>=15:
                issue_text=dict(active_codes.most_common(8))
                stage_text=dict(active_stages)
                try:
                    q=api.get("/agent/production-queue")
                    print(f"[PROGRESS] final={done}/{len(results)} workers={q.get('workers_alive',0)}/{q.get('workers',0)} queue={q.get('states')} project_states={dict(states)} stages={stage_text} severe_codes={issue_text}")
                except Exception:
                    print(f"[PROGRESS] final={done}/{len(results)} project_states={dict(states)} stages={stage_text} severe_codes={issue_text}")
                last=time.monotonic()
            time.sleep(max(.5,a.poll_seconds))

        finished=now()
        for r in results:
            try: hydrate(r,api.get(f"/projects/{r.project_id}"),db,submitted[r.project_id],finished)
            except Exception as exc:
                if not r.error: r.error=str(exc)[:300]
        stats=summary(results,started,finished,model_metrics(db,started))
        write_reports(folder,results,stats)
        print("\n=== PRODUCTION LOAD TEST ===")
        print(f"results={folder}")
        print(f"throughput={stats['throughput_sites_per_hour']} terminal sites/hour; ready_throughput={stats['ready_throughput_sites_per_hour']} sites/hour")
        print(f"top_qa_blockers={dict(list(stats['severe_codes_by_project'].items())[:10])}")
        if stats["incomplete_projects"]:
            print(f"incomplete_projects={stats['incomplete_projects']} (timeout or unobserved terminal state)")
        print(f"quality_pass_90={stats['quality_pass_rate']*100:.1f}% build_ready={stats['build_ready_rate']*100:.1f}% delivery_ready={stats['delivery_ready_rate']*100:.1f}% public_live={stats['deployment_success_rate']*100:.1f}%")
        print(f"qa_failure={stats['qa_failure_rate']*100:.1f}% repairs={stats['repair_rate']*100:.1f}%")
        print(f"visual_avg_min={stats['visual']['avg']}/{stats['visual']['min']} browser_avg_min={stats['visual']['deterministic_avg']}/{stats['visual']['deterministic_min']} browser_advisory_avg_min={stats['visual']['browser_advisory_avg']}/{stats['visual']['browser_advisory_min']} aesthetic_avg_min={stats['visual']['aesthetic_avg']}/{stats['visual']['aesthetic_min']} max_similarity={stats['originality']['max_nearest_similarity']} brief_avg_min={stats['brief_coverage']['avg']}/{stats['brief_coverage']['min']}")
        hard_fail=stats["incomplete_projects"]>0 or stats["failed"]>0 or stats["quality_pass_rate"]<.95 or stats["qa_failure_rate"]>.05 or stats["originality"]["near_duplicates"]>0 or (stats["brief_coverage"]["min"] is not None and stats["brief_coverage"]["min"]<1.0)
        return 2 if hard_fail else 0
    finally:
        api.close()

if __name__=="__main__":
    raise SystemExit(main())
