"""The one way this system talks to a model.

Every call is structured: a versioned prompt, documents fenced as untrusted
data, and a Pydantic schema the response must validate against. Nothing here
returns free text for another module to parse.

Every call also returns a `RunMeta`, which is what `agent_run` stores and what
each resulting event cites in `model_ref`. A number in the ledger can therefore
be traced back to the exact prompt version and model that produced it.

Two deviations from the Phase 1 plan, both forced by the current API:

  - **No `temperature=0`.** Sampling parameters were removed; sending
    `temperature` returns a 400 on every current model. Determinism comes from
    the response cache instead, which is stronger anyway — it reproduces the
    exact bytes rather than hoping for a stable sample.
  - **Structured output, not tool schemas.** `messages.parse()` with a Pydantic
    model is the supported path and validates the response for us. Forced
    `tool_choice` returns a 400 on Opus 5.5, so a tool-schema approach would
    need rewriting regardless.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel

from .cache import ResponseCache, cache_key
from .registry import PromptRegistry
from .untrusted import fence_all
from .usage import Usage, UsageLog, cost_usd

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000

# Effort defaults to "medium" on Opus 5.5 — one level below the older default —
# so it is always set explicitly rather than inherited.
DEFAULT_EFFORT = "high"

T = TypeVar("T", bound=BaseModel)


def schema_ref(output_model: Type[BaseModel]) -> str:
    """The output schema as the cache key sees it: its name and a hash of its
    shape. The name alone let an answer cached under an older shape (a field
    that was free text, now a closed set) be served after the schema changed."""
    shape = json.dumps(output_model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return "%s@%s" % (output_model.__name__, hashlib.sha256(shape.encode()).hexdigest()[:12])


class LLMError(RuntimeError):
    pass


class ModelRefused(LLMError):
    """Safety classifiers declined the request. Arrives as HTTP 200 with
    stop_reason "refusal", so it must be checked rather than caught."""

    def __init__(self, category: Optional[str], explanation: str = ""):
        self.category = category
        super().__init__("model refused (%s): %s" % (category, explanation))


@dataclass(frozen=True)
class RunMeta:
    prompt_ref: str
    model: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def model_ref(self) -> str:
        """Written onto every event this call produced."""
        return "%s/%s" % (self.model, self.prompt_ref)


def _default_cache_dir() -> str:
    """Where cached bodies live. A setting, because the API runs in a container
    whose working directory is not writable and whose cache must be the same
    one the eval warms on the host."""
    try:
        from ..settings import get_settings
        return get_settings().llm_cache_dir
    except Exception:  # noqa: BLE001 - a cache path must never stop a call
        return ".cache/llm"


# Committed answers (cache.ResponseCache's `replay`): the repository's, so it
# resolves from this file rather than from whatever directory the process
# started in. LEASEDESK_LLM_REPLAY_DIR moves it: the image keeps it at
# /app/reference/llm_cache, because Compose mounts the generated data over
# /app/data and would hide anything the image put there.
REPLAY_DIR = Path(os.environ.get("LEASEDESK_LLM_REPLAY_DIR")
                  or Path(__file__).resolve().parents[3] / "data" / "reference" / "llm_cache")


class LLM:
    def __init__(
        self,
        registry: Optional[PromptRegistry] = None,
        cache: Optional[ResponseCache] = None,
        usage: Optional[UsageLog] = None,
        client=None,
        model: str = MODEL,
        timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self.registry = registry or PromptRegistry()
        self.cache = cache or ResponseCache(Path(_default_cache_dir()), replay=REPLAY_DIR)
        self.usage = usage or UsageLog()
        self.model = model
        # Retries are the SDK's job: it already backs off on 429, 5xx and
        # connection errors. Hand-rolling a second layer just multiplies waits.
        self._client = client or self._build_client(timeout, max_retries)

    @staticmethod
    def _build_client(timeout: float, max_retries: int):
        import anthropic

        return anthropic.Anthropic(timeout=timeout, max_retries=max_retries)

    def structured(
        self,
        prompt_id: str,
        output_model: Type[T],
        variables: Optional[Dict[str, object]] = None,
        documents: Optional[List[Tuple[str, str]]] = None,
        version: Optional[int] = None,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = MAX_TOKENS,
        clinic_id: Optional[str] = None,
        period: Optional[str] = None,
    ) -> Tuple[T, RunMeta]:
        """Run one task. Returns the validated result and what to audit.

        `documents` are (source, text) pairs; they are fenced as untrusted data
        before the model sees them.
        """
        prompt = self.registry.get(prompt_id, version)
        system = prompt.render(variables)
        user = fence_all(documents or [])

        # Keyed on the documents, not on `user`: the fence draws a fresh random
        # nonce every call (it has to stay unguessable to whoever wrote the
        # document), so a key over the fenced text meant a call with documents
        # could never be a cache hit.
        key = cache_key(
            self.model,
            prompt.ref,
            {"system": system, "documents": [list(d) for d in documents or []], "effort": effort},
            schema_ref(output_model),
        )

        cached = self.cache.get(key)
        if cached is not None:
            meta = RunMeta(prompt.ref, self.model, True, 0, 0, 0.0)
            self._log(meta, clinic_id, period)
            return output_model.model_validate(cached), meta

        response = self._call(system, user, output_model, effort, max_tokens)
        self._check_refusal(response)

        parsed = response.parsed_output
        self.cache.put(key, parsed.model_dump(mode="json"))

        tokens_in = getattr(response.usage, "input_tokens", 0)
        tokens_out = getattr(response.usage, "output_tokens", 0)
        meta = RunMeta(
            prompt_ref=prompt.ref,
            model=self.model,
            cache_hit=False,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=cost_usd(self.model, tokens_in, tokens_out),
        )
        self._log(meta, clinic_id, period)
        return parsed, meta

    def _call(self, system: str, user: str, output_model, effort: str, max_tokens: int):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_format": output_model,
            # Adaptive thinking: the model decides depth. It cannot be disabled
            # on Opus 5.5 — lower `effort` instead.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
        }
        try:
            return self._client.messages.parse(**kwargs)
        except Exception as exc:
            raise LLMError(self._explain(exc)) from exc

    @staticmethod
    def _check_refusal(response) -> None:
        if getattr(response, "stop_reason", None) != "refusal":
            return
        details = getattr(response, "stop_details", None)
        raise ModelRefused(
            getattr(details, "category", None),
            getattr(details, "explanation", "") or "",
        )

    @staticmethod
    def _explain(exc: Exception) -> str:
        """Name the failure so a run log says what to do about it."""
        try:
            import anthropic
        except ImportError:
            return "llm call failed: %s" % exc

        if isinstance(exc, anthropic.NotFoundError):
            return "model or endpoint not found: %s" % exc
        if isinstance(exc, anthropic.RateLimitError):
            return "rate limited after retries: %s" % exc
        if isinstance(exc, anthropic.AuthenticationError):
            return "ANTHROPIC_API_KEY missing or rejected: %s" % exc
        if isinstance(exc, anthropic.APIStatusError):
            return "api returned %s: %s" % (exc.status_code, exc)
        if isinstance(exc, anthropic.APIConnectionError):
            return "could not reach the api: %s" % exc
        return "llm call failed: %s" % exc

    def _log(self, meta: RunMeta, clinic_id, period) -> None:
        self.usage.record(
            Usage(
                prompt_ref=meta.prompt_ref,
                model=meta.model,
                cache_hit=meta.cache_hit,
                input_tokens=meta.input_tokens,
                output_tokens=meta.output_tokens,
                cost_usd=meta.cost_usd,
                clinic_id=clinic_id,
                period=period,
            )
        )
