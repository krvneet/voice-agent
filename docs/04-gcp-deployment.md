# 04 — GCP Deployment

How every component runs in Google Cloud and becomes reachable via a public URL.
Target: a fully cloud-hosted service, no local dependency at demo time.

---

## 1. Topology

| Service | GCP product | Public? | Scaling |
|---|---|---|---|
| Frontend (static HTML/CSS/JS) + `/token` endpoint (FastAPI) | **Cloud Run** | ✅ Public HTTPS URL (handed to client) | 0→N (scale to zero OK) |
| Agent worker (LiveKit + Groq + **in-process Kokoro TTS**) | **Cloud Run** | ❌ Internal (talks *out* to LiveKit Cloud) | `min-instances=1` (warm), 2 vCPU / 2Gi |
| Media transport | **LiveKit Cloud** (external, free tier) | ✅ (managed) | managed |
| Secrets | **Secret Manager** | ❌ | — |
| Logs/metrics | **Cloud Logging / Monitoring** | ❌ | — |
| LLM / STT | **Groq** (fallback: Gemini AI Studio) — external free-tier API | ❌ (API) | managed |

> **2 services only.** Kokoro TTS runs **in-process inside the agent worker**
> (no separate TTS service, no HTTP hop). **No paid GCP AI services** — GCP hosts
> compute/secrets/logging only; LLM+STT are free external APIs; the TTS model is
> open weights baked into the worker image. Satisfies "GCP = hosting only" +
> "free models only".

**Why Cloud Run for the worker (not Cloud Functions):** the LiveKit agent is a
long-lived process that maintains a persistent connection to LiveKit Cloud and
holds per-call state. Cloud Run supports always-on containers with `min-instances=1`;
Functions are request-scoped and unsuitable. GKE is the "scale later" option but
is over-engineered for a POC.

## 2. Public URL & networking

- The **frontend Cloud Run service** provides the public entry point:
  `https://smart-scheduler-web-<hash>-<region>.run.app` (or a custom domain).
- The browser connects to **LiveKit Cloud** over WebRTC using a short-lived JWT
  minted by the frontend's token endpoint.
- The **agent worker needs no inbound public ingress** — it registers *outbound*
  with LiveKit Cloud and receives room dispatch. Its health/metrics server binds
  Cloud Run's `$PORT` so startup probes pass.
- All traffic is TLS by default on Cloud Run and LiveKit Cloud.

## 3. Container images

Two images, built with Cloud Build, stored in **Artifact Registry**:

1. `smart-scheduler-agent` — Python 3.12 slim + `livekit-agents` + plugins
   (`livekit-plugins-groq` for LLM+STT, `-openai` for the Gemini-AI-Studio
   fallback, `-silero`, `-turn-detector`) + `kokoro-onnx` + `onnxruntime` +
   `google-api-python-client` + `google-auth`. The **Kokoro model + voices are
   baked into the image** at build; `espeak-ng` is installed for phonemization.
   Entrypoint: `python agent.py start`.
2. `smart-scheduler-web` — small **FastAPI** app that (a) serves the static
   `index.html` / `style.css` / `app.js` (with the LiveKit JS SDK vendored
   locally, no CDN dependency) and (b) exposes a `/token` endpoint that mints a
   short-lived LiveKit access JWT. This is the public URL handed to the client.

## 4. Configuration & secrets

Stored in **Secret Manager**, mounted as env vars / files on Cloud Run:

| Secret | Used by |
|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | worker + web |
| `GROQ_API_KEY` | worker (LLM + STT) |
| `GEMINI_API_KEY` (AI Studio, fallback LLM) | worker |
| `GCAL_CALENDAR_ID` | worker |
| `gcal-sa-json` (Calendar SA key, **mounted as a file**) | worker |

Plus non-secret env vars on the worker: `GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcal-sa.json`,
`AGENT_TIMEZONE`, `LLM_PROVIDER`.

Grant the worker's Cloud Run **service account** (`scheduler-run`) roles:
`roles/secretmanager.secretAccessor`, `roles/logging.logWriter`. **No `aiplatform`
role** — no Vertex/paid AI is used. The **Calendar** access uses a *separate*
service account (`scheduler-cal`) whose key is mounted from the `gcal-sa-json`
secret and whose email is shared into the demo calendar (see
[05-calendar-integration.md](05-calendar-integration.md)).

## 5. Deployment steps (outline)

```bash
# 0. One-time GCP setup (hosting services only — no aiplatform)
gcloud services enable run.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com calendar-json.googleapis.com

# 1. Create secrets
gcloud secrets create livekit-api-key --data-file=-   # repeat per secret

# 2. Build + push images (two)
gcloud builds submit ./agent --tag REGION-docker.pkg.dev/PROJECT/repo/agent
gcloud builds submit ./web   --tag REGION-docker.pkg.dev/PROJECT/repo/web

# 3. Deploy the warm agent worker (2 vCPU / 2Gi for in-process Kokoro TTS).
#    Calendar SA key is mounted as a FILE from Secret Manager.
gcloud run deploy smart-scheduler-agent \
  --image REGION-docker.pkg.dev/PROJECT/repo/agent \
  --min-instances=1 --no-cpu-throttling --cpu=2 --memory=2Gi \
  --no-allow-unauthenticated \
  --service-account=scheduler-run@PROJECT.iam.gserviceaccount.com \
  --set-env-vars=GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcal-sa.json,AGENT_TIMEZONE=Asia/Kolkata,LLM_PROVIDER=groq \
  --set-secrets=LIVEKIT_URL=livekit-url:latest,LIVEKIT_API_KEY=livekit-api-key:latest,LIVEKIT_API_SECRET=livekit-api-secret:latest,GROQ_API_KEY=groq-api-key:latest,GEMINI_API_KEY=gemini-api-key:latest,GCAL_CALENDAR_ID=gcal-calendar-id:latest,/secrets/gcal-sa.json=gcal-sa-json:latest

# 4. Deploy the public frontend + token service (this URL goes to the client)
gcloud run deploy smart-scheduler-web \
  --image REGION-docker.pkg.dev/PROJECT/repo/web \
  --allow-unauthenticated \
  --set-secrets=LIVEKIT_API_KEY=livekit-api-key:latest,LIVEKIT_API_SECRET=livekit-api-secret:latest,LIVEKIT_URL=livekit-url:latest
```

> The `smart-scheduler-web` service URL (e.g.
> `https://smart-scheduler-web-<hash>-<region>.run.app`) is the single public
> link handed to the client — they open it, click Connect, and talk. The LiveKit
> API **secret** stays server-side in this service (used only to sign tokens);
> the browser only ever receives a short-lived per-session JWT.

> `--no-cpu-throttling` (CPU always allocated) + `min-instances=1` keep the
> worker responsive between turns and avoid cold-start latency during the demo.

## 6. Region

Pick a region close to the demo audience and to LiveKit Cloud's region to
minimize RTT (e.g. `asia-south1` for India). LiveKit Cloud auto-selects the
nearest edge; keep the worker in that same region.

## 7. Rough cost (POC / demo scale)

| Item | Estimate |
|---|---|
| Cloud Run worker (1 warm instance, 2 vCPU, always-on CPU — LLM+STT+TTS) | ~$25–45/mo |
| Cloud Run web (scale-to-zero) | <$5/mo |
| Groq LLM + STT (free tier) | **$0** |
| Gemini AI Studio (fallback, free tier) | **$0** |
| Kokoro TTS (open weights, in-process) | **$0** (compute counted above) |
| LiveKit Cloud | free tier covers demo traffic |
| Secret Manager, Artifact Registry, logging | negligible |

**All model spend is $0** — the only cost is Cloud Run compute for the one warm
worker. Total for a short-lived POC: **~$25–50/mo while running**, near $0 if
torn down after the demo. Set a **budget alert**; drop the worker to
`min-instances=0` outside demos (accepting a cold-start on first use).

## 8. CI/CD (optional, nice-to-have)

`cloudbuild.yaml` at the repo root builds both images and deploys both services.
Run `gcloud builds submit --config cloudbuild.yaml` or wire a push trigger.
