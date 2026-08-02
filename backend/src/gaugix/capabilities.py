"""What a given model will actually accept (reasoning effort, temperature, …).

Generation params reach the provider by being spread straight into the
completion call, so any key litellm understands already works. The problem that
solves nothing is *discovery*: `reasoning_effort` is meaningful on o-series,
gpt-5, Claude and Gemini 2.5 and rejected outright by gpt-4o-mini, and nobody
should have to remember which is which.

litellm already tracks this per model, so we ask it rather than keeping a table
that would be wrong within a month. Same bundled-data rule as pricing (D-023):
no network, and an honest "unknown" when litellm has never heard of the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gaugix.domain import Provider

#: The params worth a dedicated control rather than a line of JSON.
FIRST_CLASS = ("reasoning_effort", "temperature", "max_tokens", "thinking")

#: Effort levels every provider that supports the param accepts. `minimal` is
#: OpenAI-only and `none` is Gemini-only, so neither is offered here — the JSON
#: escape hatch takes them, and a provider that refuses one says so plainly.
EFFORT_LEVELS = ("low", "medium", "high")


@dataclass(slots=True)
class ModelCapabilities:
    model_id: str
    #: None when litellm does not recognise the model at all — which is not the
    #: same as "supports nothing", and must not be rendered as a locked-down form.
    supported: list[str] | None = None
    effort_levels: list[str] = field(default_factory=lambda: list(EFFORT_LEVELS))

    @property
    def known(self) -> bool:
        return self.supported is not None

    def allows(self, param: str) -> bool:
        # Unknown model → let the user try. Being wrong is recoverable; being
        # unable to set a param the model does support is not.
        return True if self.supported is None else param in self.supported


def capabilities_for(model_id: str, provider: str) -> ModelCapabilities:
    """Ask litellm which OpenAI-shaped params this model accepts."""
    caps = ModelCapabilities(model_id=model_id)
    if not model_id or provider == Provider.fake:
        return caps
    if provider == Provider.openai_compatible:
        # Behind an OpenAI-shaped URL could be vLLM, Ollama, a proxy or a
        # gateway, running any model under any name. litellm would answer with
        # the generic OpenAI list, which is a guess dressed as a fact — so stay
        # permissive and let the endpoint speak for itself.
        return caps

    try:
        import litellm

        supported = litellm.get_supported_openai_params(
            model=model_id, custom_llm_provider=provider
        )
    except Exception:
        # An unrecognised model, or a litellm version that cannot answer. Either
        # way the honest reply is "we don't know", not "nothing is supported".
        return caps

    if supported is None:
        return caps
    caps.supported = sorted(str(param) for param in supported)
    return caps
