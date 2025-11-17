"""
Incremental update script for bill_cosponsors table.
Only checks cosponsors for bills added/modified recently.
Much faster than re-checking all 30K+ bills.
"""
import os
import requests
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta
import time

load_dotenv()
API_KEY = os.getenv('CONGRESS_API_KEY')
DB_URL = os.getenv('DB_URL')

CONGRESS_API_BASE = "https://api.congress.gov/v3"

try:
    engine = create_engine(DB_URL)
    print("Database connection successful.\n")
except Exception as e:
    print(f"Database connection failed: {e}")
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


def get_last_update_date(table_name):
    """Get the last successful update date for a table."""
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            """SELECT last_update FROM update_log 
               WHERE table_name = :table_name AND status = 'success'
               ORDER BY last_update DESC LIMIT 1"""
        ), {"table_name": table_name})
        
        row = result.fetchone()
        if row:
            return row.last_update
    
    # Default: check bills from last 30 days if no previous update
    return datetime.now() - timedelta(days=30)


def get_recent_bills(since_date):
    """Get bills that were added or modified since a specific date."""
    
    # Get bills introduced recently OR bills without any cosponsors yet
    query = """
        SELECT DISTINCT b.bill_id, b.official_bill_number, b.congress, b.bill_type
        FROM bills b
        LEFT JOIN bill_cosponsors bc ON b.bill_id = bc.bill_id
        WHERE b.date_introduced >= :since_date
           OR bc.bill_id IS NULL
        ORDER BY b.congress DESC, b.bill_id
    """
    
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(query),
            {"since_date": since_date.date()}
        )
        bills = result.fetchall()
        return bills


def fetch_bill_cosponsors(congress, bill_type, bill_number):
    """Fetch cosponsors for a specific bill."""
    url = f"{CONGRESS_API_BASE}/bill/{congress}/{bill_type.lower()}/{bill_number}/cosponsors"
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    
    all_cosponsors = []
    next_url = url
    
    while next_url:
        try:
            params = {'limit': 250} if next_url == url else None
            response = requests.get(next_url, headers=headers, params=params)
            
            if response.status_code == 429:
                print("        Rate limit hit. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            if response.status_code == 404:
                # Bill has no cosponsors
                return []
            
            if response.status_code != 200:
                print(f"        Error {response.status_code}")
                return []
            
            data = response.json()
            cosponsors_list = data.get('cosponsors', [])
            
            if not cosponsors_list:
                break
            
            all_cosponsors.extend(cosponsors_list)
            
            next_url = data.get('pagination', {}).get('next', None)
            time.sleep(0.3)
            
        except Exception as e:
            print(f"        Error: {e}")
            break
    
    return all_cosponsors


def parse_cosponsor_data(cosponsor_data, bill_id):
    """Parse cosponsor data from API response."""
    try:
        bioguide_id = cosponsor_data.get('bioguideId')
        
        # Parse sponsorship date
        date_str = cosponsor_data.get('sponsorshipDate')
        sponsorship_date = None
        if date_str:
            try:
                sponsorship_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except:
                pass
        
        # Check if original cosponsor
        is_original = cosponsor_data.get('isOriginalCosponsor', False)
        
        if not bioguide_id:
            return None
        
        return {
            "bioguide_id": bioguide_id,
            "bill_id": bill_id,
            "sponsorship_date": sponsorship_date,
            "is_original_cosponsor": is_original
        }
    except Exception as e:
        print(f"        Error parsing cosponsor: {e}")
        return None


def upsert_cosponsors(bill_id, cosponsors_data):
    """Insert or update cosponsors in the database."""
    
    if not cosponsors_data:
        return 0
    
    # First, look up politician IDs for all bioguide IDs
    enriched_cosponsors = []
    
    with engine.connect() as conn:
        for cosponsor in cosponsors_data:
            bioguide_id = cosponsor['bioguide_id']
            
            result = conn.execute(
                sqlalchemy.text("SELECT politician_id FROM politicians WHERE congress_id = :bioguide_id"),
                {"bioguide_id": bioguide_id}
            )
            politician = result.fetchone()
            
            if politician:
                enriched_cosponsors.append({
                    "bill_id": cosponsor['bill_id'],
                    "politician_id": politician.politician_id,
                    "sponsorship_date": cosponsor['sponsorship_date'],
                    "is_original_cosponsor": cosponsor['is_original_cosponsor']
                })
    
    if not enriched_cosponsors:
        return 0
    
    # Upsert cosponsors
    bill_cosponsors_table = sqlalchemy.Table('bill_cosponsors', sqlalchemy.MetaData(), autoload_with=engine)
    
    inserted = 0
    
    with engine.connect() as conn:
        for cosponsor_data in enriched_cosponsors:
            try:
                stmt = pg_insert(bill_cosponsors_table).values(cosponsor_data)
                
                # On conflict, update the sponsorship date and original flag
                update_stmt = stmt.on_conflict_do_update(
                    index_elements=['bill_id', 'politician_id'],
                    set_={
                        'sponsorship_date': stmt.excluded.sponsorship_date,
                        'is_original_cosponsor': stmt.excluded.is_original_cosponsor,
                    }
                )
                
                conn.execute(update_stmt)
                conn.commit()
                inserted += 1
                
            except Exception as e:
                print(f"        Error upserting cosponsor: {e}")
    
    return inserted


def main():
    """Main function to update bill cosponsors incrementally."""
    
    print("Starting incremental bill cosponsors update...\n")
    print("=" * 80)
    
    # Get last update date
    last_update = get_last_update_date("bill_cosponsors")
    print(f"Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Fetching cosponsors for bills introduced/modified since then...\n")
    
    # Get recent bills
    bills = get_recent_bills(last_update)
    total_bills = len(bills)
    
    if total_bills == 0:
        print("No bills to update!")
        log_update("bill_cosponsors", 0, "success")
        return
    
    print(f"Found {total_bills} bills to check for cosponsors\n")
    
    total_cosponsors_added = 0
    bills_processed = 0
    
    for idx, bill in enumerate(bills, 1):
        bill_id = bill.bill_id
        official_bill_number = bill.official_bill_number
        congress = bill.congress
        bill_type = bill.bill_type
        
        # Extract numeric bill number
        bill_number = official_bill_number.replace(bill_type, "")
        
        print(f"  [{idx}/{total_bills}] {official_bill_number} (Congress {congress})")
        
        # Fetch cosponsors from API
        cosponsors_list = fetch_bill_cosponsors(congress, bill_type, bill_number)
        
        if cosponsors_list:
            # Parse cosponsor data
            parsed_cosponsors = []
            for cosponsor in cosponsors_list:
                parsed = parse_cosponsor_data(cosponsor, bill_id)
                if parsed:
                    parsed_cosponsors.append(parsed)
            
            # Upsert to database
            if parsed_cosponsors:
                added = upsert_cosponsors(bill_id, parsed_cosponsors)
                total_cosponsors_added += added
                print(f"      Added/updated {added} cosponsors")
            else:
                print(f"      No valid cosponsors")
        else:
            print(f"      No cosponsors")
        
        bills_processed += 1
        
        # Rate limiting
        if idx % 50 == 0:
            print(f"\n  Processed {idx} bills. Brief pause...\n")
            time.sleep(2)
        else:
            time.sleep(0.5)
    
    # Log the update
    log_update("bill_cosponsors", total_cosponsors_added, "success")
    
    print("\n" + "=" * 80)
    print("Bill cosponsors update completed!")
    print(f"Bills processed: {bills_processed}")
    print(f"Total cosponsors added/updated: {total_cosponsors_added}")
    print("=" * 80)


if __name__ == "__main__":
    main()
