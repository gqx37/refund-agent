# app/agent/llm.py

"""The reasoning core: Nemotron 3 Ultra, hosted on Fireworks.

The harness thesis in one line: the model is "good enough," and the engineering
value is everything around it — grounding it on facts, giving it tools, and
fencing it with deterministic guardrails. So this file is intentionally tiny. We
bind the model at temperature 0 because in this design the LLM extracts and
phrases; it does not decide, and we have no use for variance we can't act on.
"""

from __future__ import annotations

from langchain_fireworks import ChatFireworks

from app.config import LLMConfig


def build_llm(config: LLMConfig) -> ChatFireworks:
    return ChatFireworks(
        model=config.model,  # type: ignore[call-arg]  # `model` is the populate-by-name alias of model_name
        temperature=config.temperature,
        api_key=config.api_key,
    )
