# Project Handoff README

This file is for the next Copilot/session so you do not need to re-explain the project.

## 1) Project Summary

- Site type: static HTML/CSS/JS project
- Main repo: lomopototo1978-cell/lomopototo1978-cell.github.io
- Branch in use: main
- Current AI/chat page branding: BaobabGpt
- Auth mode: Supabase cloud auth is primary, localStorage fallback exists in code

## 2) Key Files

- index.html: login page (Supabase login + remember session + typing title animation)
- register.html: signup page (Supabase sign up in cloud mode)
- dashboard.html: protected user dashboard
- stargenzimbabwe.html: BaobabGpt chat UI + local knowledge engine
- auth-config.js: runtime config values (Supabase + optional EmailJS)
- model-data.json: model/knowledge data file in repo
- styles.css + script.js: shared site styles and JS for non-chat pages

## 3) Important Runtime Keys (Current Values)

From auth-config.js:

- SUPABASE_URL
  - https://xnwagtojdworipbrfaeu.supabase.co
- SUPABASE_ANON_KEY
  - eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhud2FndG9qZHdvcmlwYnJmYWV1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxMzI5ODgsImV4cCI6MjA4ODcwODk4OH0.p2Y5CglEHcrIXy0XWTnslQxTdvO-qCCAH-3uw2PAO5k
- EMAILJS_PUBLIC_KEY
  - empty
- EMAILJS_SERVICE_ID
  - empty
- EMAILJS_TEMPLATE_ID
  - empty

Note:
- Supabase anon key is designed for client use, but still treat it as sensitive config and rotate if leaked beyond expected use.

## 4) Auth Architecture and Behaviors

### Supabase client init

All auth pages use:
- window.supabase CDN library
- local variable name sbClient (NOT supabase)

Reason:
- Previous critical bug was a name collision with UMD global var supabase.
- Always keep local variable as sbClient to avoid breaking all page scripts.

### Session storage keys

- USER_KEY = mvumi_users_v1
- SESSION_KEY = mvumi_session_v1
- REMEMBER_PREF_KEY = mvumi_remember_pref_v1 (login remember checkbox)
- PENDING_KEY = mvumi_pending_signup_v1 (legacy OTP/local mode flow)

### Flow notes

- index.html:
  - If Supabase configured, checks cloud session first.
  - If no cloud session, clears stale local session to avoid redirect loops.
- register.html:
  - In Supabase mode, uses direct signUp (no OTP dependency).
- dashboard.html:
  - Uses Supabase session first.
  - If Supabase configured but no cloud session, clears local session and redirects to login.

## 5) Branding Changes Completed

- Ask Star renamed to BaobabGpt in stargenzimbabwe.html text/UI.
- Dashboard app card text now shows Baobab/Gpt.
- Chat logic still on same page path: stargenzimbabwe.html.

## 6) Hosting and Deployment

### GitHub Pages

- Repo pushes to main still work as normal.
- Historical domain used: mvumi.me.

### Azure Web App (active)

- Subscription: Azure for Students (c61c3d8d-59d5-4a80-b9e1-14c6cd05109f)
- Resource group: mvumi-rg
- App Service plan: mvumi-plan (Linux Free tier)
- Web app name: mvumi-site
- Default host: mvumi-site.azurewebsites.net
- Region: South Africa North

### Deploy command used successfully

From project root:

1) Create zip:
- Compress-Archive -Path .\* -DestinationPath "$env:TEMP\mvumi-deploy.zip" -Force

2) Deploy:
- $az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
- & $az webapp deploy --name mvumi-site --resource-group mvumi-rg --src-path "$env:TEMP\mvumi-deploy.zip" --type zip

## 7) Domain and SSL Notes

- Custom hostnames bound in Azure:
  - mvumi.me
  - www.mvumi.me
- TXT verification value used (asuid):
  - 65A275D2E67CE06DBF9C80C2B4AC450D1F771DEF635E720830C01DC8D0B84612

Important SSL constraint:
- Azure managed cert is not supported on Free tier App Service.
- SSL is handled via Cloudflare proxy (free Universal SSL).

### Current Domain Status (as of March 11, 2026)

**Setup completed:**
- Cloudflare Universal SSL certificate: Active (covers mvumi.me + *.mvumi.me, expires Jun 7 2026)
- Cloudflare SSL/TLS mode: Full
- Both CNAMEs in Cloudflare DNS set to Proxied (orange cloud):
  - mvumi.me → mvumi-site.azurewebsites.net (Proxied)
  - www.mvumi.me → mvumi-site.azurewebsites.net (Proxied)
- Namecheap nameservers changed to Custom DNS:
  - hal.ns.cloudflare.com
  - molly.ns.cloudflare.com

**Waiting on:**
- Nameserver propagation from Namecheap BasicDNS → Cloudflare
- Currently still resolving to 162.0.212.2 (old Supersonic CDN)
- Once nameservers propagate (can take up to a few hours), mvumi.me will resolve to Cloudflare IPs and the site will be live over HTTPS

**How to verify when propagation is done:**
```powershell
Resolve-DnsName mvumi.me -Type NS -Server 1.1.1.1
# Should show: hal.ns.cloudflare.com + molly.ns.cloudflare.com

Invoke-WebRequest -Uri "https://mvumi.me" -UseBasicParsing -TimeoutSec 20
# Should return: StatusCode 200
```

**If still 404 after nameservers switch to Cloudflare:**
- Check DNS → both CNAMEs still showing orange cloud (Proxied)
- Check SSL/TLS Overview → still showing Full
- The Azure hostname bindings are already verified — no Azure changes needed

## 8) Known Gotchas

1. Do not rename sbClient back to supabase.
2. Free App Service tier has SSL limitations for custom domains.
3. If login/register suddenly reloads form with no JS behavior, check browser console first for script parse errors.
4. If custom domain works on HTTP but not HTTPS, it is usually certificate/proxy propagation, not app code.

## 9) Local PC Environment (Sean's Machine)

| Item | Value |
|---|---|
| OS | Windows |
| Workspace path | `c:\Users\HP\Documents\github site` |
| Python version | 3.12.10 |
| Python executable | `C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe` |
| Azure CLI path | `C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd` |
| Azure subscription | Azure for Students (c61c3d8d-59d5-4a80-b9e1-14c6cd05109f) |
| GitHub repo | lomopototo1978-cell/lomopototo1978-cell.github.io |
| ARIA folder (to create) | `c:\Users\HP\Documents\github site\aria\` |

Note: Python 3.12 is installed. ARIA spec says Python 3.11 but 3.12 will work fine for all listed dependencies.

ARIA venv setup (run once when starting ARIA build):
```powershell
cd "c:\Users\HP\Documents\github site\aria"
C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe -m venv venv
venv\Scripts\activate
pip install azure-cosmos azure-servicebus httpx playwright duckduckgo-search nltk scikit-learn xgboost networkx numpy pandas python-dotenv
playwright install chromium
```

## 9b) Fast Troubleshooting Commands

### Check latest commits
- git log --oneline -5

### Check Azure app status
- $az = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
- & $az webapp show --name mvumi-site --resource-group mvumi-rg --query "{state:state,url:defaultHostName}" -o table

### Check hostname bindings
- & $az webapp config hostname list --webapp-name mvumi-site --resource-group mvumi-rg -o table

### Quick DNS check (PowerShell)
- Resolve-DnsName mvumi.me
- Resolve-DnsName www.mvumi.me

## 10) If Next Copilot Needs to Continue Work

Suggested first checks:

1. Read auth-config.js for current runtime keys.
2. Verify Supabase session behavior on index/register/dashboard.
3. Verify domain SSL status at mvumi.me and www.mvumi.me.
4. If UI changes requested for BaobabGpt, edit stargenzimbabwe.html only unless shared assets are needed.

## 11) Last Important Commits

- 903831a Rename Ask Star branding to BaobabGpt
- 43ec72c Redesign Ask Star UI to modern centered chat layout
- bda7295 Fix supabase variable collision by using sbClient

---

# ARIA — Autonomous Research & Intelligence Architecture

## What ARIA Is

ARIA is a Python-based autonomous multi-agent AI system that:
- Continuously researches the internet (Google + DuckDuckGo)
- Processes every piece of content through 10 dimensions of thinking
- Validates knowledge using ML models before storing
- Trains BaobabGPT to get smarter every day
- Runs 24/7 on Azure even when Sean's PC is off

ARIA lives in: `c:\Users\HP\Documents\github site\aria\`

---

## ARIA Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| Database | Azure Cosmos DB (NoSQL) |
| Message Queue | Azure Service Bus |
| Hosting | Azure Functions (serverless) |
| LLM Teacher | Qwen 2.5 9B via Azure AI Model Catalog (serverless API) |
| Primary Search | Google Custom Search API |
| Backup Search | DuckDuckGo (duckduckgo-search library) |
| HTTP | httpx (async) |
| Scraping | playwright (async) |
| ML | scikit-learn, xgboost |
| NLP | nltk |
| Knowledge Graph | networkx |
| Config | python-dotenv |

---

## ARIA .env File (fill all values before running)

```
COSMOS_ENDPOINT=your_cosmos_endpoint
COSMOS_KEY=your_cosmos_primary_key
COSMOS_DB=aria_db
SERVICE_BUS_CONN=your_service_bus_connection_string
QWEN_ENDPOINT=your_azure_qwen_endpoint
QWEN_API_KEY=your_azure_qwen_api_key
GOOGLE_API_KEY=AIzaSyCW5Uyg59ir9qbZwH4Q68H-1f1o_XwBIwU
GOOGLE_CSE_ID=your_google_cse_id
ENVIRONMENT=development
```

Note: `.env` is gitignored — never committed to GitHub.

---

## How to Call Qwen

Qwen 2.5 9B runs as a serverless API on Azure AI Model Catalog.
Always on 24/7 even when PC is off.

```python
import httpx, os

async def call_qwen(messages: list):
    headers = {
        "Authorization": f"Bearer {os.getenv('QWEN_API_KEY')}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "qwen2.5-9b-instruct",
        "messages": messages,
        "max_tokens": 1000
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            os.getenv("QWEN_ENDPOINT"),
            headers=headers,
            json=body,
            timeout=60.0
        )
        return response.json()
```

Qwen is called ONLY when:
1. Scout is stuck and needs search query guidance
2. Checker flags something for review
3. Teaching ARIA after a mistake
4. Generating training data for BaobabGPT
5. Sending weekly progress reports to Sean

Qwen is NOT the backbone. Internet is ARIA's primary source.

---

## Azure Cosmos DB Structure

Database name: `aria_db`

| Container | Partition Key |
|---|---|
| knowledge_base | /subject/category |
| agent_logs | /agent_name |
| qwen_lessons | /timestamp |
| training_data | /source_knowledge_id |
| aria_reports | /report_type |

Cosmos Account: `aria-cosmos`, Resource Group: `mvumi-rg`, Region: South Africa North

---

## Azure Service Bus

Namespace: `aria-bus`, Resource Group: `mvumi-rg`, Tier: Basic

Queues:
- `research-queue` — topics for Scout to research
- `thinking-queue` — content waiting for ThinkingEngine
- `checker-queue` — processed content waiting for CheckerAgent

---

## ARIA Folder Structure

```
aria/
├── agents/
│   ├── scout_agent.py          ← searches Google + DDG, deduplicates
│   ├── thinking_engine.py      ← 10D analysis via Qwen + RF scoring
│   ├── checker_agent.py        ← 5-layer validation, verdicts
│   ├── memory_agent.py         ← stores to Cosmos, manages knowledge graph
│   ├── adversarial_agent.py    ← fires 500 questions nightly, finds weak spots
│   ├── reporter_agent.py       ← daily/weekly reports + improvement trend
│   └── qwen_interface.py       ← all Qwen API calls
├── ml/
│   ├── bias_detector.py        ← MultinomialNB, bias score 0.0-1.0
│   ├── source_scorer.py        ← RandomForest, source credibility 0.0-1.0
│   ├── knowledge_validator.py  ← KFold(10) consistency checker
│   ├── training_builder.py     ← XGBRanker, ranks training examples
│   └── models/                 ← auto-created, stores .pkl files (gitignored)
├── database/
│   ├── cosmos_client.py        ← async Cosmos DB wrapper
│   └── knowledge_graph.py      ← networkx DiGraph, persisted to .gpickle
├── utils/
│   ├── config.py               ← loads .env, validates all vars
│   ├── text_processor.py       ← nltk clean/extract/fingerprint
│   └── decay_manager.py        ← knowledge expiry rules
├── functions/
│   ├── scout_trigger/          ← Azure Function, runs every 4 hours
│   ├── checker_trigger/        ← Azure Function, runs every 1 hour
│   └── reporter_trigger/       ← Azure Function, runs nightly 23:00 Harare
├── data/                       ← auto-created, training packages (gitignored)
├── tests/
│   └── test_all_agents.py      ← 10 test functions, one per component
├── .env                        ← gitignored, fill from section above
├── .gitignore
├── requirements.txt
└── main.py                     ← ARIA orchestrator, entry point
```

---

## Build Order (one file at a time, test before next)

### Phase 0 — Infrastructure (provision before writing any code)

1. **Azure Cosmos DB**: Portal → Create resource → Cosmos DB → NoSQL API → account `aria-cosmos` in `mvumi-rg` → create `aria_db` database with 5 containers above → copy Endpoint + Primary Key
2. **Azure Service Bus**: Portal → Create resource → Service Bus → Basic → namespace `aria-bus` in `mvumi-rg` → create 3 queues → copy Connection String from Shared Access Policies
3. **Qwen on Azure AI Foundry**: Portal → Azure AI Foundry → Model Catalog → `qwen2.5-9b-instruct` → Deploy as Serverless API → copy Endpoint + API Key
4. **Google CSE**: programmablesearchengine.google.com → New CSE → Search entire web ON → copy cx (Search Engine ID)
5. **Python environment**:
   ```
   cd "c:\Users\HP\Documents\github site\aria"
   python -m venv venv
   venv\Scripts\activate
   pip install azure-cosmos azure-servicebus httpx playwright duckduckgo-search nltk scikit-learn xgboost networkx numpy pandas python-dotenv
   playwright install chromium
   ```

### Phase 1 — Foundation
- File 1: `utils/config.py` — load + validate all env vars
- File 2: `database/cosmos_client.py` — upsert/get/query/delete wrapper
- File 3: `agents/qwen_interface.py` — all 6 async Qwen methods

### Phase 2 — Research Layer
- File 4: `utils/text_processor.py` — nltk clean/extract/fingerprint
- File 5: `ml/bias_detector.py` — MultinomialNB, seed data built-in, save/load pkl
- File 6: `ml/source_scorer.py` — RandomForest, tier list built-in, save/load pkl
- File 7: `agents/scout_agent.py` — SearchManager (Google→DDG fallback), playwright fetch, TF-IDF dedup, K-Means gap detection

### Phase 3 — Thinking & Validation
- File 8: `agents/thinking_engine.py` — 10 dimension prompts, RF depth scorer, PCA redundancy check, retry <7 dimensions
- File 9: `ml/knowledge_validator.py` — KFold consistency + TF-IDF cross-reference
- File 10: `agents/checker_agent.py` — 5 layers, exact verdicts (APPROVED/FLAGGED/REJECTED/INCOMPLETE)

### Phase 4 — Memory
- File 11: `database/knowledge_graph.py` — networkx DiGraph, gpickle persistence, sparse cluster detection
- File 12: `utils/decay_manager.py` — expiry rules (24h/30d/1y/never)
- File 13: `agents/memory_agent.py` — Agglomerative Clustering, PCA dedup, TF-IDF retrieval, auto-link graph

### Phase 5 — Adversarial + Reporting
- File 14: `agents/adversarial_agent.py` — SVM classifier, Decision Tree weakness map, 500-question nightly fire
- File 15: `ml/training_builder.py` — XGBRanker with 6 quality features, saves ranked JSON package
- File 16: `agents/reporter_agent.py` — Linear Regression trend, Thompson Sampling topic selection, daily/weekly reports

### Phase 6 — Orchestration + Azure Functions
- File 17: `main.py` — ARIA orchestrator, `run_research_cycle()`, `run_nightly_cycle()`, `run_retraining_cycle()`
- File 18: `functions/` — 3 Azure Function timer triggers

### Phase 7 — Tests
- File 19: `tests/test_all_agents.py` — 10 tests, one per component

---

## ARIA Checker Verdict Logic

```
if layer 4 (safety) fails → REJECTED immediately
if all 5 layers pass     → APPROVED → Memory Agent
if layers 1-3 partial   → FLAGGED → Qwen reviews
if layer 5 incomplete   → INCOMPLETE → back to ThinkingEngine
```

---

## ARIA Source Tier System

| Tier | Sources | Verify with |
|---|---|---|
| 1 (highest trust) | reuters.com, bbc.com, arxiv.org, pubmed.ncbi.nlm.nih.gov, github.com, theguardian.com, herald.co.zw | 2 sources |
| 2 (trusted) | medium.com, forbes.com, bloomberg.com, aljazeera.com | 3 sources |
| 3 (low trust) | Unknown blogs, forums | 5 sources |

---

## ARIA Knowledge Decay Rules

| Type | Expires after |
|---|---|
| breaking_news | 24 hours |
| economic_data | 30 days |
| scientific_fact | 1 year |
| mathematics | Never |

---

## ARIA ML Performance Targets

| Model | Target |
|---|---|
| Bias Detector (NB) | Precision >90%, Recall >85%, F1 >87% |
| Source Scorer (RF) | Accuracy >88%, False positive <10% |
| Training Ranker (XGB) | Top 10% = best quality, correlation with BaobabGPT improvement >0.75 |
| Knowledge Validator (KFold) | Consistency >85%, Cross-source agreement >80% |

---

## ARIA Nightly Improvement Cycle (23:00 Harare / UTC+2)

1. Compile all new verified knowledge from that day
2. Generate reasoning chains via Qwen
3. Build chain-of-thought examples
4. Adversarial Agent fires 500 questions
5. Identify weak spots from failures
6. Generate targeted training data for weak spots
7. XGBoost ranks all training examples by quality
8. Save ranked training package to `data/training_package_YYYYMMDD.json`
9. Generate nightly report
10. Send report to mvumi.me/admin dashboard

---

## ARIA Important Rules

1. Never remove Qwen — ARIA only outgrows dependence on it
2. ARIA has no self-awareness — it is a powerful tool, not a sentient being
3. Sean is always final authority — critical decisions escalated to mvumi.me/admin
4. Everything is logged — full audit trail, nothing happens silently
5. Safety first — harmful content rejected immediately, no exceptions
6. Free tools only — no paid APIs unless approved by Sean (Azure student credits are the budget)
7. BaobabGPT improvement is the goal — every decision asks "does this make BaobabGPT smarter?"
8. All ML models retrain weekly automatically and are only deployed if they improve on the previous version

---

## Progress Status (as of March 11, 2026)

- [ ] Phase 0: Azure Cosmos DB provisioned
- [ ] Phase 0: Azure Service Bus provisioned
- [ ] Phase 0: Qwen deployed on Azure AI Foundry
- [ ] Phase 0: Google CSE created
- [ ] Phase 0: Python venv + deps installed
- [ ] Phase 1: config.py
- [ ] Phase 1: cosmos_client.py
- [ ] Phase 1: qwen_interface.py
- [ ] Phase 2: text_processor.py
- [ ] Phase 2: bias_detector.py
- [ ] Phase 2: source_scorer.py
- [ ] Phase 2: scout_agent.py
- [ ] Phase 3: thinking_engine.py
- [ ] Phase 3: knowledge_validator.py
- [ ] Phase 3: checker_agent.py
- [ ] Phase 4: knowledge_graph.py
- [ ] Phase 4: decay_manager.py
- [ ] Phase 4: memory_agent.py
- [ ] Phase 5: adversarial_agent.py
- [ ] Phase 5: training_builder.py
- [ ] Phase 5: reporter_agent.py
- [ ] Phase 6: main.py
- [ ] Phase 6: Azure Functions
- [ ] Phase 7: tests/test_all_agents.py

---

End of handoff.
