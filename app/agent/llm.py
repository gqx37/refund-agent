# Nemotron 3 Ultra on Fireworks. temperature 0: the LLM extracts and phrases, it
# does not decide, so there's no variance worth buying.

from __future__ import annotations

from langchain_fireworks import ChatFireworks

from app.config import LLMConfig


def build_llm(config: LLMConfig) -> ChatFireworks:
    return ChatFireworks(
        model=config.model,  # type: ignore[call-arg]  # populate-by-name alias of model_name
        temperature=config.temperature,
        api_key=config.api_key,
    )
