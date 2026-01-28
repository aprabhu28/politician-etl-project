# 🏛️ Politician Agenda Analyzer

A hybrid search application that combines **semantic bill search** (Pinecone), **financial analytics** (BigQuery), and **AI synthesis** (GPT-4) to answer complex questions about U.S. politicians and legislation.

---

## 🎯 Features

### 1. **Semantic Bill Search ("The Librarian")**
- Queries 30,000+ bills from the 118th & 119th Congress
- Uses OpenAI embeddings + Pinecone vector database
- Finds bills based on meaning, not just keywords

### 2. **Financial Analytics ("The Analyst")**
- Queries 4.6M+ FEC donation records in BigQuery
- Analyzes campaign finance patterns
- Links donors to politicians and legislation

### 3. **AI Synthesis ("The Interface")**
- GPT-4 powered answer generation
- Non-partisan, fact-based responses
- Cites specific bills and donation amounts

---

## 🚀 Quick Start

### Prerequisites
1. **Python 3.9+**
2. **Google Cloud SDK** (for BigQuery)
3. **API Keys:**
   - Pinecone API key
   - OpenAI API key

### Installation

```bash
# Navigate to the app directory
cd app/

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.template .env
# Edit .env and add your API keys

# Authenticate with Google Cloud
gcloud auth application-default login
```

### Running the App

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`

---

## 📊 Architecture

```
User Question
    ↓
[Keyword Extraction] ← GPT-4o-mini
    ↓
    ├─→ [Pinecone Vector Search] → Bills Context
    ├─→ [BigQuery SQL Query] → Financial Context
    └─→ [BigQuery SQL Query] → Voting Records
    ↓
[GPT-4 Synthesis] → Final Answer with Sources
```

---

## 🔧 Configuration

### BigQuery
- **Project:** `politician-analysis-tool`
- **Dataset:** `politician_analytics`
- **Tables:** `politicians`, `bills`, `donations`, `donors`, `votes`, `committees`

### Pinecone
- **Index:** `bills-index`
- **Dimensions:** 1536
- **Metric:** Cosine similarity

### OpenAI
- **Embedding Model:** `text-embedding-3-small`
- **Synthesis Model:** `gpt-4o`

---

## 🧪 Example Queries

1. **Legislative Position:**
   > "Does Nancy Pelosi support AI regulation?"

2. **Bill Sponsorship:**
   > "What bills has Ted Cruz sponsored about energy?"

3. **Campaign Finance:**
   > "Who are the top donors to sponsors of crypto bills?"

4. **Voting Record:**
   > "Show me Elizabeth Warren's voting record on banking"

---

## 📁 Project Structure

```
app/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── .env.template       # Environment variables template
└── README.md          # This file
```

---

## 🐛 Troubleshooting

### "Cannot connect to BigQuery"
- Run: `gcloud auth application-default login`
- Verify project: `gcloud config get-value project`

### "PINECONE_API_KEY not found"
- Ensure `.env` file exists in the `app/` directory
- Check that the variable is spelled correctly

### "No bills found"
- Verify Pinecone index name is correct: `bills-index`
- Check that the index has data (30,000+ vectors)

---

## 🔐 Security Notes

- **Never commit `.env` file** to version control
- Use `.env.template` as a reference only
- BigQuery uses ADC (Application Default Credentials) for authentication
- API keys should have appropriate rate limits configured

---

## 📈 Performance

- **Average Query Time:** 3-5 seconds
- **Bill Search:** ~500ms (Pinecone)
- **Financial Query:** ~1-2s (BigQuery)
- **Synthesis:** ~2-3s (GPT-4)

---

## 🚢 Deployment

For production deployment to Google Cloud Run:

```bash
# Build container
gcloud builds submit --tag gcr.io/politician-analysis-tool/agenda-analyzer

# Deploy to Cloud Run
gcloud run deploy agenda-analyzer \
  --image gcr.io/politician-analysis-tool/agenda-analyzer \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

---

## 📝 Data Sources

- **Bills:** Congress.gov (scraped via custom ETL)
- **Donations:** FEC.gov bulk data
- **Votes:** Congress.gov voting records
- **Politicians:** Congress.gov member data

---

## 🤝 Contributing

This is a personal project, but feedback is welcome!

---

**Last Updated:** January 14, 2026  
**Version:** 1.0.0  
**Status:** ✅ Production Ready
