# Copilot Instructions for Luna Voice Assistant

This repository contains a self-hosted voice assistant split across two Python services:
- `brain/`: FastAPI service that handles LLM/tool orchestration.
- `voice/`: wake word, audio capture, STT, and TTS runtime on Raspberry Pi hardware.

## Architecture and Boundaries

- Keep `voice/` and `brain/` loosely coupled via HTTP only.
- Do not move USB audio or wake-word logic into `brain/`.
- Keep hardware-specific logic in `voice/`.
- Keep tool orchestration and model/provider selection in `brain/`.

## Coding Guidelines

- Prefer small, focused functions and clear names.
- Preserve existing module boundaries and public function signatures unless the task requires API changes.
- Use type hints for new/changed Python code where practical.
- Follow existing logging style:
  - Use structured logging setup already present in each service.
  - Avoid noisy debug output unless gated behind config.
- Keep comments short and only where logic is non-obvious.

## Configuration Rules

- Read configuration from environment variables via existing config modules.
- When adding settings:
  - Add sane defaults.
  - Add to `brain/.env.example` or `voice/.env` docs as appropriate.
  - Update `README.md` for user-facing setup changes.
- Never hardcode secrets, API keys, private hosts, or tokens.

## LLM and Tooling Behavior (brain)

- Keep provider-specific code under `brain/llm/`.
- Keep external integrations under `brain/tools/`.
- Prefer graceful fallbacks when external services are unavailable.
- Avoid breaking tool-call loops, safety checks, or retry limits without clear justification.

## Voice Runtime Behavior (voice)

- Prioritize low-latency and reliability for wake-word, STT, and playback paths.
- Avoid changes that can block audio loops indefinitely.
- Preserve interruption/barge-in behavior when modifying streaming/TTS flow.

## Testing and Validation

- Run targeted checks for changed files first.
- For Python edits, at minimum ensure changed files are syntax/error free.
- If behavior changes, include a brief manual verification path in the final response.

## Scope and Safety

- Do not add destructive shell commands in docs or scripts by default.
- Do not rewrite unrelated files during refactors.
- Keep changes minimal and aligned with the current deployment model (k3s for `brain`, bare metal Pi for `voice`).

## Building and Deploying (brain)

`docker` is not available on cluster nodes. Use `nerdctl` with the `k8s.io` namespace.

```bash
# Build into k8s.io namespace (default nerdctl namespace is invisible to k3s)
sudo nerdctl --namespace k8s.io build --no-cache -t homelab-app-brain:latest ./brain/

# Import into k3s containerd store
sudo nerdctl --namespace k8s.io save homelab-app-brain:latest | sudo k3s ctr images import -

# Restart pod
kubectl rollout restart deploy/luna-brain -n apps
kubectl rollout status deploy/luna-brain -n apps --timeout=60s
```

- Always use `--no-cache` to prevent stale layers.
- The save/import pipe is required — nerdctl and k3s use separate containerd stores.
- Deployment `imagePullPolicy` must be `Never` or `IfNotPresent` to use the locally imported image.
