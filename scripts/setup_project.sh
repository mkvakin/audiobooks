#!/bin/bash
# scripts/setup_project.sh

set -e

# Configuration
PROJECT_ID=$1
REGION=${2:-"us-central1"}
TERRAFORM_STATE_BUCKET="${PROJECT_ID}-tf-state"

if [ -z "$PROJECT_ID" ]; then
    echo "Usage: $0 <PROJECT_ID> [REGION]"
    exit 1
fi

echo "Setting up GCP project: $PROJECT_ID"

# Check if project exists, if not create it (optional, usually admin creates it)
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo "Creating project $PROJECT_ID..."
    gcloud projects create "$PROJECT_ID"
fi

# Set current project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling necessary APIs..."
gcloud services enable \
    compute.googleapis.com \
    run.googleapis.com \
    storage.googleapis.com \
    texttospeech.googleapis.com \
    iam.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    cloudresourcemanager.googleapis.com

# Create Terraform state bucket
if ! gsutil ls -b "gs://${TERRAFORM_STATE_BUCKET}" &>/dev/null; then
    echo "Creating Terraform state bucket: gs://${TERRAFORM_STATE_BUCKET}"
    gsutil mb -l "$REGION" "gs://${TERRAFORM_STATE_BUCKET}"
    gsutil versioning set on "gs://${TERRAFORM_STATE_BUCKET}"
fi

# Create Artifact Registry repo for our Docker image
REPO_NAME="audiobook-converter"
if ! gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" &>/dev/null; then
    echo "Creating Artifact Registry repository: $REPO_NAME"
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="Docker repository for Audiobook Converter"
fi

echo "Project setup complete!"
echo "You can now run Terraform from the terraform/ directory."
echo "Suggested command: terraform init -backend-config=\"bucket=${TERRAFORM_STATE_BUCKET}\""
