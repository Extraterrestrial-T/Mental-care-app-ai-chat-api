# Qwen3 32B Dense on a Cloud Run L4

This deployment uses Qwen3's dense 32B model for the Corner Health inference
endpoint. It replaces the failed 30B-A3B mixture-of-experts deployment without
requiring a custom vLLM engine build.

## Chosen runtime

- Model: `unsloth/Qwen3-32B-bnb-4bit`
- Runtime image: vLLM `v0.8.5`, pinned by digest, with a small startup proxy
- CUDA runtime: 12.4, validated against the Cloud Run L4 before model loading
- GPU: one Cloud Run NVIDIA L4 (24 GB VRAM)
- Capacity: one request and one vLLM sequence at a time
- Context window: 1,024 tokens initially

The earlier Qwen3 30B-A3B deployment reached model initialization but failed
with `FusedMoE ... quant_method is not None`: an unsupported BitsAndBytes MoE
path in vLLM 0.8.5. Qwen3-32B is dense, so it does not use that path. Qwen
documents Qwen3-32B for vLLM 0.8.5 or newer. Its 4-bit weights are close to an
L4's 24-GiB VRAM limit, so this deployment deliberately starts with one
sequence and a 1,024-token context window.

The vLLM Docker entrypoint is its OpenAI API server. The deployment passes
`--model=/models/...` directly and must not add `vllm serve` to the container
arguments.

Cloud Run limits startup probes to 240 seconds. Reading this model from GCS
FUSE takes longer, so the proxy opens the public port immediately and starts
vLLM on a private port. Until model loading completes, it returns HTTP 503 with
`Retry-After: 15`; the application must retry rather than treating that response
as a model error.

The model cache job writes the Hugging Face snapshot to the existing Cloud
Storage bucket. The serving service mounts the snapshot read-only. This avoids
downloading the model during Cloud Run's four-minute startup probe window. It
uses the new `qwen3-32b-bnb-4bit-v1` prefix so its files cannot mix with
earlier Gemma, MoE, or GPTQ caches.

## Prerequisites

- `care-llm-sa@mental-479910.iam.gserviceaccount.com` needs read/write access
  to `gs://lecunbuckett` for the cache job, then read access for the service.
- The existing Secret Manager secret `hf-token` must be readable by that
  service account. The model is public, but the token avoids Hugging Face rate
  limits during download.

## Deploy

From the repository root in Cloud Shell:

```bash
chmod +x infra/llm/qwen3-l4/*.sh
gcloud builds submit \\
  --project=mental-479910 \\
  --config=infra/llm/qwen3-l4/cloudbuild.startup-proxy.yaml \\
  infra/llm/qwen3-l4
./infra/llm/qwen3-l4/deploy-diagnostic.sh
./infra/llm/qwen3-l4/cache-model.sh
./infra/llm/qwen3-l4/deploy-service.sh
./infra/llm/qwen3-l4/smoke-test.sh
```

The cache job uses one downloader worker and 8 GiB of memory because GCS FUSE
stages large Xet-hosted model shards before committing them to the bucket. It
can be rerun safely after an interrupted download. Do not deploy the service
until the job completes and writes `config.json` under the model directory.

Only after this Qwen service passes the smoke test, remove the incorrect old
caches to avoid storage charges:

```bash
gcloud storage rm --recursive gs://lecunbuckett/qwen3-30b-a3b-bnb-4bit
gcloud storage rm --recursive gs://lecunbuckett/qwen3-30b-a3b-bnb-4bit-v2
```

## Chat behavior

Qwen3 thinks by default. The smoke test passes
`chat_template_kwargs: {"enable_thinking": false}` so its hidden reasoning is
disabled. The application should send the same field for the user-facing health
chatbot.

## Failure handling

- The diagnostic deployment must print CUDA `12.4`, `True`, and `1`, with no
  CUDA 803 error. Do not cache or deploy the model if it does not.
- If model loading runs out of VRAM at 1,024 tokens and 0.90 utilization, this
  32B 4-bit checkpoint is not viable on one L4. Do not increase Cloud Run
  concurrency or context length before it has a successful smoke test.
