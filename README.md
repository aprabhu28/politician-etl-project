# Politicians ETL PostgreSQL Project

A comprehensive data pipeline and analytics platform for tracking U.S. politicians, legislation, campaign finance, and voting records. This project combines ETL processes, PostgreSQL database management, BigQuery analytics, and semantic search capabilities to provide deep insights into political activities.

---

## Documentation

For comprehensive project documentation, architecture details, and usage guidelines, please refer to:

**[Politician Project Overview.pdf](./Politician%20Project%20Overview.pdf)**

This document includes:
- Complete system architecture
- Database schema and relationships
- ETL pipeline documentation
- API integration details
- Deployment instructions
- Query examples and use cases

---

## Project Overview

This project provides a complete solution for:
- **Data Ingestion:** ETL pipelines for FEC campaign finance data, Congressional bills, votes, and politician information
- **Database Management:** PostgreSQL database with optimized schemas for political data
- **Analytics:** BigQuery integration for complex financial analytics
- **Semantic Search:** Pinecone-powered vector search for bills and legislation
- **AI-Powered Interface:** Streamlit application with GPT-4 synthesis for answering complex political questions

---

## Quick Start

### Prerequisites
- Python 3.9+
- PostgreSQL database
- Google Cloud SDK (for BigQuery)
- API Keys: Pinecone, OpenAI

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd politician_project

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Run database migrations
psql -d your_database < sql/creations.sql

# Run the application
cd app
streamlit run app.py
```

---

## Project Structure

```
politician_project/
├── app/                    # Streamlit application
│   ├── app.py             # Main application
│   ├── database.py        # Database connections
│   ├── models.py          # Data models
│   └── metrics.py         # Analytics metrics
├── scripts/               # ETL scripts
│   ├── ingest_*.py       # Data ingestion scripts
│   ├── update_*.py       # Update scripts
│   └── hydrate_vectors.py # Vector database population
├── data/                  # Raw data files
│   ├── csvs/             # Processed CSV files
│   └── 2024/, 2026/      # FEC data by year
├── sql/                   # SQL schemas and queries
│   └── creations.sql     # Database schema
└── requirements.txt       # Python dependencies
```

---

## Key Features

### 1. ETL Pipelines
- Automated ingestion of FEC donation data (4.6M+ records)
- Congressional bill tracking (30,000+ bills)
- Politician and committee data synchronization
- Vote record management

### 2. PostgreSQL Database
- Normalized schema with proper relationships
- Optimized indexes for performance
- Support for complex queries across donations, bills, and votes

### 3. BigQuery Analytics
- Financial analytics and aggregations
- Donor pattern analysis
- Campaign finance reporting

### 4. Semantic Search
- OpenAI embeddings for bill content
- Pinecone vector database
- Natural language bill discovery

### 5. Web Interface
- Streamlit-based UI
- GPT-4 powered Q&A
- Real-time data visualization

---

## Data Sources

- **FEC Data:** Campaign finance records from FEC.gov
- **Congressional Data:** Bills, votes, and member information from Congress.gov
- **Committee Data:** Committee assignments and structures
- **Politician Profiles:** Biographical and electoral data

---

## Security & Configuration

- Environment variables for sensitive credentials
- Google Cloud Application Default Credentials for BigQuery
- Secure API key management
- Never commit `.env` files to version control

---

## Running Scripts

### Data Ingestion
```bash
# Ingest politicians
python scripts/ingest_politicians.py

# Ingest bills
python scripts/ingest_bills.py

# Ingest donations
python scripts/ingest_bulk_donations.py

# Run all updates
python scripts/run_all_updates.py
```

### Vector Database
```bash
# Populate Pinecone with bill embeddings
python scripts/hydrate_vectors.py
```

---

## Performance Metrics

- **Database:** 4.6M+ donation records
- **Bills:** 30,000+ bills indexed
- **Politicians:** Current and historical member data
- **Query Performance:** Optimized with proper indexes

---

## Deployment

See [app/DEPLOYMENT.md](app/DEPLOYMENT.md) for deployment instructions to:
- Google Cloud Run
- Docker containers
- Local development environments

---

## Contributing

This project is maintained by @anike. For questions or contributions, please open an issue or pull request.

---

## License

[Add your license information here]

---

**Last Updated:** January 27, 2026  
**Status:** Active Development
