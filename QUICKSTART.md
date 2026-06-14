# Quickstart

## 1. Requirements

- Docker Desktop or Docker Engine + Compose v2
- Python 3.11+ only if running local CLI/tests outside containers
- At least one model provider:
  - Ollama locally, or
  - OpenAI-compatible endpoint, or
  - NVIDIA-compatible endpoint, or
  - vLLM OpenAI-compatible endpoint, or
  - Azure OpenAI-compatible endpoint

## 2. Configure

```bash
cp .env.example .env
```

For a fully local first run, install/pull an Ollama model on the host and set:

```bash
SAF_DEFAULT_MODEL=ollama/llama3.1:8b
SAF_MODEL_PROVIDER_MODE=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

For NVIDIA-compatible hosted inference:

```bash
SAF_DEFAULT_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_API_KEY=...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
```

For generic OpenAI-compatible:

```bash
SAF_DEFAULT_MODEL=openai/gpt-4.1-mini
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
```

## 3. Start stack

```bash
docker compose up -d --build
./scripts/wait-for-stack.sh
./scripts/bootstrap.sh
```

## 4. Get a demo token

```bash
TOKEN=$(./scripts/get-token.sh jane analyst acme-corp)
```

## 5. Ask the governed agent

```bash
curl -s http://localhost:8080/v1/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is known about widget defects in Q1?","skill_id":"summarise-with-memory"}' | jq
```

## 6. See audit and traces

```bash
curl -s http://localhost:8080/v1/audit/last | jq
curl -s http://localhost:8080/v1/audit/verify | jq
```

Jaeger: http://localhost:16686

## 7. Test production controls

```bash
./scripts/demo-denials.sh
```

This demonstrates:

- missing/invalid token denial
- cross-tenant memory denial
- model region denial
- untrusted tool-output injection denial
- PDP fail-closed behavior
- audit chain reconstruction
