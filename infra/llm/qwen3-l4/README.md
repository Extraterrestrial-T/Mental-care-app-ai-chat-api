# Qwen3 30B-A3B on a Cloud Run L4

This is a separate deployment for the Corner Health inference endpoint. It
keeps the 30B Qwen3-A3B model, but replaces the incompatible BitsAndBytes
checkpoint with the official GPTQ Int4 checkpoint.

## Chosen runtime

- Model: `Qwen/Qwen3-30B-A3B-GPTQ-Int4`
- Runtime image: vLLM `v0.9.1`, built from source against CUDA 12.4.1
- CUDA runtime: 12.4, validated against the Cloud Run L4 before model loading
- GPU: one Cloud Run NVIDIA L4 (24 GB VRAM)
- Capacity: one request and one vLLM sequence at a time
- Context window: 2,048 tokens

The earlier deployment reached model initialization, but vLLM 0.8.5 failed
with `FusedMoE ... quant_method is not None` for the BitsAndBytes Qwen3-MoE
checkpoint. vLLM 0.9.1 supports the GPTQ checkpoint. The model is a 30B MoE
model with about 3B active parameters. Its 4-bit weights may fit on an L4 with
a small context window, but there is little spare VRAM; do not raise
concurrency or context length before measuring production memory use.

The vLLM Docker entrypoint is its OpenAI API server. The deployment passes
`--model=/models/...` directly and must not add `vllm serve` to the container
arguments.

The model cache job writes the Hugging Face snapshot to the existing Cloud
Storage bucket. The serving service mounts the snapshot read-only. This avoids
downloading the model during Cloud Run's four-minute startup probe window. It
uses the new `qwen3-30b-a3b-gptq-int4-v1` prefix so its files cannot mix with
earlier Gemma or BitsAndBytes caches.

## Prerequisites

- Artifact Registry repository `care-images` must exist in `europe-west4`.
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
  --config=infra/llm/qwen3-l4/cloudbuild.vllm091-cu124.yaml \\
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

The image build compiles vLLM and FlashInfer for L4 architecture `8.9` using
Cloud Build's lower-cost `E2_HIGHCPU_8` worker. Compilation is deliberately
single-worker and can take up to one hour, but has no GPU cost. Wait for the
diagnostic before spending time or storage on the model cache.

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
- If model loading runs out of VRAM, reduce `--max-model-len` and
  `--max-num-batched-tokens` to `1024`. If it still fails, the 30B GPTQ model
  is not viable on an L4 and the next step is Qwen3 14B rather than larger
  Cloud Run resources.
