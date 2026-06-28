# Build and Deploy to k3s

`brain/` runs on k3s; `voice/` runs bare metal on a Raspberry Pi (USB audio).
Only `brain/` is containerized/deployed.

Deployment is **GitOps**. This public repo holds the application code and the
CI workflow; the topology-bearing Kubernetes manifests live in a **private**
deploy repo:
- Code + CI: this repo (`luna-voice-assistant`)
- Manifests: `https://github.com/aachtenberg/luna-voice-assistant-deploy`
  (Deployment, Service, `kustomization.yml`) — private because it embeds LAN
  IPs, cluster DNS, a node pin, and host paths.

ArgoCD's standalone `luna-brain` Application (registered in `homelab-infra`)
syncs the deploy repo and is the source of truth for the running state.

Current deployment model for `luna-brain`:
- Image: `ghcr.io/aachtenberg/luna-brain` (pinned to an immutable `:main-<sha7>`
  tag by the `images:` block in the deploy repo's `kustomization.yml`)
- `imagePullPolicy: IfNotPresent`, pulled with the `ghcr-pull-secret` in the
  `apps` namespace
- Node pin: `kubernetes.io/hostname: raspberrypi3` (so the image is built for
  **linux/arm64**)

## The deploy flow (push to main)

```bash
git add brain/ && git commit -m "..." && git push   # to main
```

That's it. On any push touching `brain/**`:

1. **Build** — `.github/workflows/build-luna-brain.yml` builds a `linux/arm64`
   image via QEMU and pushes two tags to GHCR:
   `ghcr.io/aachtenberg/luna-brain:main` and `:main-<sha7>`.
2. **Bump** — its `bump-deploy-repo` job runs `kustomize edit set image` in the
   private deploy repo and commits the new `:main-<sha7>` tag straight to that
   repo's `main` (auth via the `LUNA_DEPLOY_PAT` repo secret on this repo; the
   GHCR push itself uses the built-in `GITHUB_TOKEN`).
3. **Sync** — ArgoCD (`automated`, `selfHeal`, `prune`) reconciles the bump and
   rolls the Deployment. The old pod keeps serving until the new one is Ready.

Watch it land:

```bash
gh run watch -R aachtenberg/luna-voice-assistant            # the build + bump
kubectl get application luna-brain -n argocd -w             # the rollout
kubectl -n apps get pods -l app.kubernetes.io/name=luna-brain -w
kubectl -n apps logs  -l app.kubernetes.io/name=luna-brain -f --tail=100
```

> One-time prerequisites (already in place): the `LUNA_DEPLOY_PAT` repo secret
> (contents:write on the deploy repo), the `ghcr-pull-secret` in the `apps`
> namespace, and the ArgoCD repo credential for the private deploy repo.

## Environment config

The brain reads config from env vars set in the Deployment (in the **deploy
repo**'s `luna-brain.yml`). To change config, edit that manifest and push — do
**not** `kubectl set env` / `kubectl edit` live, as ArgoCD `selfHeal` reverts it.

Inspect the live wiring:

```bash
kubectl -n apps get deploy luna-brain -o yaml
```

Common vars: `LLM_PROVIDER`, `OLLAMA_URL`, `OLLAMA_AUTO_MODEL`, `OLLAMA_MODEL`,
`OLLAMA_MODEL_REFRESH_SECONDS`, `GROQ_MODEL`, `ANTHROPIC_MODEL`, `SEARXNG_URL`,
`MQTT_BROKER`, `PROMETHEUS_URL`, `INFLUXDB_URL`/`INFLUXDB_DATABASE`, the
`LOCATION_*` set, and API keys via Secret refs (`ANTHROPIC_API_KEY`,
`GROQ_API_KEY`, `INFLUXDB_TOKEN`) from the `luna-brain-secrets` SealedSecret.

### Switching the LLM without a deploy

Provider/model routing can be changed **live** via `/admin/provider` (no
restart, persisted to `LLM_OVERRIDE_PATH` on the data volume). On the cluster,
use the `luna-llm` CLI in the deploy repo:

```bash
./luna-llm                 # show current config + live chain
./luna-llm set provider=groq
./luna-llm set provider=ollama ollama_model=qwen2.5:14b
./luna-llm reset           # back to env-var defaults
```

API keys are never set this way — they always come from the Secret.

## Smoke test

The Service is ClusterIP-only and the pod has python but not curl:

```bash
kubectl exec -n apps deploy/luna-brain -- python -c \
 "import urllib.request,json;print(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/ask',data=json.dumps({'text':'what time is it?'}).encode(),headers={'Content-Type':'application/json'})).read().decode())"

# Metrics
kubectl exec -n apps deploy/luna-brain -- python -c \
 "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/metrics').read().decode())" | grep brain_current_provider
```

## Rollback

Revert via git — ArgoCD follows:

```bash
# In the deploy repo: revert the bad image bump (or set an older :main-<sha7>) and push.
git -C luna-voice-assistant-deploy revert <bump-sha> && git push
```

Because every build publishes an immutable `:main-<sha7>` tag, any prior known-good
tag can be pinned back in `kustomization.yml` for a fast rollback. Avoid
in-cluster `kubectl rollout undo` — ArgoCD will re-sync to whatever git says.

## Notes

- `voice/` runs on bare-metal Raspberry Pi for USB audio access; only `brain/`
  is containerized/deployed on k3s.
- Keep deployment state declarative in the deploy repo; avoid manual `kubectl`
  drift, which `selfHeal` fights.
- Legacy: luna-brain used to be a hand-built `homelab-app-brain` image with
  `imagePullPolicy: Never`, imported on the node via `nerdctl ... | k3s ctr
  images import`. That path is retired.
