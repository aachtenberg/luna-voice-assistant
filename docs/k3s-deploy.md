# Build and Deploy to k3s

This repository currently does not include Kubernetes manifests.
Kubernetes manifests and deployment configuration live in:
- https://github.com/aachtenberg/homelab-infra

Use that repository as the source of truth for namespaces, deployment specs,
service definitions, ingress, configmaps, and secrets.

Current `homelab-infra` deployment model for `luna-brain` (at time of writing):
- Deployment image: `homelab-app-brain`
- `imagePullPolicy: Never`
- Node pinning: `kubernetes.io/hostname: raspberrypi3`

The expected workflow from this app repository is:
1. Build/update the `homelab-app-brain` image on the node that runs `luna-brain`.
2. Apply/update manifests from `homelab-infra` as needed.
3. Restart rollout and run smoke tests.

These instructions assume your cluster already has:
- Namespace `apps`
- Deployment `luna-brain`
- Service `luna-brain` on port `8000`

## 1) Prerequisites

On your workstation:
- `kubectl` configured for your k3s cluster context
- Access to the node running `luna-brain` (currently `raspberrypi3`) for local image builds

On the node that builds the image:
- `nerdctl`
- `k3s ctr`

Verify context and current workload:

```bash
kubectl config current-context
kubectl -n apps get deploy luna-brain
kubectl -n apps get pods -l app.kubernetes.io/name=luna-brain
```

## 2) Build image for current infra model (local node image)

Build on the node that hosts `luna-brain` so kubelet can use the locally imported image. `docker` is not available on the cluster nodes; use `nerdctl` in the `k8s.io` namespace and then import the image into k3s's containerd store:

```bash
ssh aachten@raspberrypi3 '
  cd /home/aachten/luna-voice-assistant &&
  sudo nerdctl --namespace k8s.io build --no-cache -t homelab-app-brain:latest ./brain &&
  sudo nerdctl --namespace k8s.io save homelab-app-brain:latest | sudo k3s ctr images import -
'
```

Then restart the deployment:

```bash
kubectl -n apps rollout restart deployment/luna-brain
kubectl -n apps rollout status deployment/luna-brain --timeout=180s
```

Notes:
- `--no-cache` avoids stale layers during homelab builds
- The `nerdctl save | k3s ctr images import` pipe is required because nerdctl and k3s use separate containerd stores
- `imagePullPolicy` should remain `Never` or `IfNotPresent` for this local-image workflow

Optional future model: registry-backed immutable images

If you change `homelab-infra` to use registry images (and a non-`Never` pull policy), use immutable tags:

```bash
export IMAGE_REPO=ghcr.io/aachtenberg/luna-brain
export IMAGE_TAG=$(git rev-parse --short HEAD)
export IMAGE=${IMAGE_REPO}:${IMAGE_TAG}

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f brain/Dockerfile \
  -t ${IMAGE} \
  --push \
  ./brain
```

## 3) Deploy via homelab-infra

Preferred path (GitOps-style) is to update image tags in the infra repo and apply:

```bash
git clone https://github.com/aachtenberg/homelab-infra.git
cd homelab-infra

# Update `k3s/base/apps/luna-brain.yml` as needed, commit, then apply
kubectl apply -f <path-to-luna-brain-manifests>
kubectl -n apps rollout status deployment/luna-brain --timeout=180s
```

If you need a fast/manual hotfix, patch image directly in-cluster:

```bash
kubectl -n apps set image deployment/luna-brain luna-brain=homelab-app-brain:latest
kubectl -n apps rollout status deployment/luna-brain --timeout=180s
```

Watch pod restarts and logs:

```bash
kubectl -n apps get pods -l app.kubernetes.io/name=luna-brain -w
kubectl -n apps logs -l app.kubernetes.io/name=luna-brain -f --tail=100
```

## 4) Environment config in k3s

The brain app reads config from env vars.
For k3s deployments, set values in Deployment env / ConfigMap / Secret in `homelab-infra`.

Inspect current env wiring:

```bash
kubectl -n apps get deploy luna-brain -o yaml
```

Key env vars commonly updated:
- `LLM_PROVIDER`
- `OLLAMA_URL`
- `OLLAMA_AUTO_MODEL`
- `OLLAMA_MODEL` (fallback model)
- `OLLAMA_MODEL_REFRESH_SECONDS`
- `TIMESCALEDB_HOST`, `TIMESCALEDB_PORT`, `TIMESCALEDB_DATABASE`, `TIMESCALEDB_USER`, `TIMESCALEDB_PASSWORD`
- `SEARXNG_URL`
- `MQTT_BROKER`
- `PROMETHEUS_URL`
- `LOCATION_CITY`, `LOCATION_REGION`, `LOCATION_COUNTRY`, `LOCATION_TIMEZONE`, `LOCATION_LAT`, `LOCATION_LON`
- API keys via Secret refs (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`)

After env changes are applied from `homelab-infra`, restart rollout if needed:

```bash
kubectl -n apps rollout restart deployment/luna-brain
kubectl -n apps rollout status deployment/luna-brain --timeout=180s
```

## 5) Smoke test

From any node with cluster DNS access:

```bash
curl -X POST http://luna-brain.apps.svc.cluster.local:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"text":"what time is it?"}'
```

Check metrics endpoint:

```bash
kubectl -n apps port-forward deploy/luna-brain 8000:8000
curl http://127.0.0.1:8000/metrics
```

## 6) Rollback (if needed)

```bash
kubectl -n apps rollout undo deployment/luna-brain
kubectl -n apps rollout status deployment/luna-brain --timeout=180s
```

## Notes

- `voice/` is intended to run on bare metal Raspberry Pi for USB audio access; only `brain/` is containerized/deployed on k3s.
- For production, pin images to immutable tags (commit SHA), avoid `latest`, and keep at least one known-good tag for fast rollback.
- Keep deployment state declarative in `homelab-infra`; avoid long-term drift from manual `kubectl set image` changes.
