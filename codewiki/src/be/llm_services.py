"""
LLM service factory for creating configured LLM clients.

Includes a compatibility layer for OpenAI-compatible API proxies that may
return slightly non-standard responses (e.g. choices[].index = None).

Supports multiple providers: openai-compatible, anthropic, bedrock, azure-openai.
"""
import logging
from typing import Optional
from openai.types import chat

from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.usage import UsageLimits
from openai import OpenAI, BadRequestError

from codewiki.src.config import Config

logger = logging.getLogger(__name__)


def _should_use_max_completion_tokens(model_name: str, base_url: str) -> bool:
    """
    Determine whether to use max_completion_tokens instead of max_tokens.

    Newer OpenAI models (o1, o3, o4, gpt-4o, gpt-5, etc.) require
    max_completion_tokens. Anthropic and other providers still use max_tokens.
    """
    model_lower = model_name.lower()
    # OpenAI models that require max_completion_tokens
    new_openai_patterns = ("o1", "o3", "o4", "gpt-4o", "gpt-4-turbo", "gpt-5")
    if any(pattern in model_lower for pattern in new_openai_patterns):
        return True
    # If base_url points to OpenAI directly, newer models may need it
    if base_url and "api.openai.com" in base_url:
        return True
    return False


def build_usage_limits(config: Config, sub: bool = False) -> Optional[UsageLimits]:
    """Agent request budget for the pydantic-ai loop.

    Top-level modules use ``config.request_limit``; sub-module agents use
    ``config.sub_request_limit`` when set, else they inherit ``request_limit``.
    Returns ``None`` when no budget is enforced (e.g. the subscription/caw path).
    Shared by the module backend and the sub-module delegation tool so the budget
    is defined in exactly one place.
    """
    request_limit = getattr(config, "request_limit", None)
    if sub:
        sub_limit = getattr(config, "sub_request_limit", None)
        if sub_limit is not None:
            request_limit = sub_limit
    if request_limit is None:
        return None
    return UsageLimits(request_limit=request_limit)


def _param_style_for(config: Config, model_name: str) -> str:
    """Resolve the token-limit parameter for *model_name*: ``max_tokens`` vs ``max_completion_tokens``.

    Precedence: a resolved :class:`ModelProfile` (Stage 2) wins; otherwise an explicit
    non-default ``config.token_param_style`` wins; otherwise fall back to substring
    auto-detection so newer OpenAI models (gpt-4o/o1/...) keep working. The
    ``call_llm`` BadRequestError retry remains the final net for gateway-renamed ids.
    """
    profile = getattr(config, "profile", None)
    if profile is not None and getattr(profile, "token_param_style", None) in (
        "max_tokens",
        "max_completion_tokens",
    ):
        return profile.token_param_style
    style = getattr(config, "token_param_style", "max_tokens")
    if style == "max_completion_tokens":
        return "max_completion_tokens"
    return (
        "max_completion_tokens"
        if _should_use_max_completion_tokens(model_name, config.llm_base_url)
        else "max_tokens"
    )


def _temperature_for(config: Config) -> Optional[float]:
    """Temperature to send, or ``None`` to omit the parameter entirely.

    A resolved profile may declare ``temperature=None`` for reasoning models that
    reject an explicit temperature; without a profile we preserve the legacy 0.0.
    """
    profile = getattr(config, "profile", None)
    if profile is not None:
        return profile.temperature
    return 0.0


def _build_model_settings(config: Config, model_name: str) -> OpenAIModelSettings:
    """Build model settings with the correct token parameter and temperature.

    Token-param style and temperature are profile-driven (with safe fallbacks);
    temperature is omitted entirely when the profile declares it ``None``.
    """
    kwargs = {_param_style_for(config, model_name): config.max_tokens}
    temperature = _temperature_for(config)
    if temperature is not None:
        kwargs["temperature"] = temperature
    return OpenAIModelSettings(**kwargs)


def _get_litellm_model_name(model_name: str, provider: str, litellm_prefix: Optional[str] = None) -> str:
    """
    Get the litellm-compatible model name for a given provider.

    Prefers an explicit ``litellm_prefix`` (from the resolved ModelProfile) when set;
    otherwise falls back to the provider-based prefix heuristic. For Bedrock, prefixes
    'bedrock/'; for Anthropic, 'anthropic/' — when not already prefixed.
    """
    if litellm_prefix:
        return model_name if model_name.startswith(litellm_prefix) else f"{litellm_prefix}{model_name}"
    if provider == "bedrock":
        if not model_name.startswith("bedrock/"):
            return f"bedrock/{model_name}"
    elif provider == "anthropic":
        if not model_name.startswith("anthropic/"):
            return f"anthropic/{model_name}"
    return model_name


class CompatibleOpenAIModel(OpenAIModel):
    """OpenAIModel subclass that patches non-standard API proxy responses.

    Some OpenAI-compatible proxies return responses with fields like
    choices[].index set to None instead of an integer. This subclass
    fixes those fields before pydantic validation runs.
    """

    def _validate_completion(self, response: chat.ChatCompletion) -> chat.ChatCompletion:
        # Patch choices[].index: None -> sequential integer (0, 1, 2, ...)
        if response.choices:
            for i, choice in enumerate(response.choices):
                if choice.index is None:
                    choice.index = i
        return super()._validate_completion(response)


def _create_litellm_openai_client(config: Config) -> OpenAI:
    """
    Create an OpenAI-compatible client backed by litellm's proxy.

    litellm translates OpenAI API calls to Bedrock, Anthropic, etc.
    """
    import litellm
    # Configure litellm for the provider
    if config.provider == "bedrock":
        import os
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)

    # litellm exposes an OpenAI-compatible Router we can use,
    # but the simplest path is to use litellm.completion() directly.
    # For pydantic-ai integration, we create a proxy client.
    return OpenAI(
        api_key=config.llm_api_key or "not-needed-for-bedrock",
        base_url=config.llm_base_url or "https://api.openai.com/v1",
    )


def create_main_model(config: Config) -> CompatibleOpenAIModel:
    """Create the main LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.main_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.main_model)
    )


def create_fallback_model(config: Config) -> CompatibleOpenAIModel:
    """Create the fallback LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.fallback_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.fallback_model)
    )


def create_fallback_models(config: Config) -> FallbackModel:
    """Create fallback models chain from configuration."""
    main = create_main_model(config)
    fallback = create_fallback_model(config)
    return FallbackModel(main, fallback)


def create_openai_client(config: Config) -> OpenAI:
    """Create OpenAI client from configuration."""
    return OpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key
    )


def call_llm(
    prompt: str,
    config: Config,
    model: str = None,
    temperature: float = 0.0
) -> str:
    """
    Call LLM with the given prompt.

    Supports openai-compatible, anthropic, and bedrock providers.
    For bedrock/anthropic, uses litellm to translate the API call.

    Args:
        prompt: The prompt to send
        config: Configuration containing LLM settings
        model: Model name (defaults to config.main_model)
        temperature: Temperature setting

    Returns:
        LLM response text
    """
    if model is None:
        model = config.main_model

    provider = getattr(config, "provider", "openai-compatible")

    if provider in ("bedrock", "anthropic"):
        return _call_llm_via_litellm(prompt, config, model, temperature)

    if provider == "azure-openai":
        return _call_llm_via_azure(prompt, config, model, temperature)

    # Default: OpenAI-compatible
    client = create_openai_client(config)

    # Use the correct token parameter based on model/provider; if the server
    # rejects our choice, swap to the other token kwarg and retry once.
    use_completion_tokens = _should_use_max_completion_tokens(model, config.llm_base_url)
    primary_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
    fallback_key = "max_tokens" if use_completion_tokens else "max_completion_tokens"

    base_kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }

    try:
        response = client.chat.completions.create(
            **base_kwargs,
            **{primary_key: config.max_tokens},
        )
    except BadRequestError as e:
        if _is_unsupported_token_param_error(e, primary_key):
            logger.info(
                "Provider rejected %s for model %s; retrying with %s.",
                primary_key, model, fallback_key,
            )
            response = client.chat.completions.create(
                **base_kwargs,
                **{fallback_key: config.max_tokens},
            )
        else:
            raise
    return response.choices[0].message.content


def _is_unsupported_token_param_error(err: BadRequestError, param: str) -> bool:
    """Return True if *err* is the OpenAI "unsupported_parameter" error for *param*."""
    body = getattr(err, "body", None) or {}
    if isinstance(body, dict):
        error = body.get("error") or {}
        if isinstance(error, dict):
            if error.get("param") == param and error.get("code") == "unsupported_parameter":
                return True
    # Fallback: message-based sniff for proxies that don't preserve structure
    msg = str(err).lower()
    return "unsupported parameter" in msg and param in msg


def _call_llm_via_litellm(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via litellm for Bedrock/Anthropic providers.

    litellm handles the provider-specific API translation automatically.
    """
    import litellm
    import os

    litellm_model = _get_litellm_model_name(model, config.provider, getattr(config, "litellm_prefix", None))

    if config.provider == "bedrock":
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)
        logger.debug("Calling Bedrock model %s in region %s", litellm_model, config.aws_region)
    elif config.provider == "anthropic":
        logger.debug("Calling Anthropic model %s via litellm", litellm_model)

    response = litellm.completion(
        model=litellm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
        api_key=config.llm_api_key if config.provider != "bedrock" else None,
    )
    return response.choices[0].message.content


def _call_llm_via_azure(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via Azure OpenAI.

    Uses the AzureOpenAI client from the openai package with
    azure_endpoint, api_version, and deployment name.
    """
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=config.llm_api_key,
        api_version=config.api_version,
        azure_endpoint=config.llm_base_url,
    )

    deployment = config.azure_deployment or model
    logger.debug("Calling Azure OpenAI deployment %s (api_version=%s)", deployment, config.api_version)

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content
