# 0005. Any OpenAI-compatible model provider

- Status: accepted
- Date: 2026-10-05

## Context

Every model call went to one provider (Nebius Token Factory). The client already spoke the OpenAI Chat Completions
protocol, which most providers and local model servers offer. People have keys with other providers, some want a
model on their own PC, and a provider's prices, models and speed change month to month (one model's median answer
went from 3 s to 40 s in a day).

## Decision

Model calls go to one provider chosen by the user: a preset (address, key name, default model, the request switches
it needs) or any other OpenAI-compatible address. The choice lives in `state/models.json` (`ai-pc models use`) and can
be overridden by environment variables. Each role (fast, vision, deep ...) can have its own model. Nebius with
GLM-5.3-Flash stays the default, with the settings it was tuned with.

## Consequences

- Switching provider is one command, and a model on the PC (Ollama, LM Studio, llama.cpp, vLLM) keeps every request
  on the PC.
- The rules-first design is unchanged: most requests still need no model.
- Providers differ in small ways (fields they refuse, thinking switches, image formats). Presets carry what is known;
  for the rest the client drops an optional field a provider refuses, once.
- Presets age as providers retire models, so each names its documentation and `ai-pc models list` shows what a
  provider offers today.
- Costs are only known for models with a price in `config.py` or one given with `--price`.
