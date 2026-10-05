# Configuration

## API keys

Keys are looked up in this order ([src/ai_pc/core/keys.py](../src/ai_pc/core/keys.py)):

1. the environment, e.g. `NEBIUS_API_KEY`
2. a `.env` file in the project folder (git-ignored; start from [.env.example](../.env.example))
3. this PC's encrypted vault: `ai-pc keys set NEBIUS_API_KEY` (Windows DPAPI: only this Windows user on this PC can
   read it; `ai-pc keys list` shows the names, never the keys)
4. a legacy `my_nebius.txt` in the project folder (git-ignored; prefer 2 or 3)

Keys are never printed, logged, saved in chats or sent to a model. Keys for work apps, social media and accounting
programs are added with each program's `connect` command (`ai-pc hub connect slack`, `ai-pc social connect facebook`,
`ai-pc accounts connect quickbooks`) and kept in the same vault.

## Where data lives

Everything stays inside the project folder ([src/ai_pc/core/paths.py](../src/ai_pc/core/paths.py)); none of it is in
the repository. Set `AI_PC_HOME` to keep it in another folder.

| Folder | What is in it |
|---|---|
| `tools/` | portable programs the agents drive ([tools](tools.md)) and reviewed downloads (`tools/review/`) |
| `models/` | local models: Whisper (speech), YuNet (faces), the click models, Hugging Face cache |
| `media/` | sample and test media |
| `out/` | everything the programs make, each in its own folder (`out/video`, `out/docs`, `out/aipc/chats` ...) |
| `state/` | learned skills, caches, the encrypted key vault (`state/hub/vault.bin`) and its audit log |
| `kb/` | the video knowledge base, built on this PC from the installed editors' catalogues |
| `runs/` | the desktop agent's run logs and screenshots |

## Settings files

| File | Settings |
|---|---|
| `out/aipc/bar.json` | the command bar: `hotkey` (default `ctrl+alt+space`), fallbacks, `theme` (`auto`, `light`, `dark`), `notify`, `resume_hours` |
| [src/ai_pc/core/config.py](../src/ai_pc/core/config.py) | the model for each role, prices, limits, the programs the desktop agent never controls |

## Language models

Most requests are read by rules and never reach a model. The rest go to one provider, chosen once
([src/ai_pc/llm/providers.py](../src/ai_pc/llm/providers.py)). The default is Nebius Token Factory, where every role
(fast replies, vision, planning, documents) uses `zai-org/GLM-5.3-Flash`, the cheapest model on that account that also
reads images, with `reasoning_effort: low`. The choice and its measurements are in `config.py`;
`scripts/bench_models.py` re-runs the benchmark.

Any provider with an OpenAI-compatible Chat Completions API can take its place. These have presets: the address, the
key's name and a low-cost default model that reads images (checked against each provider's documentation on
5 October 2026; models change often, so `ai-pc models list <provider>` shows what one offers today):

| Preset | Provider | Key | Default model |
|---|---|---|---|
| `nebius` | [Nebius Token Factory](https://docs.tokenfactory.nebius.com) | `NEBIUS_API_KEY` | `zai-org/GLM-5.3-Flash` |
| `openai` | [OpenAI](https://developers.openai.com/api/docs) | `OPENAI_API_KEY` | `gpt-6-luna` |
| `gemini` | [Google Gemini](https://ai.google.dev/gemini-api/docs/openai) | `GEMINI_API_KEY` | `gemini-3.5-flash-lite` |
| `mistral` | [Mistral AI](https://docs.mistral.ai) | `MISTRAL_API_KEY` | `ministral-8b-latest` |
| `groq` | [Groq](https://console.groq.com/docs/openai) | `GROQ_API_KEY` | `qwen/qwen3.8-27b` |
| `together` | [Together AI](https://docs.together.ai/docs/openai-api-compatibility) | `TOGETHER_API_KEY` | `Qwen/Qwen3.5-9B` |
| `fireworks` | [Fireworks AI](https://docs.fireworks.ai/tools-sdks/openai-compatibility) | `FIREWORKS_API_KEY` | `accounts/fireworks/models/glm-5p3-flash` |
| `deepinfra` | [DeepInfra](https://docs.deepinfra.com/chat/overview) | `DEEPINFRA_API_KEY` | `zai-org/GLM-5.3-Flash` |
| `openrouter` | [OpenRouter](https://openrouter.ai/docs/quickstart) | `OPENROUTER_API_KEY` | `z-ai/glm-5.3-flash` |
| `huggingface` | [Hugging Face](https://huggingface.co/docs/inference-providers/index) | `HF_TOKEN` | `Qwen/Qwen3.5-9B` |
| `deepseek` | [DeepSeek](https://api-docs.deepseek.com) | `DEEPSEEK_API_KEY` | `deepseek-flash` |
| `qwen` | [Alibaba Cloud (Qwen)](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions) | `DASHSCOPE_API_KEY` | `qwen3.7-flash` |
| `zai` | [Z.ai (GLM)](https://docs.z.ai/guides/develop/openai/python) | `ZAI_API_KEY` | `glm-5.3-flash` |
| `moonshot` | [Moonshot AI (Kimi)](https://platform.kimi.ai/docs) | `MOONSHOT_API_KEY` | `kimi-k2.6` |
| `xai` | [xAI (Grok)](https://docs.x.ai/developers/quickstart) | `XAI_API_KEY` | `grok-4.3` |
| `cerebras` | [Cerebras](https://inference-docs.cerebras.ai/resources/openai) | `CEREBRAS_API_KEY` | `qwen-3.8-27b` |
| `sambanova` | [SambaNova](https://docs.sambanova.ai/docs/en/get-started/api-keys-urls) | `SAMBANOVA_API_KEY` | `gemma-4-31B-it` |
| `nvidia` | [NVIDIA NIM](https://build.nvidia.com) | `NVIDIA_API_KEY` | `z-ai/glm-5.3-flash` |
| `novita` | [Novita AI](https://docs.novita.ai/api-reference/model-apis-llm-create-chat-completion) | `NOVITA_API_KEY` | `google/gemma-4-26b-a4b-it` |
| `cohere` | [Cohere](https://docs.cohere.com/docs/compatibility-api) | `COHERE_API_KEY` | `command-r7b-12-2024` |
| `siliconflow` | [SiliconFlow](https://docs.siliconflow.com/en/userguide/quickstart) | `SILICONFLOW_API_KEY` | `Qwen/Qwen3-VL-8B-Instruct` |
| `ollama` | [Ollama (on this PC)](https://docs.ollama.com/api/openai-compatibility) | none | `qwen3-vl:8b` |
| `lmstudio` | [LM Studio (on this PC)](https://lmstudio.ai/docs/developer/openai-compat) | none | `google/gemma-3-4b` |
| `llamacpp` | [llama.cpp server (on this PC)](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | none | `local` |
| `vllm` | [vLLM (on this PC)](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) | none | choose one |
| `custom` | any other OpenAI-compatible server | `AI_PC_API_KEY` | choose one |

```powershell
ai-pc models                                     # the presets, and whose key is set
ai-pc keys set GROQ_API_KEY                      # the provider's key, kept in the vault like the others
ai-pc models use groq                            # from now on (saved in state/models.json)
ai-pc models use openrouter --model z-ai/glm-5.3-flash --price 0.15,0.5
ai-pc models use ollama --model qwen3-vl:8b      # a model on this PC: no key, nothing leaves the PC
ai-pc models use custom --base-url https://llm.example.com/v1 --model my-model
ai-pc models show                                # the provider and the model each role uses now
ai-pc models test                                # one short request: does it answer, and how fast
ai-pc models reset                               # back to Nebius
```

The environment wins over the saved choice: `AI_PC_PROVIDER`, `AI_PC_MODEL` (every role), `AI_PC_MODEL_<ROLE>`
(`FAST`, `VISION`, `DEEP`, `VIDEO`, `ANNOTATE`, `CAPTION`, `DOCS`) and `AI_PC_BASE_URL`.

How requests differ between providers:

- Each preset sends its own switches: thinking turned off where a provider allows it (DeepSeek, Moonshot, Alibaba's
  Qwen), a low reasoning effort for OpenAI and Gemini. A model that refuses a switch is asked again without it.
- Some APIs do not take every optional field: Mistral has no streaming usage counts, Moonshot and OpenAI's current
  models take no `temperature`, and OpenAI wants `max_completion_tokens`. The presets leave those out; with any other
  server, a field it refuses once (`stream_options`, `response_format`, `temperature`) is never sent to it again.
- The desktop agent's vision and the picture checks send images, so pick a model that reads them. Cohere's preset is
  text only.
- Costs are counted for the Nebius models in `config.py`, and for any model given a price with `--price` (US dollars
  per million tokens, input and output). Other models count as free in the cost line of each reply.

## Environment variables

| Variable | Effect |
|---|---|
| `NEBIUS_API_KEY` | the default model provider's key (each provider has its own: `OPENAI_API_KEY`, `GROQ_API_KEY` ...) |
| `AI_PC_PROVIDER`, `AI_PC_MODEL`, `AI_PC_MODEL_<ROLE>`, `AI_PC_BASE_URL` | the model provider and models; see [Language models](#language-models) |
| `AI_PC_HOME` | the folder that holds tools, models, media, outputs and state |
| `AI_PC_BAR_HOME` | another folder for the command bar's settings and log (used by tests) |
| `CUA_GROUNDER` | the desktop agent's click model: `vocaela` (default) or `tinyclick` |
