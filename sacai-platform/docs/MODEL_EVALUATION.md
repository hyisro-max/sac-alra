# Tool-calling model evaluation

Production remains on the staged Qwen vision/coder models until a replacement
wins this repository's actual schema test. General chat benchmarks are not an
acceptance criterion.

## Candidate policy

On a connected dual-H100 staging host, evaluate the current models plus recent
Ollama-compatible candidates whose official model card documents tool use. At
minimum include the current Qwen models and one alternative such as `gpt-oss`
only after checking its official license/model card. Ollama documents the native
`tools` request and `message.tool_calls` response at
`https://docs.ollama.com/capabilities/tool-calling`; Qwen's official Qwen3 post
documents tool-agent support at `https://qwenlm.github.io/blog/qwen3/`.

Do not rely on a model-library tag as proof of license, architecture support, or
complete offline transfer. Record the exact tag, manifest digest, quantization,
context size, Ollama version, official license URL, and total blob bytes.

## Run the checked-in harness

```bash
cd sacai-platform
python3 model-eval/run_tool_eval.py \
  --model qwen3-vl:30b-a3b \
  --cases model-eval/cases.jsonl \
  --output model-eval/results/qwen3-vl.json
```

Run each model three times at temperature zero. The harness scores exact tool
selection, required argument keys/values, forbidden path arguments, and cases
where no tool should be called. Manually inspect multi-step job polling and all
failures. A candidate must reach 100% on safety-critical `must_not_call` and
filepath cases and materially improve total exact-call accuracy without
regressing vision needs. Add ambiguous, failed, and real employee phrasings to
`cases.jsonl`; do not tune only to public benchmarks.

## Offline proof

Stop Ollama, copy the complete `.ollama` tree to clean disconnected storage,
load the same pinned Ollama image, start with egress disabled, and rerun the
suite. A candidate is ineligible if any blob is fetched, its license disallows
deployment, it cannot fit under the configured dual-H100 concurrency, or the
offline score differs. Append the result path and chosen/rejected reason to
`BUILD_LOG.md` before changing a production model.

