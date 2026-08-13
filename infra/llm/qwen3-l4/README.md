# Qwen3 30B-A3B on a Cloud Run L4

This is a separate, clean deployment for the Corner Health inference endpoint.
It does not use the failed Gemma image or source build.

## Chosen runtime

- Model: `unsloth/Qwen3-30B-A3B-bnb-4bit`
- Runtime image: `vllm/vllm-openai:v0.8.5`, pinned by digest
- CUDA: 12.4
- GPU: one Cloud Run NVIDIA L4 (24 GB VRAM)
- Capacity: one request and one vLLM sequence at a time
- Context window: 2,048 tokens

Qwen3 is supported by vLLM 0.8.5. The selected image is built with CUDA 12.4,
which is compatible with the Cloud Run L4 driver. The model is a 30B MoE model
with about 3B active parameters. Its 4-bit weights fit on an L4 with a small
context window, but there is little spare VRAM; do not raise concurrency or
context length before measuring production memory use.

The model cache job writes the Hugging Face snapshot to the existing Cloud
Storage bucket. The serving service mounts the snapshot read-only. This avoids
trying to download roughly 17.5 GB during Cloud Run's four-minute startup
probe window.

## Prerequisites

- Artifact Registry is not needed for this deployment; Cloud Run pulls the
  pinned public vLLM image directly.
- `care-llm-sa@mental-479910.iam.gserviceaccount.com` needs read/write access
  to `gs://lecunbuckett` for the cache job, then read access for the service.
- The existing Secret Manager secret `hf-token` must be readable by that
  service account. The model is public, but the token avoids Hugging Face rate
  limits during download.

## Deploy

From the repository root in Cloud Shell:

```bash
chmod +x infra/llm/qwen3-l4/*.sh
./infra/llm/qwen3-l4/cache-model.sh
./infra/llm/qwen3-l4/deploy-service.sh
./infra/llm/qwen3-l4/smoke-test.sh
```

The cache job uses one downloader worker and 8 GiB of memory because GCS FUSE
stages large Xet-hosted model shards before committing them to the bucket. It
can be rerun safely after an interrupted download. Do not deploy the service
until the job completes and writes `config.json` under the model directory.

## Chat behavior

Qwen3 thinks by default. The smoke test passes
`chat_template_kwargs: {"enable_thinking": false}` so its hidden reasoning is
disabled. The application should send the same field for the user-facing health
chatbot. Do not enable a reasoning parser in this vLLM 0.8.5 service: that mode
is incompatible with disabling thinking in the request.

## Failure handling

- If deployment reports a CUDA 803 error, stop and retrieve live service logs;
  this image should report CUDA 12.4 rather than 12.9.
- If model loading runs out of VRAM, lower `--gpu-memory-utilization` to `0.90`.
  If it still fails, use `unsloth/Qwen3-14B-bnb-4bit` rather than increasing
  Cloud Run resources, because an L4 always has 24 GB VRAM.
