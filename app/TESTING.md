# 🧪 Testing Guide - Politician Agenda Analyzer

## Overview
This document provides comprehensive testing procedures for the Politician Agenda Analyzer application.

---

## ✅ Pre-Launch Checklist

### 1. Environment Setup
- [ ] `.env` file exists with valid API keys
- [ ] Python 3.9+ installed
- [ ] Virtual environment created
- [ ] All dependencies installed (`pip install -r requirements.txt`)

### 2. Service Authentication
- [ ] Google Cloud authenticated (`gcloud auth application-default login`)
- [ ] Pinecone API key valid
- [ ] OpenAI API key valid

### 3. Data Validation
- [ ] BigQuery dataset accessible: `politician-analysis-tool.politician_analytics`
- [ ] Pinecone index accessible: `bills-index`
- [ ] Minimum 30,000 vectors in Pinecone
- [ ] Minimum 4.6M rows in BigQuery donations table

---

## 🔬 Unit Testing

### Test 1: Service Connections
**Objective:** Verify all cloud services initialize correctly.

**Steps:**
1. Run `python setup_check.py`
2. Verify all checks pass

**Expected Result:**
```
✅ Python 3.9+
✅ All dependencies installed
✅ Environment file configured
✅ Google Cloud authenticated
✅ Pinecone connected (30,000+ vectors)
✅ OpenAI connected
✅ BigQuery connected (XXX bills)
```

---

### Test 2: Semantic Search
**Objective:** Test bill retrieval from Pinecone.

**Test Cases:**
| Query | Expected Bills (approx) |
|-------|------------------------|
| "Cryptocurrency regulation" | Bills containing crypto, blockchain, digital currency |
| "Climate change legislation" | Environmental bills, emissions, clean energy |
| "Healthcare reform" | Medicare, Medicaid, insurance bills |
| "Immigration policy" | Border security, visa, asylum bills |

**Manual Test:**
1. Launch app: `streamlit run app.py`
2. Enter query
3. Expand "Relevant Bills from Vector Search"
4. Verify bills are semantically relevant (not just keyword matches)

**Pass Criteria:**
- Returns 3-10 bills
- Bills are relevant to query meaning
- Similarity scores > 0.5
- Metadata includes: bill_number, title, summary, sponsor

---

### Test 3: Analytical Search
**Objective:** Test BigQuery financial queries.

**Test Cases:**

#### 3A: Top Donors by Keyword
- **Input:** "Oil", "Energy", "Petroleum"
- **Expected:** Oil companies, energy PACs
- **Verify:** Total amounts > $0, donor names relevant

#### 3B: Politician Votes
- **Input:** Politician = "Nancy Pelosi", Keywords = ["Healthcare"]
- **Expected:** Voting records from BigQuery
- **Verify:** Vote dates, descriptions, results present

#### 3C: Bill Sponsor Donors
- **Input:** Bill number = "H.R. 1"
- **Expected:** Top donors to the bill's sponsor
- **Verify:** Donor names, amounts, locations

---

### Test 4: Keyword Extraction
**Objective:** Test LLM-based keyword extraction.

**Test Cases:**
| User Question | Expected Keywords |
|---------------|-------------------|
| "Does AOC support the Green New Deal?" | bill_search_terms: ["Green New Deal", "climate"], politician_names: ["AOC", "Alexandria Ocasio-Cortez"] |
| "Who funds gun rights legislation?" | bill_search_terms: ["gun rights", "firearms"], donor_keywords: ["NRA", "gun"] |
| "Show me tech industry donations" | donor_keywords: ["tech", "technology", "software"] |

**Pass Criteria:**
- Returns valid JSON structure
- Extracts relevant terms
- Handles misspellings and abbreviations

---

### Test 5: Synthesis Engine
**Objective:** Test end-to-end answer generation.

**Test Case:**
- **Query:** "Does Nancy Pelosi support AI regulation?"
- **Expected Sources:**
  - Bills about AI, regulation, technology
  - Possibly donation data if relevant
  - Voting records if available
- **Expected Answer:**
  - Factual, non-partisan
  - Cites specific bills
  - Mentions voting patterns if found
  - States if data is insufficient

**Pass Criteria:**
- Answer is coherent and addresses the question
- Specific bill numbers cited (e.g., "H.R. 1234")
- No hallucinated information
- Sources match cited content

---

## 🎯 Integration Testing

### Test Scenario 1: First-Time User Flow
1. User opens app
2. Sees connection status: "✅ Connected to BigQuery & Pinecone"
3. Reads example questions in sidebar
4. Enters: "What is Bernie Sanders' position on Medicare for All?"
5. System extracts keywords
6. Retrieves relevant bills (semantic)
7. Retrieves votes (analytical)
8. Displays synthesized answer with sources

**Success Metrics:**
- Total time < 10 seconds
- Answer includes at least 2 bill citations
- Sources are expandable and accurate

---

### Test Scenario 2: Complex Multi-Faceted Query
**Query:** "Who are the top oil industry donors, and which energy bills did their recipients sponsor?"

**Expected Flow:**
1. Extract keywords: donor_keywords=["oil"], bill_search_terms=["energy"]
2. Query BigQuery for oil donors → Get top 10
3. Search Pinecone for energy bills → Get 5 bills
4. (Optional) Query sponsors of those bills
5. Synthesize answer linking donors → politicians → bills

**Success Metrics:**
- Answer addresses both parts (donors AND bills)
- Financial figures cited (e.g., "$2.3M total")
- Specific bills mentioned
- Clear logical connection established

---

### Test Scenario 3: Error Handling
**Test Cases:**
1. **Empty Query:** User clicks "Analyze" with no input
   - Expected: Warning message displayed
   
2. **No Results:** Query for extremely obscure topic
   - Expected: Graceful message: "No bills found for this query"
   
3. **API Rate Limit:** Rapid successive queries
   - Expected: Error message with retry suggestion
   
4. **Invalid Politician Name:** "Who is Barack Obama's voting record?"
   - Expected: "No voting records found" or "Not a current legislator"

---

## 📊 Performance Testing

### Latency Benchmarks
| Operation | Target | Acceptable | Poor |
|-----------|--------|------------|------|
| Page Load | < 2s | < 5s | > 5s |
| Keyword Extraction | < 1s | < 3s | > 3s |
| Pinecone Search | < 500ms | < 2s | > 2s |
| BigQuery Query | < 2s | < 5s | > 5s |
| GPT Synthesis | < 3s | < 7s | > 7s |
| **Total Query** | **< 5s** | **< 10s** | **> 10s** |

### Load Testing
- **Concurrent Users:** Test with 1, 5, 10 simultaneous queries
- **Expected:** Performance degrades gracefully
- **Monitoring:** Watch for BigQuery quota limits

---

## 🐛 Known Issues & Limitations

### Current Limitations
1. **Data Freshness:** Bills are from 118th-119th Congress only
2. **Politician Coverage:** Only current members of Congress
3. **Donation Data:** FEC data through 2024 only
4. **No Historical Analysis:** Cannot answer "how has this changed over time?"

### Edge Cases
1. Very long summaries may be truncated
2. Bills with no sponsor metadata will show "Unknown"
3. Queries about non-legislators will return empty results
4. Queries requiring mathematical calculations may be imprecise

---

## 📝 Test Report Template

```markdown
## Test Report - [Date]

### Test Summary
- **Total Tests:** X
- **Passed:** Y
- **Failed:** Z
- **Skipped:** W

### Failed Tests
| Test ID | Description | Expected | Actual | Priority |
|---------|-------------|----------|--------|----------|
| T-XX | ... | ... | ... | High/Med/Low |

### Performance Metrics
- Average query time: X.Xs
- 95th percentile: X.Xs
- Errors encountered: X

### Recommendations
1. ...
2. ...

### Sign-Off
- Tester: [Name]
- Date: [Date]
- Status: ✅ Ready / 🚧 Needs Work / ❌ Blocked
```

---

## 🚀 Deployment Checklist

Before deploying to production (Google Cloud Run):

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Performance benchmarks met
- [ ] Error handling validated
- [ ] Security review complete (API keys not exposed)
- [ ] Documentation updated
- [ ] Monitoring configured
- [ ] Rollback plan documented

---

**Last Updated:** January 14, 2026  
**Version:** 1.0.0
