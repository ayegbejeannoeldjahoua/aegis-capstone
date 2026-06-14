# Model Routing

The model registry supports provider/model refs, aliases, allowlists, primary/fallback behavior, local providers, hosted providers, risk-tier tags, and region constraints.

Supported adapter classes:

- `ollama`: local Ollama `/api/chat`.
- `openai_compatible`: OpenAI-compatible `/chat/completions`, used for OpenAI, NVIDIA-compatible endpoints, vLLM, LM Studio, and many gateways.
- `azure_openai`: Azure OpenAI-compatible extension point.

Production concepts implemented:

- provider/model refs: `provider/model`
- aliases: `local-fast`, `enterprise-reasoning`
- allowed model catalog
- primary/fallback list
- fail-visible unknown model
- policy-controlled region
- tenant values impact model route
- model audit event records provider/model/region

To add a model, edit `configs/model_registry.yaml`, define provider metadata, and store secrets in Vault or env.
