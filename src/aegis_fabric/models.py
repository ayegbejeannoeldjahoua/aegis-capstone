from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .logging_config import get_logger, log_event
from .secrets import secrets
from .settings import settings

logger = get_logger("aegis.models")


class ModelNotAllowed(ValueError):
    """Raised when a requested model is unknown or disallowed by routing rules."""


class ChatMessage(BaseModel):
    role: str
    content: str


class ModelResult(BaseModel):
    model: str
    provider: str
    content: str
    usage: dict = {}


class ModelProfile(BaseModel):
    provider: str
    model_id: str
    type: str
    base_url: str
    api_key: str | None = None
    region: str
    local: bool = False
    risk_tiers: list[str] = []
    supports_tools: bool = False
    deployment: str | None = None


def _registry_path() -> Path:
    if settings.model_registry_path:
        return Path(settings.model_registry_path)
    p = Path("/app/configs/model_registry.yaml")
    return p if p.exists() else Path("configs/model_registry.yaml")


class ModelRegistry:
    def __init__(self, path: str | None = None):
        self.raw = yaml.safe_load((Path(path) if path else _registry_path()).read_text())

    # -- internal helpers ---------------------------------------------------
    def _find(self, model_id: str) -> tuple[str, dict, dict] | None:
        for provider_id, provider in self.raw["providers"].items():
            for m in provider.get("models", []):
                if model_id == m["id"] or model_id in m.get("aliases", []):
                    return provider_id, provider, m
        return None

    def _to_profile(self, provider_id: str, provider: dict, model: dict) -> ModelProfile:
        base_url = os.getenv(provider.get("base_url_env", ""), "")
        api_key_name = provider.get("api_key_secret_env")
        api_key = secrets().get(api_key_name) if api_key_name else None
        deployment = None
        if provider.get("deployment_env"):
            deployment = os.getenv(provider["deployment_env"], "")
        return ModelProfile(
            provider=provider_id,
            model_id=model["id"],
            type=provider["type"],
            base_url=base_url,
            api_key=api_key,
            region=provider.get("region", settings.model_region),
            local=provider.get("local", False),
            risk_tiers=model.get("risk_tiers", []),
            supports_tools=model.get("supports_tools", False),
            deployment=deployment,
        )

    def resolve(self, requested: str | None = None) -> ModelProfile:
        model_id = requested or settings.default_model
        found = self._find(model_id)
        if not found:
            raise ModelNotAllowed(f"model not allowed or unknown: {model_id}")
        return self._to_profile(*found)

    # -- governed routing ---------------------------------------------------
    def _selection(self) -> dict:
        return self.raw.get("selection", {})

    def _fallback_ids(self) -> list[str]:
        return self._selection().get("fallbacks", [])

    def default_model_id(self) -> str:
        """The registry's configured default model id (literal; not env-expanded)."""
        return self._selection().get("default_model", settings.default_model)

    def catalog(self) -> list[dict]:
        """All registered models with routing-relevant metadata, for admin display."""
        out: list[dict] = []
        for provider_id, provider in self.raw["providers"].items():
            for m in provider.get("models", []):
                out.append({
                    "model_id": m["id"], "provider": provider_id, "type": provider["type"],
                    "local": provider.get("local", False),
                    "region": provider.get("region", settings.model_region),
                    "risk_tiers": m.get("risk_tiers", []),
                    "supports_tools": m.get("supports_tools", False),
                    "aliases": m.get("aliases", []),
                })
        return out

    def is_known(self, model_id: str) -> bool:
        return self._find(model_id) is not None

    def max_tier_of(self, model_id: str) -> str | None:
        """Effective (max) risk tier of a model, or None if unknown."""
        from . import rbac
        found = self._find(model_id)
        if not found:
            return None
        tiers = found[2].get("risk_tiers", [])
        return max(tiers, key=rbac.risk_rank) if tiers else "T1"

    def route(
        self,
        requested: str | None,
        *,
        allowed_region: str,
        classification: str = "internal",
        require_tool_support: bool = False,
        caps: dict | None = None,
        default_model: str | None = None,
    ) -> list[ModelProfile]:
        """Return ordered candidate profiles (primary then fallbacks) that satisfy
        routing policy: region residency; restricted/confidential data stays local;
        optional tool support; and the role's model governance caps (provider/model
        allowlist, max risk tier, and a classification threshold above which only
        local models are allowed). A user-pinned model that violates a hard policy
        raises ModelNotAllowed rather than silently routing elsewhere."""
        from . import rbac

        caps = caps or {}
        # A "local-only" data rule can only be honoured if the registry actually has a local
        # provider. In a hosted-only deployment (no local models) the constraint is vacuous, so
        # all classifications route to hosted models — governed instead by per-role classification
        # ceilings (max_read/write_classification) rather than model residency.
        has_local = any(p.get("local") for p in self.raw.get("providers", {}).values())
        restricted = has_local and classification in self._restricted_classes()
        # role-level: data at/above this classification must use a local model (only if one exists)
        thresh = caps.get("require_local_above_classification")
        if has_local and thresh and rbac.class_rank(classification) >= rbac.class_rank(thresh):
            restricted = True
        allowed_providers = caps.get("allowed_providers") or []
        allowed_model_ids = caps.get("allowed_model_ids") or []
        max_tier = caps.get("max_model_risk_tier", "T3")

        ordered_ids: list[str] = []
        strict_requested = bool(requested and self._selection().get("fail_visible_for_user_pinned_model", True))
        if requested:
            ordered_ids.append(requested)
        if not strict_requested:
            ordered_ids.append(default_model or self._selection().get("default_model", settings.default_model))
            ordered_ids.extend(self._fallback_ids())

        seen: set[str] = set()
        candidates: list[ModelProfile] = []
        rejected_pinned: list[str] = []
        for mid in ordered_ids:
            if not mid or mid in seen:
                continue
            seen.add(mid)
            found = self._find(mid)
            if not found:
                continue
            profile = self._to_profile(*found)
            ok, why = self._satisfies(profile, allowed_region, restricted, require_tool_support,
                                      allowed_providers, allowed_model_ids, max_tier)
            if ok:
                candidates.append(profile)
            elif requested and mid == requested:
                rejected_pinned.append(why)

        if requested and rejected_pinned and not any(c.model_id == self._canonical(requested) for c in candidates):
            raise ModelNotAllowed(
                f"requested model '{requested}' violates routing policy: {'; '.join(rejected_pinned)}"
            )
        if not candidates:
            raise ModelNotAllowed("no model satisfies routing policy (region/classification/governance)")
        # fallback_mode=strict (or residency_strict) forbids the cost-aware fallback chain:
        # only the primary candidate is offered, so a degrade never crosses provider/region.
        if (caps.get("fallback_mode") == "strict" or caps.get("residency_strict")) and len(candidates) > 1:
            candidates = candidates[:1]
        return candidates

    def _canonical(self, mid: str) -> str:
        found = self._find(mid)
        return found[2]["id"] if found else mid

    def _restricted_classes(self) -> set[str]:
        # Nothing to pin to a local model when the deployment has no local provider.
        if not any(p.get("local") for p in self.raw.get("providers", {}).values()):
            return set()
        for pol in self.raw.get("routing_policies", []):
            cond = pol.get("when", {})
            if "classification_in" in cond and pol.get("require", {}).get("local"):
                return set(cond["classification_in"])
        return {"restricted", "confidential"}

    @staticmethod
    def _satisfies(profile: ModelProfile, allowed_region: str, restricted: bool, need_tools: bool,
                   allowed_providers=None, allowed_model_ids=None, max_tier: str = "T3"):
        if profile.region != allowed_region:
            return False, f"region {profile.region} != allowed {allowed_region}"
        if restricted and not profile.local:
            return False, "data classification requires a local provider"
        if need_tools and not profile.supports_tools:
            return False, "model does not support tool calls"
        if allowed_providers and profile.provider not in allowed_providers:
            return False, f"provider {profile.provider} not in allowlist"
        if allowed_model_ids and profile.model_id not in allowed_model_ids:
            return False, f"model {profile.model_id} not in allowlist"
        # Model risk-tier gating was removed in v1.15.0 ("no tiers in model use"): a role's
        # max_model_risk_tier no longer blocks any model. risk_tiers remain for display only.
        # `max_tier` is accepted for signature stability but intentionally unused.
        _ = max_tier
        return True, ""


class ModelClient:
    async def chat(self, profile: ModelProfile, messages: list[ChatMessage], temperature: float = 0.2) -> ModelResult:
        if profile.type == "ollama":
            return await self._ollama(profile, messages, temperature)
        if profile.type == "azure_openai":
            return await self._azure(profile, messages, temperature)
        if profile.type == "openai_compatible":
            return await self._openai_compatible(profile, messages, temperature)
        if profile.type == "anthropic":
            return await self._anthropic(profile, messages, temperature)
        raise ValueError(f"unsupported provider type: {profile.type}")

    async def chat_with_fallbacks(
        self, profiles: list[ModelProfile], messages: list[ChatMessage], temperature: float = 0.2
    ) -> ModelResult:
        """Try each candidate profile in order; on provider error fall through to
        the next. Raises the last error if all candidates fail."""
        last_err: Exception | None = None
        for profile in profiles:
            start = time.perf_counter()
            try:
                result = await self._chat_retrying(profile, messages, temperature)
                try:
                    from . import operational_metrics

                    operational_metrics.record_model_call(
                        (time.perf_counter() - start) * 1000.0,
                        result.provider,
                        result.model,
                        result.usage,
                    )
                except Exception:
                    pass
                return result
            except Exception as e:  # provider/network error -> try next candidate
                last_err = e
                try:
                    from . import operational_metrics

                    operational_metrics.record_model_provider_error(profile.provider, profile.model_id, str(e))
                except Exception:
                    pass
                log_event(logger, 30, "model_call_failed_trying_fallback", model=profile.model_id, error=str(e))
        raise RuntimeError(f"all model candidates failed; last error: {last_err}")

    def _chat_retrying(self, profile: ModelProfile, messages: list[ChatMessage], temperature: float):
        @retry(
            reraise=True,
            stop=stop_after_attempt(max(1, settings.model_max_retries + 1)),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        )
        async def _do():
            return await self.chat(profile, messages, temperature)

        return _do()

    @staticmethod
    def _model_name(profile: ModelProfile) -> str:
        return profile.model_id.split("/", 1)[1] if "/" in profile.model_id else profile.model_id

    async def _ollama(self, profile, messages, temperature) -> ModelResult:
        if not profile.base_url:
            raise RuntimeError("OLLAMA_BASE_URL not configured")
        payload = {
            "model": self._model_name(profile),
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=settings.model_timeout_seconds) as client:
            r = await client.post(f"{profile.base_url.rstrip('/')}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        return ModelResult(model=profile.model_id, provider=profile.provider, content=data.get("message", {}).get("content", ""))

    async def _openai_compatible(self, profile, messages, temperature) -> ModelResult:
        env_prefix = profile.provider.upper().replace("-", "_")
        if not profile.base_url:
            raise RuntimeError(f"{env_prefix}_BASE_URL not configured")
        headers = {"Content-Type": "application/json"}
        if profile.api_key:
            headers["Authorization"] = f"Bearer {profile.api_key}"
        elif not profile.local:
            raise RuntimeError(f"{env_prefix}_API_KEY not configured")
        payload = {
            "model": self._model_name(profile),
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=settings.model_timeout_seconds) as client:
            r = await client.post(f"{profile.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        return ModelResult(
            model=profile.model_id, provider=profile.provider,
            content=data["choices"][0]["message"]["content"], usage=data.get("usage", {}),
        )

    async def _anthropic(self, profile, messages, temperature) -> ModelResult:
        """Anthropic Messages API: ``x-api-key`` + ``anthropic-version`` headers, a required
        ``max_tokens``, the system prompt as a top-level field (not a message), and the reply in
        ``content[].text`` rather than the OpenAI ``choices`` shape."""
        base = profile.base_url or "https://api.anthropic.com"
        if not profile.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        system_parts = [m.content for m in messages if m.role == "system"]
        convo = [
            {"role": ("assistant" if m.role == "assistant" else "user"), "content": m.content}
            for m in messages if m.role != "system"
        ]
        payload = {
            "model": self._model_name(profile),
            "max_tokens": settings.model_max_output_tokens,
            "temperature": temperature,
            "messages": convo,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": profile.api_key,
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=settings.model_timeout_seconds) as client:
            r = await client.post(f"{base.rstrip('/')}/v1/messages", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        u = data.get("usage", {}) or {}
        return ModelResult(
            model=profile.model_id, provider=profile.provider, content=text,
            usage={"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")},
        )

    async def _azure(self, profile, messages, temperature) -> ModelResult:
        """Azure OpenAI uses a deployment-scoped path and the ``api-key`` header
        with an ``api-version`` query parameter — not the OpenAI bearer scheme."""
        if not profile.base_url or not profile.deployment:
            raise RuntimeError("AZURE_OPENAI_BASE_URL and AZURE_OPENAI_DEPLOYMENT must be configured")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
        url = (
            f"{profile.base_url.rstrip('/')}/openai/deployments/{profile.deployment}"
            f"/chat/completions?api-version={api_version}"
        )
        headers = {"Content-Type": "application/json"}
        if profile.api_key:
            headers["api-key"] = profile.api_key
        payload = {"messages": [m.model_dump() for m in messages], "temperature": temperature}
        async with httpx.AsyncClient(timeout=settings.model_timeout_seconds) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        return ModelResult(
            model=profile.model_id, provider=profile.provider,
            content=data["choices"][0]["message"]["content"], usage=data.get("usage", {}),
        )


registry = ModelRegistry()
client = ModelClient()
