# Deployment guide — free hosting for a 2 GB model app

## The constraint that decides everything

This app loads **two sentence-transformer models** (embeddings + cross-encoder
reranker) plus PyTorch. At runtime it needs roughly **1.5–2 GB of RAM**.

That single fact eliminates most free tiers:

| Platform | Free RAM | Verdict |
|---|---|---|
| **Hugging Face Spaces (Docker)** | ~16 GB (2 vCPU) | ✅ **Recommended** — fits comfortably, and it is where the ML community looks |
| **Oracle Cloud Always Free (ARM VM)** | 24 GB | ✅ Works, but you run the VM, TLS and process supervision yourself |
| Render (free web service) | 512 MB | ❌ Killed on the first model load |
| Koyeb / Fly.io free allowances | 256–512 MB | ❌ Same problem |
| Vercel / Netlify | static only | ❌ No Python, no models |
| Google Cloud Run | pay-per-use, free allowance | ⚠️ Possible with the models baked into the image, but cold starts are long and it is easy to slip out of the free allowance |
| Railway / others | trial credit, then paid | ⚠️ Not actually free |

> Free-tier limits change often. Check the current numbers before committing.

**If you want the app to fit a 512 MB tier**, the only real way is to stop
loading local models: swap the embeddings for an API-embedding model (Gemini
has one). That removes PyTorch and sentence-transformers entirely and the app
drops to a few hundred MB — at the cost of a paid API call per embedding.

---

## Recommended: Hugging Face Spaces (Docker SDK)

A `Dockerfile` is already provided at the repository root for exactly this
(single container, port 7860, both models pre-downloaded during the build).

### 1. Create the Space

On huggingface.co → **New Space**:

- **SDK:** Docker
- **Hardware:** CPU basic (free)
- **Visibility:** Public (that is the point — it is a portfolio piece)

### 2. Add the Space configuration to `README.md`

Spaces reads YAML front-matter from the repository's `README.md`. Add this to
the very top of the file (it must be the first thing in the file):

```yaml
---
title: Doc-Chat RAG
emoji: 📄
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---
```

### 3. Push the code

```bash
git remote add space https://huggingface.co/spaces/<your-username>/doc-chat
git push space main
```

The build takes a while the first time (PyTorch + both models are baked into the
image). After that, updates only rebuild the layers that changed.

### 4. Set the secrets (never in the repo)

In the Space: **Settings → Variables and secrets**. Add:

| Name | Value |
|---|---|
| `DEEPSEEK_API_KEY` | your DeepSeek key |
| `GEMINI_API_KEY` | your Gemini key (image OCR) |
| `LLM_PROVIDER` | `deepseek` |
| `SECRET_KEY` | a fresh random string — see below |

Generate a production secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` is already excluded by `.gitignore` **and** `.dockerignore`, so keys can
never be committed or baked into an image. Verify that once yourself with
`git status` before the first push.

---

## Things to know before you share the link

**1. Data disappears on rebuild.** On the free tier the container filesystem is
ephemeral. ChromaDB, the SQLite databases and uploaded files are wiped whenever
the Space restarts or rebuilds. That is fine for a demo — document it so nobody
is surprised, and use the synthetic files in `eval/test_docs/` when testing in
public rather than personal documents.

**2. It sleeps, then takes ~10–30 seconds to wake.** Models are baked into the
image, so the first request loads them from disk rather than downloading them,
but the first answer after idle will still feel slow. Tell people in the README
so it doesn't look broken.

**3. Anyone who registers can spend your credits.** There is no rate limiting in
the backend yet. Before sharing the link widely:

- set a **spending cap** in your DeepSeek (and Google) console — this is the
  one that actually protects you,
- or keep the Space private and share a demo video instead,
- or add a per-IP limit on `/register`, `/login` and `/ask`.

**4. Logout revocation is in-memory.** A token revoked by `/logout` becomes
valid again after a restart, until it expires (7 days by default). Acceptable
for a demo; fix by moving the denylist to Redis/Postgres if it ever holds real
user data.

**5. CORS.** `CORS_ORIGINS=*` is the default. Once you know the Space URL, set
it to that exact origin.

**6. Health check.** `GET /health` reports the status of each service — the
first thing to look at if the Space starts but does not answer.

---

## Alternative: Oracle Cloud Always Free

If you want the app always-on with no sleep, the ARM VM on Oracle's always-free
tier (up to 24 GB RAM) is the strongest free option. You are responsible for
everything a platform would normally do: a systemd unit (or Docker) to run
`uvicorn`, nginx as a reverse proxy, TLS via Let's Encrypt, and OS updates. More
work, but no cold starts and no ephemeral filesystem surprises.

---

## Checklist before going live

- [ ] `SECRET_KEY` is a fresh random value, not the repository default
- [ ] API keys are set as platform secrets, never committed
- [ ] Spending caps set on the LLM providers
- [ ] `CORS_ORIGINS` restricted to the deployed origin
- [ ] Cold start and data-reset behaviour documented in the README
- [ ] Tested with the synthetic documents in `eval/test_docs/`, not personal files
- [ ] First answer after idle verified as working (not just the landing page)
