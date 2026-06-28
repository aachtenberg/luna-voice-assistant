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

Deployment is **GitOps** — push to `main` and the pipeline does the rest. There
is no manual image build.

```bash
git add brain/ && git commit -m "..." && git push   # to main
```

- `.github/workflows/build-luna-brain.yml` builds a `linux/arm64` image (pod is
  pinned to a Pi), pushes `ghcr.io/aachtenberg/luna-brain:main` + `:main-<sha7>`
  to GHCR, then bumps the private `luna-voice-assistant-deploy` repo.
- ArgoCD syncs the bump and rolls the pod. Don't hand-edit live resources —
  `selfHeal` reverts them; change git instead.
- The topology-bearing deploy manifests live in the private deploy repo, not here.
- Legacy: the hand-built `homelab-app-brain` + `imagePullPolicy: Never` /
  `nerdctl ... | k3s ctr images import` flow is retired.
