# Step-by-step production-mode demonstration

This guide demonstrates several users from different teams/tenants using the platform in real time.

## 1. Start

```bash
cp .env.example .env
# Configure model provider in .env. For local demonstration, run Ollama on host.
docker compose up -d --build
./scripts/wait-for-stack.sh
./scripts/bootstrap.sh
```

## 2. Obtain tokens

```bash
JANE=$(./scripts/get-token.sh jane analyst acme-corp)
LEE=$(./scripts/get-token.sh lee lead acme-corp)
BEN=$(./scripts/get-token.sh ben analyst beta-corp)
```

## 3. Concurrent API use

Open three terminals:

```bash
curl -s http://localhost:8080/v1/ask -H "Authorization: Bearer $JANE" -H 'Content-Type: application/json' -d '{"prompt":"Widget defects Q1"}' | jq
curl -s http://localhost:8080/v1/ask -H "Authorization: Bearer $LEE" -H 'Content-Type: application/json' -d '{"prompt":"Widget defects Q1"}' | jq
curl -s http://localhost:8080/v1/ask -H "Authorization: Bearer $BEN" -H 'Content-Type: application/json' -d '{"prompt":"Widget defects Q1"}' | jq
```

Expected behavior:

- Jane sees only ACME tenant memory.
- Lee has lead role and can be extended to write team-decisions.
- Ben sees only Beta tenant memory.
- Audit records separate tenant IDs and trace IDs.

## 4. Real-time WebSocket use

Use a WebSocket client such as `websocat`:

```bash
websocat "ws://localhost:8080/v1/ws/chat?token=$JANE"
```

Then send:

```json
{"type":"ask","prompt":"What is known about widget defects in Q1?"}
```

## 5. Model selection

```bash
curl -s http://localhost:8080/v1/models | jq
curl -s http://localhost:8080/v1/ask \
  -H "Authorization: Bearer $JANE" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Widget defects Q1","model":"ollama/llama3.1:8b"}' | jq
```

## 6. Governance checks

```bash
./scripts/demo-denials.sh
curl -s http://localhost:8080/v1/audit/verify | jq
```

## 7. Observe

Open Jaeger at http://localhost:16686 and select `sentinel-api`.
