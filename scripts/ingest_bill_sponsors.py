"""
Script to populate bills.sponsor_id and bills.date_introduced fields.
Uses the /member/{bioguideId}/sponsored-legislation endpoint to fetch all bills sponsored by each politician.
"""
import os
import requests
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy.engine import create_engine
from datetime import datetime
import time

load_dotenv()
API_KEY = os.getenv('CONGRESS_API_KEY')
DB_URL = os.getenv('DB_URL')

SPONSORED_LEGISLATION_API = "https://api.congress.gov/v3/member/{bioguideId}/sponsored-legislation"

try:
    engine = create_engine(DB_URL)
    print("  Database connection successful.\n")
except Exception as e:
    print(f"  Database connection failed: {e}")
    exit()


def get_all_politicians():
    """Fetch all politicians from the database with their congress_id (bioguideId)."""
    print("  Fetching all politicians from database...")
    
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT politician_id, congress_id, first_name, last_name FROM politicians WHERE congress_id IS NOT NULL"
        ))
        politicians = [{"politician_id": row.politician_id, "congress_id": row.congress_id, 
                       "name": f"{row.first_name} {row.last_name}"} for row in result]
    
    print(f"  Found {len(politicians)} politicians with bioguide IDs\n")
    return politicians


def fetch_sponsored_legislation(bioguide_id):
    """Fetch all bills sponsored by a given politician."""
    url = SPONSORED_LEGISLATION_API.format(bioguideId=bioguide_id)
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    
    all_legislation = []
    next_url = url
    
    while next_url:
        try:
            response = requests.get(next_url, headers=headers, params={'limit': 250} if next_url == url else None)
            
            if response.status_code == 429:
                print("    Rate limit hit. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            if response.status_code != 200:
                print(f"    Error {response.status_code}: {response.text}")
                break
            
            data = response.json()
            legislation = data.get('sponsoredLegislation', [])
            all_legislation.extend(legislation)
            
            # Check for pagination
            next_url = data.get('pagination', {}).get('next', None)
            time.sleep(0.5)  # Be nice to the API
            
        except Exception as e:
            print(f"    Error fetching data: {e}")
            break
    
    return all_legislation


def update_bill_sponsor(politician_id, congress, bill_type, bill_number, date_introduced):
    """Update a bill's sponsor_id and date_introduced in the database."""
    
    # Construct official_bill_number (e.g., "HR1234", "S4417")
    official_bill_number = f"{bill_type}{bill_number}"
    
    # Parse date
    date_obj = None
    if date_introduced:
        try:
            date_obj = datetime.strptime(date_introduced, "%Y-%m-%d").date()
        except:
            pass
    
    with engine.connect() as conn:
        # Check if bill exists
        result = conn.execute(sqlalchemy.text(
            "SELECT bill_id FROM bills WHERE official_bill_number = :num AND congress = :cong"
        ), {"num": official_bill_number, "cong": congress})
        
        bill = result.fetchone()
        
        if bill:
            # Update sponsor_id and date_introduced
            conn.execute(sqlalchemy.text(
                """UPDATE bills 
                   SET sponsor_id = :sponsor_id, 
                       date_introduced = :date_introduced 
                   WHERE bill_id = :bill_id"""
            ), {
                "sponsor_id": politician_id, 
                "date_introduced": date_obj, 
                "bill_id": bill.bill_id
            })
            conn.commit()
            return True
        
    return False


def main():
    """Main function to process all politicians and update their sponsored bills."""
    
    politicians = get_all_politicians()
    
    total_updated = 0
    total_not_found = 0
    
    print("  Starting to fetch and update sponsored legislation...\n")
    print("=" * 80)
    
    for idx, politician in enumerate(politicians, 1):
        bioguide_id = politician['congress_id']
        politician_id = politician['politician_id']
        name = politician['name']
        
        print(f"\n[{idx}/{len(politicians)}] Processing {name} ({bioguide_id})...")
        
        # Fetch sponsored legislation
        sponsored_bills = fetch_sponsored_legislation(bioguide_id)
        
        if not sponsored_bills:
            print(f"      No sponsored legislation found")
            continue
        
        print(f"    Found {len(sponsored_bills)} sponsored bills")
        
        updated_count = 0
        not_found_count = 0
        
        # Update each bill
        for bill in sponsored_bills:
            congress = bill.get('congress')
            bill_type = bill.get('type')
            bill_number = bill.get('number')
            date_introduced = bill.get('introducedDate')
            
            # Only process bills from Congress 118 and 119 (the ones in our database)
            if congress not in [118, 119]:
                continue
            
            if congress and bill_type and bill_number:
                if update_bill_sponsor(politician_id, congress, bill_type, bill_number, date_introduced):
                    updated_count += 1
                else:
                    not_found_count += 1
        
        print(f"    Updated: {updated_count} |   Not found in DB: {not_found_count}")
        
        total_updated += updated_count
        total_not_found += not_found_count
        
        # Progress update every 50 politicians
        if idx % 50 == 0:
            print(f"\n{'='*80}")
            print(f"  PROGRESS: Processed {idx}/{len(politicians)} politicians")
            print(f"   Total bills updated: {total_updated}")
            print(f"   Total bills not found: {total_not_found}")
            print(f"{'='*80}")
    
    print("\n" + "=" * 80)
    print("  COMPLETED!")
    print(f"  Total bills updated with sponsor: {total_updated}")
    print(f"   Total bills not found in database: {total_not_found}")
    print("=" * 80)


if __name__ == "__main__":
    main()
