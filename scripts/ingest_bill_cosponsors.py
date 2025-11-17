"""
Script to populate the bill_cosponsors table.
Fetches cosponsor data from /bill/{congress}/{billType}/{billNumber}/cosponsors endpoint.
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

COSPONSORS_API = "https://api.congress.gov/v3/bill/{congress}/{billType}/{billNumber}/cosponsors"

try:
    engine = create_engine(DB_URL)
    print("Database connection successful.\n")
except Exception as e:
    print(f"Database connection failed: {e}")
    exit()


def get_politician_map():
    """Create a mapping of congress_id (bioguideId) to politician_id."""
    print("📋 Building politician lookup map...")
    
    politician_map = {}
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT politician_id, congress_id FROM politicians WHERE congress_id IS NOT NULL"
        ))
        for row in result:
            politician_map[row.congress_id] = row.politician_id
    
    print(f"Loaded {len(politician_map)} politicians into map\n")
    return politician_map


def get_all_bills():
    """Fetch all bills that need cosponsor data."""
    print("Fetching all bills from database...")
    
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            """SELECT bill_id, official_bill_number, congress, bill_type 
               FROM bills 
               WHERE congress IN (118, 119)
               ORDER BY bill_id"""
        ))
        bills = [{
            "bill_id": row.bill_id,
            "official_bill_number": row.official_bill_number,
            "congress": row.congress,
            "bill_type": row.bill_type
        } for row in result]
    
    print(f"Found {len(bills)} bills to process\n")
    return bills


def fetch_cosponsors(congress, bill_type, bill_number):
    """Fetch all cosponsors for a given bill."""
    url = COSPONSORS_API.format(congress=congress, billType=bill_type.lower(), billNumber=bill_number)
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    
    all_cosponsors = []
    next_url = url
    
    while next_url:
        try:
            response = requests.get(next_url, headers=headers, params={'limit': 250} if next_url == url else None)
            
            if response.status_code == 429:
                print("      Rate limit hit. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            if response.status_code == 404:
                # No cosponsors for this bill
                return []
            
            if response.status_code != 200:
                print(f"      Error {response.status_code}")
                break
            
            data = response.json()
            cosponsors = data.get('cosponsors', [])
            all_cosponsors.extend(cosponsors)
            
            # Check for pagination
            next_url = data.get('pagination', {}).get('next', None)
            time.sleep(0.3)  # Be nice to the API
            
        except Exception as e:
            print(f"      Error: {e}")
            break
    
    return all_cosponsors


def insert_cosponsors(bill_id, cosponsors, politician_map):
    """Insert cosponsors into the bill_cosponsors table."""
    
    inserted = 0
    skipped = 0
    
    with engine.connect() as conn:
        for cosponsor in cosponsors:
            bioguide_id = cosponsor.get('bioguideId')
            sponsorship_date_str = cosponsor.get('sponsorshipDate')
            is_original = cosponsor.get('isOriginalCosponsor', False)
            
            # Get politician_id from bioguideId
            politician_id = politician_map.get(bioguide_id)
            
            if not politician_id:
                skipped += 1
                continue
            
            # Parse date
            sponsorship_date = None
            if sponsorship_date_str:
                try:
                    sponsorship_date = datetime.strptime(sponsorship_date_str, "%Y-%m-%d").date()
                except:
                    pass
            
            try:
                # Insert cosponsor (ON CONFLICT DO NOTHING handles duplicates)
                conn.execute(sqlalchemy.text(
                    """INSERT INTO bill_cosponsors 
                       (bill_id, politician_id, sponsorship_date, is_original_cosponsor)
                       VALUES (:bill_id, :politician_id, :sponsorship_date, :is_original)
                       ON CONFLICT (bill_id, politician_id) DO NOTHING"""
                ), {
                    "bill_id": bill_id,
                    "politician_id": politician_id,
                    "sponsorship_date": sponsorship_date,
                    "is_original": is_original
                })
                conn.commit()
                inserted += 1
                
            except Exception as e:
                print(f"      Error inserting cosponsor: {e}")
                skipped += 1
    
    return inserted, skipped


def main():
    """Main function to process all bills and populate cosponsors."""
    
    politician_map = get_politician_map()
    bills = get_all_bills()
    
    total_cosponsors_inserted = 0
    total_cosponsors_skipped = 0
    bills_with_cosponsors = 0
    bills_without_cosponsors = 0
    
    print("  Starting to fetch and populate bill cosponsors...\n")
    print("=" * 80)
    
    for idx, bill in enumerate(bills, 1):
        bill_id = bill['bill_id']
        official_bill_number = bill['official_bill_number']
        congress = bill['congress']
        bill_type = bill['bill_type']
        
        # Extract bill number from official_bill_number (e.g., "HR1234" -> "1234")
        bill_number = official_bill_number.replace(bill_type.upper(), "")
        
        print(f"[{idx}/{len(bills)}] {official_bill_number} (Congress {congress})...")
        
        # Fetch cosponsors
        cosponsors = fetch_cosponsors(congress, bill_type, bill_number)
        
        if not cosponsors:
            print(f"      No cosponsors")
            bills_without_cosponsors += 1
        else:
            print(f"    Found {len(cosponsors)} cosponsors")
            inserted, skipped = insert_cosponsors(bill_id, cosponsors, politician_map)
            print(f"    Inserted: {inserted} |   Skipped: {skipped}")
            
            bills_with_cosponsors += 1
            total_cosponsors_inserted += inserted
            total_cosponsors_skipped += skipped
        
        # Progress update every 100 bills
        if idx % 100 == 0:
            print(f"\n{'='*80}")
            print(f"  PROGRESS: Processed {idx}/{len(bills)} bills")
            print(f"   Bills with cosponsors: {bills_with_cosponsors}")
            print(f"   Total cosponsors inserted: {total_cosponsors_inserted}")
            print(f"{'='*80}\n")
    
    print("\n" + "=" * 80)
    print("  COMPLETED!")
    print(f"  Bills with cosponsors: {bills_with_cosponsors}")
    print(f"    Bills without cosponsors: {bills_without_cosponsors}")
    print(f"  Total cosponsors inserted: {total_cosponsors_inserted}")
    print(f"   Total cosponsors skipped: {total_cosponsors_skipped}")
    print("=" * 80)


if __name__ == "__main__":
    main()
