# Cloud Run L4 vLLM build

This package builds vLLM source commit `9b4e83934` for CUDA 12.4.1 and
NVIDIA compute capability 8.9, which is the Cloud Run L4 target. It exists
because the published Gemma 4 vLLM image uses CUDA 12.9 and returns CUDA error
803 on Cloud Run's L4 driver.

## Build the image

Run from Cloud Shell after setting the project:

```bash
gcloud config set project mental-479910

gcloud builds submit \
  --project=mental-479910 \
  --config=infra/llm/cloudbuild.vllm-cu124.yaml \
  infra/llm
```

The resulting image is:

```text
europe-west4-docker.pkg.dev/mental-479910/care-images/vllm-gemma4-cu124:9b4e839
```

The first build is intentionally expensive and can take up to two hours. It
builds vLLM CUDA extensions from source without precompiled CUDA 12.9 wheels.

## Verify CUDA before deploying the model

```bash
chmod +x infra/llm/deploy-diagnostic.sh infra/llm/deploy-care-llm.sh
./infra/llm/deploy-diagnostic.sh
```

The diagnostic logs must show, in order:

```text
12.4
True
1
```

Do not deploy the model if CUDA is unavailable or the log contains error 803.

## Deploy the inference endpoint

The Hugging Face token must already exist as the `hf-token` Secret Manager
secret and be readable by `care-llm-sa@mental-479910.iam.gserviceaccount.com`.

```bash
./infra/llm/deploy-care-llm.sh
```

After the service becomes ready, run:

```bash
export SERVICE_URL="$(gcloud run services describe care-llm \
  --project=mental-479910 \
  --region=us-central1 \
  --format='value(status.url)')"

curl -sS "$SERVICE_URL/v1/models" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

For a chat smoke test, send one message to `/v1/chat/completions` with the
model name `unsloth/gemma-4-31B-it-unsloth-bnb-4bit`.

If model loading runs out of L4 VRAM, change `--max-model-len` to `2048` and
`--gpu-memory-utilization` to `0.90` in `deploy-care-llm.sh`, then redeploy.
