# 🚀 Deployment Guide - Cloud Run

This guide covers deploying the Politician Agenda Analyzer to Google Cloud Run.

---

## 📋 Prerequisites

1. **Google Cloud Project**
   - Project ID: `politician-analysis-tool`
   - Billing enabled
   - APIs enabled: Cloud Run, Cloud Build, Artifact Registry

2. **Local Setup**
   - Google Cloud SDK installed
   - Docker installed (optional, Cloud Build will handle it)
   - Authenticated: `gcloud auth login`

3. **Environment Variables**
   - Pinecone API key
   - OpenAI API key

---

## 🔧 Pre-Deployment Configuration

### 1. Create Secret Manager Secrets

Store API keys securely in Google Secret Manager:

```bash
# Create Pinecone secret
echo -n "your-pinecone-api-key" | gcloud secrets create pinecone-api-key \
    --data-file=- \
    --replication-policy="automatic"

# Create OpenAI secret
echo -n "your-openai-api-key" | gcloud secrets create openai-api-key \
    --data-file=- \
    --replication-policy="automatic"
```

### 2. Grant Cloud Run Access to Secrets

```bash
PROJECT_NUMBER=$(gcloud projects describe politician-analysis-tool --format="value(projectNumber)")

gcloud secrets add-iam-policy-binding pinecone-api-key \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding openai-api-key \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

---

## 🏗️ Build & Deploy

### Option A: Automated Deployment (Recommended)

```bash
# Navigate to app directory
cd app/

# Deploy with Cloud Build (auto-builds container)
gcloud run deploy agenda-analyzer \
    --source . \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --set-secrets="PINECONE_API_KEY=pinecone-api-key:latest,OPENAI_API_KEY=openai-api-key:latest" \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --max-instances 10 \
    --min-instances 0 \
    --concurrency 80
```

### Option B: Manual Docker Build

```bash
# Build container locally
docker build -t gcr.io/politician-analysis-tool/agenda-analyzer:latest .

# Test locally
docker run -p 8501:8501 --env-file .env gcr.io/politician-analysis-tool/agenda-analyzer:latest

# Push to Google Container Registry
docker push gcr.io/politician-analysis-tool/agenda-analyzer:latest

# Deploy to Cloud Run
gcloud run deploy agenda-analyzer \
    --image gcr.io/politician-analysis-tool/agenda-analyzer:latest \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --set-secrets="PINECONE_API_KEY=pinecone-api-key:latest,OPENAI_API_KEY=openai-api-key:latest"
```

---

## 🔐 Security Configuration

### Authentication (Optional)

To require authentication:

```bash
# Deploy with authentication required
gcloud run deploy agenda-analyzer \
    --no-allow-unauthenticated

# Grant access to specific users
gcloud run services add-iam-policy-binding agenda-analyzer \
    --region us-central1 \
    --member="user:your-email@example.com" \
    --role="roles/run.invoker"
```

### Network Configuration

#### VPC Connector (if accessing private resources)

```bash
# Create VPC connector
gcloud compute networks vpc-access connectors create agenda-connector \
    --region us-central1 \
    --range 10.8.0.0/28

# Deploy with VPC connector
gcloud run deploy agenda-analyzer \
    --vpc-connector agenda-connector \
    --vpc-egress all-traffic
```

---

## ⚙️ Resource Configuration

### Recommended Settings

| Setting | Development | Production |
|---------|-------------|------------|
| CPU | 1 | 2 |
| Memory | 1Gi | 2Gi |
| Max Instances | 5 | 10 |
| Min Instances | 0 | 1 (for faster cold starts) |
| Timeout | 60s | 300s |
| Concurrency | 80 | 80 |

### Cost Optimization

```bash
# Minimal deployment (keep costs low)
gcloud run deploy agenda-analyzer \
    --source . \
    --platform managed \
    --region us-central1 \
    --memory 1Gi \
    --cpu 1 \
    --timeout 60 \
    --max-instances 3 \
    --min-instances 0 \
    --concurrency 80
```

**Estimated Costs (with free tier):**
- Cloud Run: Free for first 2M requests/month
- BigQuery: First 1TB queries/month free
- Pinecone: Free tier (100K requests/month)
- OpenAI: Pay-per-use (~$0.10 per 1K queries)

---

## 📊 Monitoring & Logging

### Enable Cloud Monitoring

```bash
# View logs
gcloud run services logs read agenda-analyzer --region us-central1

# Stream logs in real-time
gcloud run services logs tail agenda-analyzer --region us-central1
```

### Set Up Alerts

```bash
# Create uptime check
gcloud monitoring uptime create agenda-uptime \
    --display-name="Agenda Analyzer Uptime" \
    --resource-type="cloud-run-service" \
    --http-check-path="/"
```

### Key Metrics to Monitor

1. **Request Latency**
   - Target: < 10s per query
   - Alert if 95th percentile > 15s

2. **Error Rate**
   - Target: < 1%
   - Alert if > 5%

3. **BigQuery Queries**
   - Monitor daily query volume
   - Alert if approaching 1TB free tier limit

4. **OpenAI API Costs**
   - Track token usage
   - Set budget alerts

---

## 🔄 Continuous Deployment

### Set Up Cloud Build Trigger

Create `cloudbuild.yaml`:

```yaml
steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/agenda-analyzer:$COMMIT_SHA', '.']
  
  # Push to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/agenda-analyzer:$COMMIT_SHA']
  
  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'agenda-analyzer'
      - '--image=gcr.io/$PROJECT_ID/agenda-analyzer:$COMMIT_SHA'
      - '--region=us-central1'
      - '--platform=managed'
      - '--allow-unauthenticated'

images:
  - 'gcr.io/$PROJECT_ID/agenda-analyzer:$COMMIT_SHA'
```

### Connect to GitHub

```bash
# Create trigger for main branch
gcloud builds triggers create github \
    --repo-name=politician_project \
    --repo-owner=your-github-username \
    --branch-pattern="^main$" \
    --build-config=cloudbuild.yaml
```

---

## 🧪 Post-Deployment Testing

### Health Check

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe agenda-analyzer --region us-central1 --format="value(status.url)")

# Test endpoint
curl $SERVICE_URL/_stcore/health
```

### Smoke Tests

1. **Homepage Load**
   ```bash
   curl -I $SERVICE_URL
   # Expected: HTTP 200
   ```

2. **Test Query**
   - Open $SERVICE_URL in browser
   - Enter test query
   - Verify results appear

3. **Load Test**
   ```bash
   # Install Apache Bench
   ab -n 100 -c 10 $SERVICE_URL/
   ```

---

## 🔧 Troubleshooting

### Common Issues

#### 1. "Permission Denied" Error
**Solution:** Check IAM permissions for Cloud Run service account.

```bash
gcloud projects get-iam-policy politician-analysis-tool
```

#### 2. Cold Start Timeouts
**Solution:** Increase timeout or set min-instances to 1.

```bash
gcloud run services update agenda-analyzer \
    --min-instances 1 \
    --region us-central1
```

#### 3. BigQuery Connection Fails
**Solution:** Ensure service account has BigQuery User role.

```bash
gcloud projects add-iam-policy-binding politician-analysis-tool \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/bigquery.user"
```

#### 4. Out of Memory Errors
**Solution:** Increase memory allocation.

```bash
gcloud run services update agenda-analyzer \
    --memory 2Gi \
    --region us-central1
```

---

## 🎯 Performance Tuning

### Optimize Cold Starts

1. **Keep container size small:** Use slim base image
2. **Lazy load dependencies:** Import packages only when needed
3. **Use minimum instances:** Set to 1 for production

### Optimize Query Performance

1. **Cache service connections:** Already implemented with `@st.cache_resource`
2. **Optimize BigQuery queries:** Use partitioned tables, limit results
3. **Batch Pinecone queries:** Query once per session

---

## 📝 Rollback Procedure

If deployment fails or issues arise:

```bash
# List previous revisions
gcloud run revisions list --service agenda-analyzer --region us-central1

# Rollback to previous revision
gcloud run services update-traffic agenda-analyzer \
    --to-revisions=agenda-analyzer-00001-xyz=100 \
    --region us-central1
```

---

## ✅ Deployment Checklist

- [ ] Secrets created in Secret Manager
- [ ] IAM permissions configured
- [ ] Service deployed successfully
- [ ] Health check passes
- [ ] Test query returns results
- [ ] Monitoring and logging configured
- [ ] Alerts set up
- [ ] Documentation updated
- [ ] Team notified of new URL

---

## 🌐 Custom Domain (Optional)

### Map Custom Domain

```bash
# Verify domain ownership first in Google Search Console

# Map domain
gcloud run domain-mappings create \
    --service agenda-analyzer \
    --domain app.yourpoliticssite.com \
    --region us-central1
```

### Update DNS

Add the following records to your DNS provider:

```
Type: CNAME
Name: app
Value: ghs.googlehosted.com
```

---

## 📞 Support

- **Cloud Run Docs:** https://cloud.google.com/run/docs
- **Troubleshooting:** Check logs with `gcloud run services logs`
- **Cost Monitoring:** https://console.cloud.google.com/billing

---

**Last Updated:** January 14, 2026  
**Deployment Status:** ✅ Ready for Production
