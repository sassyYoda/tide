#!/usr/bin/env bash
# Phase 6 — GCP project bootstrap (Pitfall P13 — budget alerts mandatory).
# Idempotent: re-running is safe. Run as a user with billing.admin on a billing account.
#
# DEFERRED TO USER: this script is fully authored but cannot be fully automated.
# Creating a GCP project + binding a billing account requires the project owner's
# console/CLI session — there is no service-account path for first-time project
# creation. The user MUST run this once (with the env vars below exported) when
# they are ready to provision the Tide GCP environment.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-tide-mvp}"
BILLING_ACCOUNT="${GCP_BILLING_ACCOUNT:-}"   # e.g., 01ABCD-234567-EFGH89; user must export
REGION="${GCP_REGION:-us-east1}"             # must be free-tier-eligible (us-east1/west1/central1)

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not found. brew install --cask google-cloud-sdk" >&2; exit 1; }
[ -n "$BILLING_ACCOUNT" ] || { echo "ERROR: export GCP_BILLING_ACCOUNT=<account-id> first" >&2; exit 1; }

# 1. Project (idempotent)
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name="Tide MVP"
fi
gcloud config set project "$PROJECT_ID"

# 2. Billing
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT" || true

# 3. APIs (verified list from RESEARCH §Wave 0 — 9 services)
APIS=(
  compute.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  artifactregistry.googleapis.com
  cloudscheduler.googleapis.com
  iamcredentials.googleapis.com
  sts.googleapis.com
  cloudresourcemanager.googleapis.com
  iam.googleapis.com
)
for api in "${APIS[@]}"; do
  gcloud services enable "$api" --project="$PROJECT_ID" || true
done

# 4. Budget alerts (Pitfall P13 — $1/$5/$10/$30 thresholds)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
echo "Project number: $PROJECT_NUMBER"

# gcloud beta billing budgets create has changed CLI shape across versions; emit
# instructions for the user rather than failing on a version mismatch.
cat <<EOF
NEXT MANUAL STEP — Budget alerts (Pitfall P13):
  Visit https://console.cloud.google.com/billing/budgets?project=$PROJECT_ID
  Create a budget for the linked billing account:
    - Amount: \$30/month
    - Thresholds: 3%, 17%, 33%, 100% (= \$1, \$5, \$10, \$30)
    - Email notifications to: $(gcloud config get-value account)

NEXT STEP — Add GitHub repo vars (NOT secrets):
  gh variable set GCP_PROJECT_ID --body "$PROJECT_ID"
  gh variable set GCP_PROJECT_NUMBER --body "$PROJECT_NUMBER"
  gh variable set GCP_REGION --body "$REGION"

Bootstrap complete. Next: cd terraform && terraform init && terraform plan -var-file=staging.tfvars
EOF
