"""
Incremental update script for bill sponsor_id.
Only updates bills that don't have sponsor info yet.
Much faster than re-checking all bills.
"""
import os
import requests
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import create_engine
from datetime import datetime
import time

load_dotenv()
API_KEY = os.getenv('CONGRESS_API_KEY')
DB_URL = os.getenv('DB_URL')

CONGRESS_API_BASE = "https://api.congress.gov/v3"

try:
    engine = create_engine(DB_URL)
    print("  Database connection successful.\n")
except Exception as e:
    print(f"  Database connection failed: {e}")
    exit()


def log_update(table_name, records_updated, status="success"):
    """Log update to update_log table."""
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(
            """INSERT INTO update_log (table_name, last_update, records_updated, status)
               VALUES (:table_name, CURRENT_TIMESTAMP, :records_updated, :status)"""
        ), {
            "table_name": table_name,
            "records_updated": records_updated,
            "status": status
        })
        conn.commit()


def get_bills_without_sponsors():
    """Get all bills that don't have sponsor_id populated yet."""
    query = """
        SELECT bill_id, official_bill_number, congress, bill_type
        FROM bills
        WHERE sponsor_id IS NULL
        ORDER BY congress DESC, bill_id
    """
    
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(query))
        bills = result.fetchall()
        return bills


def fetch_bill_sponsor(congress, bill_type, bill_number):
    """Fetch sponsor info for a specific bill."""
    url = f"{CONGRESS_API_BASE}/bill/{congress}/{bill_type.lower()}/{bill_number}"
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 429:
            print("        Rate limit hit. Waiting 60 seconds...")
            time.sleep(60)
            return fetch_bill_sponsor(congress, bill_type, bill_number)  # Retry
        
        if response.status_code != 200:
            return None, None
        
        data = response.json()
        bill_data = data.get('bill', {})
        
        # Extract sponsor bioguide ID
        sponsors = bill_data.get('sponsors', [])
        sponsor_bioguide_id = None
        if sponsors and len(sponsors) > 0:
            sponsor_bioguide_id = sponsors[0].get('bioguideId')
        
        # Extract introduced date
        introduced_date_str = bill_data.get('introducedDate')
        introduced_date = None
        if introduced_date_str:
            try:
                introduced_date = datetime.strptime(introduced_date_str, "%Y-%m-%d").date()
            except:
                pass
        
        return sponsor_bioguide_id, introduced_date
        
    except Exception as e:
        print(f"        Error fetching bill: {e}")
        return None, None


def update_bill_sponsor(bill_id, sponsor_bioguide_id, introduced_date):
    """Update sponsor_id and date_introduced for a bill."""
    
    # First, look up the politician_id from congress_id (bioguide_id)
    if sponsor_bioguide_id:
        with engine.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT politician_id FROM politicians WHERE congress_id = :bioguide_id"),
                {"bioguide_id": sponsor_bioguide_id}
            )
            politician = result.fetchone()
            
            if not politician:
                print(f"        Sponsor not found in politicians table: {sponsor_bioguide_id}")
                return False
            
            politician_id = politician.politician_id
    else:
        politician_id = None
    
    # Update the bill
    try:
        with engine.connect() as conn:
            update_query = """
                UPDATE bills
                SET sponsor_id = :sponsor_id,
                    date_introduced = :date_introduced
                WHERE bill_id = :bill_id
            """
            conn.execute(
                sqlalchemy.text(update_query),
                {
                    "sponsor_id": politician_id,
                    "date_introduced": introduced_date,
                    "bill_id": bill_id
                }
            )
            conn.commit()
            return True
    except Exception as e:
        print(f"        Error updating bill: {e}")
        return False


def main():
    """Main function to update bill sponsors incrementally."""
    
    print("Starting incremental bill sponsors update...\n")
    print("=" * 80)
    
    # Get bills without sponsors
    bills = get_bills_without_sponsors()
    total_bills = len(bills)
    
    if total_bills == 0:
        print("  All bills already have sponsor information!")
        log_update("bill_sponsors", 0, "success")
        return
    
    print(f"  Found {total_bills} bills without sponsor info\n")
    
    updated_count = 0
    failed_count = 0
    
    for idx, bill in enumerate(bills, 1):
        bill_id = bill.bill_id
        official_bill_number = bill.official_bill_number
        congress = bill.congress
        bill_type = bill.bill_type
        
        # Extract numeric bill number from official_bill_number
        bill_number = official_bill_number.replace(bill_type, "")
        
        print(f"  [{idx}/{total_bills}] Processing {official_bill_number} (Congress {congress})...")
        
        # Fetch sponsor info from API
        sponsor_bioguide_id, introduced_date = fetch_bill_sponsor(congress, bill_type, bill_number)
        
        if sponsor_bioguide_id or introduced_date:
            success = update_bill_sponsor(bill_id, sponsor_bioguide_id, introduced_date)
            if success:
                updated_count += 1
                print(f"        Updated sponsor: {sponsor_bioguide_id}")
            else:
                failed_count += 1
        else:
            failed_count += 1
            print(f"        No sponsor info available")
        
        # Rate limiting - be nice to the API
        if idx % 50 == 0:
            print(f"\n    Processed {idx} bills. Brief pause...\n")
            time.sleep(2)
        else:
            time.sleep(0.3)
    
    # Log the update
    log_update("bill_sponsors", updated_count, "success")
    
    print("\n" + "=" * 80)
    print("  Bill sponsors update completed!")
    print(f"  Successfully updated: {updated_count}")
    print(f"   Failed/No data: {failed_count}")
    print("=" * 80)


if __name__ == "__main__":
    main()
