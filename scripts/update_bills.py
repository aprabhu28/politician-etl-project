"""
Incremental update script for bills table.
Fetches only bills introduced in the last N days and updates the database.
Much faster than full re-ingestion.
"""
import os
import requests
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy.engine import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta
import time

load_dotenv()
API_KEY = os.getenv('CONGRESS_API_KEY')
DB_URL = os.getenv('DB_URL')

BILLS_API_BASE = "https://api.congress.gov/v3/bill"
CONGRESSES_TO_CHECK = [119]  # Only check current congress (119th Congress: 2025-2027)

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
    
    # Default: fetch bills from last 30 days if no previous update
    return datetime.now() - timedelta(days=30)


def fetch_recent_bills(congress, from_date):
    """Fetch bills introduced after a specific date."""
    print(f"  Fetching bills from {congress}th Congress since {from_date.strftime('%Y-%m-%d')}...")
    
    list_url = f"{BILLS_API_BASE}/{congress}"
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    
    # Format date for API (ISO 8601)
    from_date_str = from_date.strftime("%Y-%m-%dT00:00:00Z")
    
    all_bills = []
    next_url = list_url
    
    while next_url:
        # Always include fromDateTime parameter, even on pagination
        if next_url == list_url:
            params = {'limit': 250, 'fromDateTime': from_date_str}
        else:
            # For pagination URLs, they should already include the date filter
            # But we need to parse and ensure it's there
            params = None
        
        try:
            response = requests.get(next_url, headers=headers, params=params)
            
            if response.status_code == 429:
                print("      Rate limit hit. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            if response.status_code != 200:
                print(f"      Error {response.status_code}: {response.text}")
                break
            
            data = response.json()
            bills_list = data.get('bills', [])
            
            if not bills_list:
                break
            
            # Additional client-side filtering to ensure bills are after from_date
            filtered_bills = []
            for bill in bills_list:
                introduced_date = bill.get('introducedDate')
                if introduced_date:
                    try:
                        bill_date = datetime.strptime(introduced_date, "%Y-%m-%d")
                        if bill_date >= from_date:
                            filtered_bills.append(bill)
                    except:
                        filtered_bills.append(bill)  # Include if date parsing fails
                else:
                    filtered_bills.append(bill)  # Include if no date
            
            all_bills.extend(filtered_bills)
            print(f"    Fetched {len(all_bills)} bills so far...")
            
            # If we got fewer bills than expected after filtering, we might be done
            if len(filtered_bills) < len(bills_list):
                print(f"    Reached bills before cutoff date. Stopping.")
                break
            
            next_url = data.get('pagination', {}).get('next', None)
            time.sleep(0.5)
            
        except Exception as e:
            print(f"      Error: {e}")
            break
    
    return all_bills


def parse_bill_data(bill_data):
    """Parse bill data from API response."""
    try:
        bill_number = bill_data.get('number')
        bill_congress = bill_data.get('congress')
        bill_type = bill_data.get('type')
        bill_title = bill_data.get('title')
        
        latest_action_text = None
        latest_action = bill_data.get('latestAction')
        if latest_action and isinstance(latest_action, dict):
            latest_action_text = latest_action.get('text')

        official_bill_number = f"{bill_type}{bill_number}"

        if not bill_number or not bill_type or not bill_congress:
            return None

        return {
            "official_bill_number": official_bill_number,
            "bill_type": bill_type,
            "congress": bill_congress,
            "title": bill_title,
            "status": latest_action_text,
        }
    except Exception as e:
        print(f"      Error parsing bill: {e}")
        return None


def upsert_bills(bills_data):
    """Insert or update bills in the database."""
    bills_table = sqlalchemy.Table('bills', sqlalchemy.MetaData(), autoload_with=engine)
    
    inserted = 0
    updated = 0
    
    with engine.connect() as conn:
        for bill_data in bills_data:
            try:
                stmt = pg_insert(bills_table).values(bill_data)
                
                # On conflict, update title and status
                update_stmt = stmt.on_conflict_do_update(
                    index_elements=['official_bill_number', 'congress'],
                    set_={
                        'title': stmt.excluded.title,
                        'status': stmt.excluded.status,
                    }
                )
                
                result = conn.execute(update_stmt)
                conn.commit()
                
                if result.rowcount > 0:
                    inserted += 1
                else:
                    updated += 1
                    
            except Exception as e:
                print(f"      Error upserting bill: {e}")
    
    return inserted, updated


def main():
    """Main function to update bills incrementally."""
    
    print("  Starting incremental bills update...\n")
    print("=" * 80)
    
    # Get last update date
    last_update = get_last_update_date("bills")
    print(f"  Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Fetching bills introduced since then...\n")
    
    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    
    for congress in CONGRESSES_TO_CHECK:
        print(f"\n--- Congress {congress} ---")
        
        # Fetch recent bills
        bills_list = fetch_recent_bills(congress, last_update)
        
        if not bills_list:
            print(f"     No new bills found")
            continue
        
        print(f"    Found {len(bills_list)} bills")
        
        # Parse bill data
        parsed_bills = []
        for bill in bills_list:
            parsed = parse_bill_data(bill)
            if parsed:
                parsed_bills.append(parsed)
        
        if parsed_bills:
            # Upsert to database
            inserted, updated = upsert_bills(parsed_bills)
            print(f"    Inserted: {inserted} | Updated: {updated}")
            
            total_fetched += len(bills_list)
            total_inserted += inserted
            total_updated += updated
    
    # Log the update
    total_records = total_inserted + total_updated
    log_update("bills", total_records, "success")
    
    print("\n" + "=" * 80)
    print("  Bills update completed!")
    print(f"  Total bills fetched: {total_fetched}")
    print(f"  New bills inserted: {total_inserted}")
    print(f"  Existing bills updated: {total_updated}")
    print("=" * 80)


if __name__ == "__main__":
    main()
