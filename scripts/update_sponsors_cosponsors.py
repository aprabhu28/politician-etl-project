"""
Combined incremental update script for bill sponsors and cosponsors.
Parses XML files from congress repo - MUCH faster than API calls.
Only processes bills modified since last update.
"""
import os
import sqlalchemy
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta
from pathlib import Path

load_dotenv()
DB_URL = os.getenv('DB_URL')

# Paths for congress repo tool
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
BASE_DIR = PROJECT_DIR.parent  # Politicians ETL PostgreSQL Project
CONGRESS_REPO_DIR = BASE_DIR / "congress"
CONGRESS_DATA_DIR = CONGRESS_REPO_DIR / "congress" / "data"

CONGRESSES_TO_CHECK = [118, 119]  # 118th & 119th Congress

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
    
    # Default: check last 7 days if no previous update
    return datetime.now() - timedelta(days=7)


def get_politician_id(bioguide_id):
    """Look up politician_id from congress_id (bioguide_id)."""
    if not bioguide_id:
        return None
    
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT politician_id FROM politicians WHERE congress_id = :bioguide_id"),
            {"bioguide_id": bioguide_id}
        )
        row = result.fetchone()
        return row.politician_id if row else None


def get_bill_id(official_bill_number):
    """Look up bill_id from official_bill_number."""
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT bill_id FROM bills WHERE official_bill_number = :bill_num"),
            {"bill_num": official_bill_number}
        )
        row = result.fetchone()
        return row.bill_id if row else None


def parse_sponsors_and_cosponsors(xml_path):
    """
    Parse sponsor and cosponsor data from fdsys_billstatus.xml file.
    Returns (bill_info, sponsor_bioguide, cosponsors_list)
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Extract bill info
        bill = root.find('.//bill')
        if bill is None:
            return None, None, []
        
        congress = bill.find('congress')
        bill_type_elem = bill.find('type')
        bill_number_elem = bill.find('number')
        introduced_date_elem = bill.find('introducedDate')
        
        if congress is None or bill_type_elem is None or bill_number_elem is None:
            return None, None, []
        
        congress_num = int(congress.text)
        bill_type = bill_type_elem.text
        bill_number = bill_number_elem.text
        official_bill_number = f"{bill_type}{bill_number}"
        
        introduced_date = None
        if introduced_date_elem is not None and introduced_date_elem.text:
            try:
                introduced_date = datetime.strptime(introduced_date_elem.text, "%Y-%m-%d").date()
            except:
                pass
        
        bill_info = {
            'official_bill_number': official_bill_number,
            'congress': congress_num,
            'introduced_date': introduced_date
        }
        
        # Extract sponsor bioguide ID
        sponsors = bill.find('.//sponsors')
        sponsor_bioguide_id = None
        if sponsors is not None:
            sponsor = sponsors.find('item')
            if sponsor is not None:
                bioguide_elem = sponsor.find('bioguideId')
                if bioguide_elem is not None:
                    sponsor_bioguide_id = bioguide_elem.text
        
        # Extract cosponsors
        cosponsors_list = []
        cosponsors = bill.find('.//cosponsors')
        if cosponsors is not None:
            for cosponsor in cosponsors.findall('item'):
                bioguide_elem = cosponsor.find('bioguideId')
                sponsorship_date_elem = cosponsor.find('sponsorshipDate')
                is_original_elem = cosponsor.find('isOriginalCosponsor')
                
                if bioguide_elem is not None:
                    bioguide_id = bioguide_elem.text
                    
                    sponsorship_date = None
                    if sponsorship_date_elem is not None and sponsorship_date_elem.text:
                        try:
                            sponsorship_date = datetime.strptime(sponsorship_date_elem.text, "%Y-%m-%d").date()
                        except:
                            pass
                    
                    is_original = False
                    if is_original_elem is not None and is_original_elem.text:
                        is_original = is_original_elem.text.lower() == 'true'
                    
                    cosponsors_list.append({
                        'bioguide_id': bioguide_id,
                        'sponsorship_date': sponsorship_date,
                        'is_original_cosponsor': is_original
                    })
        
        return bill_info, sponsor_bioguide_id, cosponsors_list
        
    except Exception as e:
        print(f"    Error parsing {xml_path}: {e}")
        return None, None, []


def scan_congress_bills(congress, since_date):
    """Scan congress repo for bills introduced since a date (truly new bills only)."""
    congress_dir = CONGRESS_DATA_DIR / str(congress) / "bills"
    
    if not congress_dir.exists():
        print(f"  Congress {congress} directory not found: {congress_dir}")
        return []
    
    bills_data = []
    
    # Bill types to check
    bill_types = ['hr', 's', 'hres', 'sres', 'hjres', 'sjres', 'hconres', 'sconres']
    
    for bill_type in bill_types:
        bill_type_dir = congress_dir / bill_type
        
        if not bill_type_dir.exists():
            continue
        
        # Iterate through bill folders
        for bill_folder in bill_type_dir.iterdir():
            if not bill_folder.is_dir():
                continue
            
            xml_file = bill_folder / "fdsys_billstatus.xml"
            
            if not xml_file.exists():
                continue
            
            # Parse sponsors and cosponsors
            bill_info, sponsor_bioguide, cosponsors = parse_sponsors_and_cosponsors(xml_file)
            if not bill_info:
                continue
            
            # Only include bills introduced since last update (truly new bills)
            introduced_date = bill_info.get('introduced_date')
            if introduced_date and introduced_date >= since_date.date():
                bills_data.append({
                    'bill': bill_info,
                    'sponsor_bioguide': sponsor_bioguide,
                    'cosponsors': cosponsors
                })
    
    return bills_data


def update_sponsors(bills_data):
    """Update sponsor_id and date_introduced for bills."""
    if not bills_data:
        return 0
    
    updated = 0
    
    with engine.connect() as conn:
        for data in bills_data:
            bill_info = data['bill']
            sponsor_bioguide = data['sponsor_bioguide']
            
            official_bill_number = bill_info['official_bill_number']
            introduced_date = bill_info['introduced_date']
            
            # Get politician_id for sponsor
            sponsor_id = get_politician_id(sponsor_bioguide) if sponsor_bioguide else None
            
            try:
                # Update bill with sponsor_id and date_introduced
                conn.execute(
                    sqlalchemy.text(
                        """UPDATE bills 
                           SET sponsor_id = :sponsor_id, 
                               date_introduced = :introduced_date
                           WHERE official_bill_number = :bill_num"""
                    ),
                    {
                        "sponsor_id": sponsor_id,
                        "introduced_date": introduced_date,
                        "bill_num": official_bill_number
                    }
                )
                conn.commit()
                updated += 1
                
            except Exception as e:
                print(f"    Error updating sponsor for {official_bill_number}: {e}")
    
    return updated


def update_cosponsors(bills_data):
    """Insert or update bill cosponsors."""
    if not bills_data:
        return 0
    
    bill_cosponsors_table = sqlalchemy.Table('bill_cosponsors', sqlalchemy.MetaData(), autoload_with=engine)
    
    total_updated = 0
    
    with engine.connect() as conn:
        for data in bills_data:
            bill_info = data['bill']
            cosponsors = data['cosponsors']
            
            if not cosponsors:
                continue
            
            official_bill_number = bill_info['official_bill_number']
            
            # Get bill_id
            bill_id = get_bill_id(official_bill_number)
            if not bill_id:
                continue
            
            for cosponsor in cosponsors:
                bioguide_id = cosponsor['bioguide_id']
                
                # Get politician_id
                politician_id = get_politician_id(bioguide_id)
                if not politician_id:
                    continue
                
                try:
                    stmt = pg_insert(bill_cosponsors_table).values({
                        'bill_id': bill_id,
                        'politician_id': politician_id,
                        'sponsorship_date': cosponsor['sponsorship_date'],
                        'is_original_cosponsor': cosponsor['is_original_cosponsor']
                    })
                    
                    # On conflict, update dates and original flag
                    update_stmt = stmt.on_conflict_do_update(
                        index_elements=['bill_id', 'politician_id'],
                        set_={
                            'sponsorship_date': stmt.excluded.sponsorship_date,
                            'is_original_cosponsor': stmt.excluded.is_original_cosponsor
                        }
                    )
                    
                    conn.execute(update_stmt)
                    conn.commit()
                    total_updated += 1
                    
                except Exception as e:
                    print(f"    Error upserting cosponsor for {official_bill_number}: {e}")
    
    return total_updated


def main():
    """Main function to update sponsors and cosponsors incrementally."""
    
    print("Starting incremental sponsors and cosponsors update...\n")
    print("=" * 80)
    
    if not CONGRESS_DATA_DIR.exists():
        print(f"  ERROR: Congress repo not found at {CONGRESS_DATA_DIR}")
        print("  Please clone and setup congress repo first.")
        return
    
    # Get last update dates (use the older of the two)
    last_update_sponsors = get_last_update_date("bill_sponsors")
    last_update_cosponsors = get_last_update_date("bill_cosponsors")
    
    last_update = min(last_update_sponsors, last_update_cosponsors)
    
    print(f"  Last sponsors update: {last_update_sponsors.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Last cosponsors update: {last_update_cosponsors.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Checking for bills introduced since: {last_update.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    total_bills_found = 0
    total_sponsors_updated = 0
    total_cosponsors_updated = 0
    
    # Process in reverse order (119 first) to prioritize current congress
    for congress in sorted(CONGRESSES_TO_CHECK, reverse=True):
        print(f"--- Congress {congress} ---")
        
        # Scan congress repo for newly introduced bills
        bills_data = scan_congress_bills(congress, last_update)
        
        print(f"  Found {len(bills_data)} bills introduced since last update")
        
        if bills_data:
            # Update sponsors
            sponsors_updated = update_sponsors(bills_data)
            total_sponsors_updated += sponsors_updated
            print(f"  Updated {sponsors_updated} sponsors")
            
            # Update cosponsors
            cosponsors_updated = update_cosponsors(bills_data)
            total_cosponsors_updated += cosponsors_updated
            print(f"  Updated/inserted {cosponsors_updated} cosponsors")
        
        total_bills_found += len(bills_data)
        print()
    
    # Log the updates
    log_update("bill_sponsors", total_sponsors_updated, "success")
    log_update("bill_cosponsors", total_cosponsors_updated, "success")
    
    print("=" * 80)
    print("Sponsors and cosponsors update completed!")
    print(f"Total bills processed: {total_bills_found}")
    print(f"Total sponsors updated: {total_sponsors_updated}")
    print(f"Total cosponsors updated: {total_cosponsors_updated}")
    print("=" * 80)


if __name__ == "__main__":
    main()
