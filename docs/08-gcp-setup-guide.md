# 08 — GCP & Services Setup Guide (do this now)

Everything you need to provision **before** implementation, so all services are
available. Two parts:

- **Part A** — three **free external accounts** to create and copy keys from
  (LiveKit Cloud, Groq, Google AI Studio) + the demo Google Calendar.
- **Part B** — **GCP resources** (APIs, Artifact Registry, service accounts,
  IAM, Secret Manager, budget alert) via copy-paste `gcloud` commands.

By the end you'll have every value the app needs stored in **Secret Manager**,
ready for the deploy commands in [04-gcp-deployment.md](04-gcp-deployment.md).

> Reminder of the constraints: **free models only**, **GCP for hosting only** —
> so there is **no Vertex AI / Cloud STT / Cloud TTS** to enable here.

---

## 0. Prerequisites

- A Google account with a **GCP project** and **billing enabled** (Cloud Run
  needs billing even though usage is tiny). Free-trial credits are fine.
- **`gcloud` CLI** installed and authenticated:
  ```bash
  gcloud auth login
  gcloud config set project YOUR_PROJECT_ID
  ```
- Docker is **not** required locally — images are built with Cloud Build.

Set these shell variables once (reused by every command below):

```bash
export PROJECT_ID="your-project-id"
export REGION="asia-south1"          # pick one near your demo audience
export REPO="smart-scheduler"        # Artifact Registry repo name
gcloud config set project "$PROJECT_ID"
```

---

## Part A — Free external accounts (copy the keys, you'll store them in Part B)

### A1. LiveKit Cloud (media transport) — free tier
1. Sign up at **https://cloud.livekit.io** and create a **project**.
2. From the project's **Settings → Keys**, copy three values:
   - **Project URL** → looks like `wss://<name>.livekit.cloud`
   - **API Key** → `APIxxxxxxxx`
   - **API Secret** → long secret string
3. Keep them for `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.

### A2. Groq (LLM + STT) — free tier
1. Sign up at **https://console.groq.com**.
2. **API Keys → Create API Key**, copy it (shown once).
3. Keep it for `GROQ_API_KEY`.

### A3. Google AI Studio (fallback LLM: Gemini 2.0 Flash) — free tier
1. Go to **https://aistudio.google.com/apikey** (a Google account; this is the
   free **Developer API**, *not* Vertex/GCP billing).
2. **Create API key**, copy it.
3. Keep it for `GEMINI_API_KEY`.

> This is only the fallback LLM — still worth having so you can switch instantly
> if Groq rate-limits during the demo.

### A4. Demo Google Calendar (do this *after* Part B creates the calendar SA)
Deferred to **Part B, step B6** because it needs the calendar service-account
email that you create there.

---

## Part B — GCP resources (copy-paste)

### B1. Enable the required APIs (hosting only — no `aiplatform`)
```bash
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  calendar-json.googleapis.com
```

### B2. Create the Artifact Registry Docker repo
```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Smart Scheduler images"
```

### B3. Create the two service accounts
```bash
# Runtime identity for the Cloud Run services (worker, tts, web)
gcloud iam service-accounts create scheduler-run \
  --display-name="Smart Scheduler Cloud Run runtime"

# Dedicated identity used ONLY to access the demo calendar
gcloud iam service-accounts create scheduler-cal \
  --display-name="Smart Scheduler Calendar access"
```

Capture their emails:
```bash
export RUN_SA="scheduler-run@${PROJECT_ID}.iam.gserviceaccount.com"
export CAL_SA="scheduler-cal@${PROJECT_ID}.iam.gserviceaccount.com"
```

### B4. Grant IAM roles to the runtime SA
```bash
# Read secrets from Secret Manager
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/secretmanager.secretAccessor"

# Write logs
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/logging.logWriter"
```

> The worker→TTS call also needs `roles/run.invoker`; that's granted on the TTS
> service specifically at deploy time (see [04](04-gcp-deployment.md)), so no
> project-wide grant is needed now.

The `scheduler-cal` SA needs **no GCP roles** — its only power comes from being
shared into the calendar (step B6).

### B5. Create the calendar SA key (used by the app to authenticate to Calendar)
```bash
gcloud iam service-accounts keys create ./gcal-sa.json \
  --iam-account="$CAL_SA"
```
This writes `gcal-sa.json` locally. **Do not commit it** — it goes into Secret
Manager in step B7 and can be deleted locally afterward.

> *Hardening option (optional):* instead of a key file, run Cloud Run as
> `scheduler-cal` and use Application Default Credentials (keyless). The key-file
> path is used here because it also works for local development.

### B6. Create + share the demo calendar
1. Open **https://calendar.google.com** (any Google account).
2. Create a calendar: **Settings → Add calendar → Create new calendar**, name it
   e.g. *"Smart Scheduler Demo"*, **Create**.
3. Select it in the left list → **Settings and sharing**.
4. Under **Share with specific people or groups → Add people**, paste the
   `scheduler-cal@...` email (echo `$CAL_SA` to copy it) and set permission to
   **"Make changes to events"**. Save.
5. Scroll to **Integrate calendar** → copy the **Calendar ID** (looks like
   `xxxxxxxx@group.calendar.google.com`). Keep it for `GCAL_CALENDAR_ID`.
6. Pre-seed a few events (a busy Tuesday afternoon, a *"Project Alpha Kick-off"*,
   a late-day meeting) so the conflict-resolution / relative-time demos trigger.

### B7. Store every value in Secret Manager
Replace the placeholder values with what you copied in Part A.
```bash
printf 'wss://YOUR.livekit.cloud' | gcloud secrets create livekit-url          --data-file=-
printf 'APIxxxxxxxx'              | gcloud secrets create livekit-api-key       --data-file=-
printf 'YOUR_LIVEKIT_SECRET'      | gcloud secrets create livekit-api-secret    --data-file=-
printf 'YOUR_GROQ_KEY'            | gcloud secrets create groq-api-key          --data-file=-
printf 'YOUR_GEMINI_KEY'          | gcloud secrets create gemini-api-key        --data-file=-
printf 'xxxx@group.calendar.google.com' | gcloud secrets create gcal-calendar-id --data-file=-
gcloud secrets create gcal-sa-json --data-file=./gcal-sa.json
```
`AGENT_TIMEZONE` (e.g. `Asia/Kolkata`) is non-secret — pass it as a plain env var
at deploy time, not a secret.

Verify they all exist:
```bash
gcloud secrets list
# expect: gcal-calendar-id, gcal-sa-json, gemini-api-key,
#         groq-api-key, livekit-api-key, livekit-api-secret, livekit-url
```

Clean up the local key file once stored:
```bash
rm -f ./gcal-sa.json
```

### B8. Budget alert (recommended)
Easiest via console: **Billing → Budgets & alerts → Create budget**, scope to the
project, set e.g. **$25/month** with 50/90/100% email alerts. (Or via
`gcloud billing budgets create` if you have your billing account ID.)

---

## Done — verification checklist

| Item | Check |
|---|---|
| APIs enabled | `gcloud services list --enabled` shows run, secretmanager, artifactregistry, cloudbuild, calendar-json |
| Artifact Registry repo | `gcloud artifacts repositories list --location=$REGION` shows `smart-scheduler` |
| Service accounts | `gcloud iam service-accounts list` shows `scheduler-run` + `scheduler-cal` |
| Runtime SA roles | secretAccessor + logWriter bound (`gcloud projects get-iam-policy $PROJECT_ID`) |
| Calendar shared | `scheduler-cal` email listed under the demo calendar's sharing with "Make changes to events" |
| Secrets | `gcloud secrets list` shows all 7 secrets |
| External keys | LiveKit URL/key/secret, Groq key, Gemini key all captured |

When every row is checked, the environment is ready and the next step is to build
the code and run the deploy commands in [04-gcp-deployment.md](04-gcp-deployment.md).

## What you will hand to the client (later)
After deploy, the **`smart-scheduler-web` Cloud Run URL** is the public link the
client opens and talks to. Nothing from this setup step is exposed publicly — all
keys/secrets stay server-side in Secret Manager.
