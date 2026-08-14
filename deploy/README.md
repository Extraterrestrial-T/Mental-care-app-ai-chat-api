# VM deployment

This directory deploys the existing FastAPI, LangGraph, Gemini, Redis, and
FAISS application to one VM. It deliberately has no self-hosted chat model.

## Runtime design

- GitHub Actions builds `mental-care-app` and pushes two tags to Artifact
  Registry: the commit SHA and `main`.
- The workflow connects to the VM through IAP, writes the immutable SHA tag to
  `.release.env`, rebuilds the RAG index, then replaces the app container.
- `huggingface-cache` is a named Docker volume. The sentence-transformer model
  downloads once, then is reused after app restarts and deployments.
- `rag-index` is another named Docker volume. The release job recreates FAISS
  from the committed `app/agent/corpus.txt` before the new API starts.
- Caddy owns ports 80 and 443, obtains the TLS certificate, and proxies HTTP
  and WebSocket requests to FastAPI.

The one-time first deployment downloads the embedding model and creates the
index. Normal application requests only load those local persistent files.
Each release has a short maintenance window while the app is stopped and the
FAISS index is rebuilt; the embedding model itself remains in its persistent
cache volume.

## VM setup

1. Give the VM a reserved external IP and create an `A` record from the full
   hostname, for example `api.carecoordinator.org`, to that IP. `api` by itself
   is not a public hostname and cannot receive a TLS certificate.
2. Allow inbound TCP `80` and `443` to the VM. Keep TCP `8000` closed; Caddy is
   the only public entry point.
3. Give the VM's service account `roles/artifactregistry.reader` on the
   `my-repo` Artifact Registry repository. On the VM, run
   `gcloud auth configure-docker us-east1-docker.pkg.dev --quiet` as the user
   that will run Docker.
4. Copy this repository's `deploy/bootstrap-vm.sh` to the VM and run it once.
   It installs Docker and creates `/opt/carecoordinator/secrets`.
5. Copy `vm.env.example` to `/opt/carecoordinator/.env`, then replace every
   placeholder. Put the Firebase service-account JSON and Google OAuth client
   JSON in `/opt/carecoordinator/secrets` using the exact paths in `.env`.

Do not store the `.env` file or either JSON credential in GitHub or in the
container image.

## GitHub Actions identity

Use GitHub Actions workload identity federation, not a downloaded service
account key. Create a deployment service account with these roles:

- `roles/artifactregistry.writer` on the Artifact Registry repository
- `roles/iap.tunnelResourceAccessor` on the project
- `roles/compute.osAdminLogin` and `roles/compute.viewer` on the project

Limit the workload-identity provider to this repository:
`Extraterrestrial-T/Mental-care-app-ai-chat-api`. The workflow needs these
GitHub repository variables:

```text
GCP_PROJECT_ID=mental-479910
GAR_LOCATION=us-east1
GAR_REPOSITORY=my-repo
VM_NAME=your-vm-name
VM_ZONE=your-vm-zone
VM_DEPLOY_DIR=/opt/carecoordinator
```

Set these GitHub repository secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER=projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL/providers/github
GCP_SERVICE_ACCOUNT=github-deploy@mental-479910.iam.gserviceaccount.com
```

The service account used by GitHub must be able to use OS Login on the VM, and
the VM must have OS Login enabled for IAP deployments. After this setup, every
push to `main` builds, indexes, and deploys without logging into the VM.

Run the following once from Cloud Shell, replacing the VM values. It creates a
GitHub-only federated identity and grants the minimum roles used by the
workflow:

```bash
export PROJECT_ID=mental-479910
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export REGION=us-east1
export REPOSITORY=my-repo
export GITHUB_REPOSITORY=Extraterrestrial-T/Mental-care-app-ai-chat-api
export DEPLOY_SA=github-deploy
export POOL_ID=github
export PROVIDER_ID=github
export VM_NAME=your-vm-name
export VM_ZONE=your-vm-zone

gcloud iam service-accounts create "$DEPLOY_SA" --project="$PROJECT_ID"
gcloud iam workload-identity-pools create "$POOL_ID" \
  --project="$PROJECT_ID" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$PROJECT_ID" --location=global --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub Actions" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$GITHUB_REPOSITORY'"

gcloud iam service-accounts add-iam-policy-binding \
  "$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" --project="$PROJECT_ID" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_ID/attribute.repository/$GITHUB_REPOSITORY"
gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" \
  --project="$PROJECT_ID" --location="$REGION" \
  --member="serviceAccount:$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.writer

for ROLE in roles/iap.tunnelResourceAccessor roles/compute.osAdminLogin roles/compute.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="$ROLE"
done
gcloud compute instances add-metadata "$VM_NAME" --project="$PROJECT_ID" \
  --zone="$VM_ZONE" --metadata=enable-oslogin=TRUE
```

Set `GCP_WORKLOAD_IDENTITY_PROVIDER` to:

```text
projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github
```
