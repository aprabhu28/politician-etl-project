# Bill Sponsorship & Cosponsorships Implementation

## ✅ Completed Tasks

### 1. Database Schema ✓
- Created `bill_cosponsors` junction table
- Added foreign keys to `bills` and `politicians` tables
- Added indexes for performance optimization
- Added unique constraint to prevent duplicate cosponsorships
- Table includes: `cosponsor_id`, `bill_id`, `politician_id`, `sponsorship_date`, `is_original_cosponsor`

**SQL File:** `sql/creations.sql`
**Migration Script:** `create_cosponsors_table.py`

---

### 2. Data Ingestion Scripts ✓

#### Script 1: `scripts/ingest_bill_sponsors.py`
**Purpose:** Populate `bills.sponsor_id` and `bills.date_introduced`

**API Endpoint Used:** `/member/{bioguideId}/sponsored-legislation`

**Process:**
1. Fetches all politicians from database
2. For each politician, calls Congress API to get their sponsored bills
3. Matches bills by `(congress, type, number)` to existing bills in database
4. Updates `sponsor_id` and `date_introduced` fields

**How to Run:**
```bash
python scripts/ingest_bill_sponsors.py
```

#### Script 2: `scripts/ingest_bill_cosponsors.py`
**Purpose:** Populate `bill_cosponsors` table with all cosponsor relationships

**API Endpoint Used:** `/bill/{congress}/{billType}/{billNumber}/cosponsors`

**Process:**
1. Fetches all bills from database (Congress 118 & 119)
2. For each bill, calls Congress API to get cosponsor list
3. Maps `bioguideId` to `politician_id`
4. Inserts cosponsor records with sponsorship date and original cosponsor flag

**How to Run:**
```bash
python scripts/ingest_bill_cosponsors.py
```

**Note:** These scripts handle API rate limiting and pagination automatically.

---

### 3. SQLAlchemy Models ✓

Updated `app/models.py` with:

#### New Model: `BillCosponsor`
- Maps to `bill_cosponsors` table
- Relationships to both `Bill` and `Politician`

#### Updated Model: `Bill`
- Added `sponsor_id` foreign key
- Added `sponsor` relationship (one-to-one with Politician)
- Added `cosponsors` relationship (one-to-many with BillCosponsor)

#### Updated Model: `Politician`
- Added `sponsored_bills` relationship (bills they introduced)
- Added `cosponsored_bills` relationship (bills they cosponsored)

---

### 4. API Endpoints ✓

Added 4 new endpoints to `app/main.py`:

#### 1. `GET /politicians/{politician_id}/sponsored-bills`
**Returns:** All bills sponsored (introduced) by a politician
**Filters:** Pagination (skip, limit)
**Use Case:** "Show me all bills introduced by AOC"

#### 2. `GET /politicians/{politician_id}/cosponsored-bills`
**Returns:** All bills cosponsored by a politician
**Filters:** 
- Pagination (skip, limit)
- `original_only` - filter for original cosponsors
**Use Case:** "Show me all bills Bernie Sanders cosponsored"

#### 3. `GET /bills/{bill_id}/sponsor`
**Returns:** The primary sponsor of a specific bill
**Use Case:** "Who introduced the Green New Deal?"

#### 4. `GET /bills/{bill_id}/cosponsors`
**Returns:** All cosponsors of a specific bill
**Filters:**
- Pagination (skip, limit)
- `original_only` - filter for original cosponsors
**Use Case:** "Who cosponsored the Infrastructure Bill?"

---

## 🎯 Next Steps

### Phase 1: Run Data Ingestion (Required)
```bash
# Step 1: Populate sponsor_id for all bills
python scripts/ingest_bill_sponsors.py

# Step 2: Populate bill_cosponsors table
python scripts/ingest_bill_cosponsors.py
```

**Note:** These scripts will take several hours due to API rate limiting (30K+ bills).

---

### Phase 2: Build Analysis Endpoints

Now that you have sponsorship data, you can build powerful analysis endpoints:

#### Example 1: Contradiction Analysis
```python
GET /politicians/{id}/financial-influence-analysis

# Returns:
# - Top donor industries
# - Bills sponsored/cosponsored related to those industries
# - Potential conflicts of interest
```

#### Example 2: Bipartisan Analysis
```python
GET /bills/{id}/partisan-analysis

# Returns:
# - Sponsor party
# - Cosponsor party breakdown
# - Bipartisan score
```

#### Example 3: Follow the Money
```python
GET /analysis/donor-to-legislation

# Query: Show politicians who received donations from [industry]
# and sponsored/cosponsored bills benefiting that industry
```

---

### Phase 3: Frontend Visualization

Build dashboards to visualize:
- **Politician Profiles**: Show their sponsored bills, votes, donations side-by-side
- **Network Graphs**: Connect politicians → donors → industries → bills
- **Contradiction Alerts**: Highlight when votes/sponsorships contradict stated positions
- **Timeline View**: Track how donations correlate with bill sponsorships over time

---

## 📊 Data Model Summary

```
Politicians (2,598)
    ├─→ sponsored_bills (via sponsor_id)
    ├─→ cosponsored_bills (via bill_cosponsors)
    ├─→ votes (646,189)
    └─→ donations (4.5M)

Bills (30,113)
    ├─→ sponsor (Politician)
    ├─→ cosponsors (via bill_cosponsors)
    └─→ votes

BillCosponsors (junction table)
    ├─→ bill
    ├─→ politician
    ├─ sponsorship_date
    └─ is_original_cosponsor

Donations (4.5M)
    ├─→ politician
    └─→ donor (27,000+)
```

---

## 🚀 Testing the New Endpoints

Once FastAPI server restarts, visit: http://localhost:8000/docs

You'll see the new endpoints in Swagger UI:
- `/politicians/{politician_id}/sponsored-bills`
- `/politicians/{politician_id}/cosponsored-bills`
- `/bills/{bill_id}/sponsor`
- `/bills/{bill_id}/cosponsors`

**Example API Calls:**
```bash
# Get bills sponsored by politician #1
curl http://localhost:8000/politicians/1/sponsored-bills

# Get cosponsors of bill #100
curl http://localhost:8000/bills/100/cosponsors

# Get only original cosponsors
curl http://localhost:8000/bills/100/cosponsors?original_only=true
```

---

## 📝 Files Created/Modified

### Created:
- `create_cosponsors_table.py` - Database migration script
- `scripts/ingest_bill_sponsors.py` - Sponsor ingestion
- `scripts/ingest_bill_cosponsors.py` - Cosponsor ingestion

### Modified:
- `sql/creations.sql` - Added bill_cosponsors table definition
- `app/models.py` - Added BillCosponsor model, updated relationships
- `app/main.py` - Added 4 new API endpoints

---

## 💡 Your NYC Mayoral Example

With this infrastructure, you can now:

1. **Query:** "Show me all bills introduced by Politician A related to transportation"
2. **Query:** "Show me all donations Politician A received from DoorDash or delivery companies"
3. **Analyze:** "Did Politician A's policy positions align with their sponsored bills?"
4. **Compare:** "How did Politician A vote on e-bike legislation vs. what they said?"

This is the foundation for exposing contradictions between:
- **What they say** (public statements - future enhancement)
- **What they do** (sponsored bills, votes)
- **Who pays them** (donations from specific industries)

---

## 🎉 Summary

You now have a complete sponsorship and cosponsorsh tracking system that connects:
- Politicians ↔ Bills they sponsor
- Politicians ↔ Bills they cosponsor
- Bills ↔ All their sponsors and cosponsors
- Full API access to query all these relationships

**Next:** Run the ingestion scripts, then start building your analysis endpoints! 🚀
