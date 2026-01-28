"""
Incremental update script for bills table.
Uses congress scraping tool to download new bills, then parses XML.
Downloads bills introduced since last update, then updates bills and sponsors.
"""
import os
import subprocess
import sqlalchemy
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timedelta
from pathlib import Path
import time

load_dotenv()
DB_URL = os.getenv('DB_URL')

# Paths for congress repo tool
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
BASE_DIR = PROJECT_DIR.parent  # Politicians ETL PostgreSQL Project
CONGRESS_REPO_DIR = BASE_DIR / "congress"
CONGRESS_DATA_DIR = CONGRESS_REPO_DIR / "congress" / "data"
CONGRESS_VENV_PYTHON = CONGRESS_REPO_DIR / "venv_congress" / "Scripts" / "python.exe"

CONGRESSES_TO_CHECK = [119]  # Current congress first
BILL_TYPES = ['hr', 's', 'hres', 'sres', 'hjres', 'sjres', 'hconres', 'sconres']

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
    
    # Default: check bills from last 7 days if no previous update
    return datetime.now() - timedelta(days=7)


def get_existing_bills():
    """Get set of existing bill tuples (official_bill_number, congress) for deduplication."""
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT official_bill_number, congress FROM bills"
        ))
        return {(row.official_bill_number, row.congress) for row in result.fetchall()}


def get_highest_bill_number(congress, bill_type):
    """Get the highest bill number for a given congress and bill type from database."""
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(
                """SELECT MAX(CAST(SUBSTRING(official_bill_number FROM '[0-9]+') AS INTEGER)) as max_num
                   FROM bills 
                   WHERE congress = :congress AND bill_type = :bill_type"""
            ),
            {"congress": congress, "bill_type": bill_type.upper()}
        )
        row = result.fetchone()
        return row.max_num if row.max_num else 0


def scrape_bill(congress, bill_type, bill_number, verbose=False):
    """
    Use congress scraping tool to download a specific bill.
    Returns the path to the XML file if successful, None otherwise.
    """
    bill_id = f"{bill_type.lower()}{bill_number}-{congress}"
    xml_path = CONGRESS_DATA_DIR / str(congress) / "bills" / bill_type.lower() / f"{bill_type.lower()}{bill_number}" / "fdsys_billstatus.xml"
    
    # Check if file already exists (from previous download)
    if xml_path.exists() and xml_path.stat().st_size > 0:
        return xml_path
    
    # Build command
    cmd = [
        str(CONGRESS_VENV_PYTHON),
        "run.py",
        "bills",
        f"--bill_id={bill_id}"
    ]
    
    if verbose:
        print(f"        Running: {' '.join(cmd)}")
        print(f"        Working dir: {CONGRESS_DATA_DIR.parent}")
    
    try:
        # Run the scraper with longer timeout
        result = subprocess.run(
            cmd,
            cwd=str(CONGRESS_DATA_DIR.parent),  # congress/congress directory
            capture_output=True,
            text=True,
            timeout=360  # 6 minutes
        )
        
        if verbose:
            print(f"        Return code: {result.returncode}")
            if result.stdout:
                print(f"        Stdout: {result.stdout[:200]}")
            if result.stderr:
                print(f"        Stderr: {result.stderr[:200]}")
        
        # Wait for file to be created (up to 10 seconds)
        for i in range(20):
            if xml_path.exists() and xml_path.stat().st_size > 0:
                time.sleep(0.5)  # Brief pause to ensure file is complete
                return xml_path
            time.sleep(0.5)
        
        # File wasn't created - bill probably doesn't exist
        if verbose:
            print(f"        File not created: {xml_path}")
        return None
        
    except subprocess.TimeoutExpired:
        print(f"      ⏱ Timeout scraping {bill_type.upper()}{bill_number}")
        return None
    except Exception as e:
        print(f"      ❌ Error scraping {bill_type.upper()}{bill_number}: {e}")
        return None


def parse_bill_xml(xml_path):
    """Parse bill data, sponsor, and cosponsors from fdsys_billstatus.xml file."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Extract bill info
        bill = root.find('.//bill')
        if bill is None:
            return None
        
        congress = bill.find('congress')
        bill_type_elem = bill.find('type')
        bill_number_elem = bill.find('number')
        title_elem = bill.find('.//title')
        introduced_date_elem = bill.find('introducedDate')
        
        if congress is None or bill_type_elem is None or bill_number_elem is None:
            return None
        
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
        
        # Title
        title = title_elem.text if title_elem is not None and title_elem.text else None
        
        # Extract sponsor bioguide ID
        sponsors = bill.find('.//sponsors')
        sponsor_bioguide_id = None
        if sponsors is not None:
            sponsor = sponsors.find('item')
            if sponsor is not None:
                bioguide_elem = sponsor.find('bioguideId')
                if bioguide_elem is not None:
                    sponsor_bioguide_id = bioguide_elem.text
        
        # Extract summary
        summary_text = None
        summaries = root.find('.//summaries')
        if summaries is not None:
            summary = summaries.find('summary')
            if summary is not None:
                cdata = summary.find('cdata')
                if cdata is not None:
                    text = cdata.find('text')
                    if text is not None and text.text:
                        summary_text = text.text.strip()
        
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
        
        return {
            'bill': {
                'official_bill_number': official_bill_number,
                'congress': congress_num,
                'bill_type': bill_type,
                'title': title,
                'date_introduced': introduced_date,
                'summary': summary_text,
                'sponsor_bioguide_id': sponsor_bioguide_id
            },
            'cosponsors': cosponsors_list
        }
        
    except Exception as e:
        print(f"      Error parsing {xml_path}: {e}")
        return None


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


def upsert_bill_and_cosponsors(bill_data, cosponsors_data):
    """Insert bill and its cosponsors into database."""
    
    # Get politician_id for sponsor
    sponsor_bioguide = bill_data.pop('sponsor_bioguide_id', None)
    bill_data['sponsor_id'] = get_politician_id(sponsor_bioguide)
    
    bills_table = sqlalchemy.Table('bills', sqlalchemy.MetaData(), autoload_with=engine)
    bill_cosponsors_table = sqlalchemy.Table('bill_cosponsors', sqlalchemy.MetaData(), autoload_with=engine)
    
    with engine.connect() as conn:
        try:
            # Upsert bill
            stmt = pg_insert(bills_table).values(bill_data)
            
            update_stmt = stmt.on_conflict_do_update(
                index_elements=['official_bill_number', 'congress'],
                set_={
                    'title': stmt.excluded.title,
                    'date_introduced': stmt.excluded.date_introduced,
                    'sponsor_id': stmt.excluded.sponsor_id,
                    'summary': stmt.excluded.summary
                }
            )
            
            conn.execute(update_stmt)
            conn.commit()
            
            # Get bill_id
            result = conn.execute(
                sqlalchemy.text(
                    "SELECT bill_id FROM bills WHERE official_bill_number = :bill_num AND congress = :congress"
                ),
                {"bill_num": bill_data['official_bill_number'], "congress": bill_data['congress']}
            )
            row = result.fetchone()
            bill_id = row.bill_id if row else None
            
            if not bill_id:
                return False
            
            # Upsert cosponsors
            cosponsors_added = 0
            for cosponsor in cosponsors_data:
                politician_id = get_politician_id(cosponsor['bioguide_id'])
                if not politician_id:
                    continue
                
                try:
                    cosponsor_stmt = pg_insert(bill_cosponsors_table).values({
                        'bill_id': bill_id,
                        'politician_id': politician_id,
                        'sponsorship_date': cosponsor['sponsorship_date'],
                        'is_original_cosponsor': cosponsor['is_original_cosponsor']
                    })
                    
                    cosponsor_update_stmt = cosponsor_stmt.on_conflict_do_update(
                        index_elements=['bill_id', 'politician_id'],
                        set_={
                            'sponsorship_date': cosponsor_stmt.excluded.sponsorship_date,
                            'is_original_cosponsor': cosponsor_stmt.excluded.is_original_cosponsor
                        }
                    )
                    
                    conn.execute(cosponsor_update_stmt)
                    conn.commit()
                    cosponsors_added += 1
                except:
                    pass
            
            return True
            
        except Exception as e:
            print(f"      Error upserting bill: {e}")
            return False
    """Scan congress repo for bills introduced since last update (new bills only)."""
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
        
        # Iterate through bill folders (e.g., hr1, hr2, etc.)
        for bill_folder in bill_type_dir.iterdir():
            if not bill_folder.is_dir():
                continue
            
            xml_file = bill_folder / "fdsys_billstatus.xml"
            
            if not xml_file.exists():
                continue
            
            # Parse the XML first to get bill info
            bill_data = parse_bill_xml(xml_file)
            if not bill_data:
                continue
            
            official_bill_number = bill_data['official_bill_number']
            introduced_date = bill_data.get('date_introduced')
            congress_num = bill_data.get('congress')
            
            # Only include NEW bills introduced since last update
            # Skip bills that already exist in DB (check by bill number + congress)
            if (official_bill_number, congress_num) in existing_bills_set:
                continue
            
            # Only include bills introduced recently (not old bills from bulk download)
            if not introduced_date or introduced_date < since_date.date():
                continue
            
            bills_data.append(bill_data)
    
    return bills_data


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


def main():
    """Main function to update bills incrementally by scraping new bills."""
    
    print("Starting incremental bills update...\n")
    print("=" * 80)
    
    if not CONGRESS_REPO_DIR.exists() or not CONGRESS_VENV_PYTHON.exists():
        print(f"  ERROR: Congress repo or venv not found")
        print(f"  Repo: {CONGRESS_REPO_DIR}")
        print(f"  Venv: {CONGRESS_VENV_PYTHON}")
        return
    
    # Get last update date
    last_update = get_last_update_date("bills")
    print(f"  Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Scraping bills introduced since then...\n")
    
    # Get existing bills
    existing_bills_set = get_existing_bills()
    print(f"  Current database has {len(existing_bills_set)} bills\n")
    
    total_bills_scraped = 0
    total_bills_added = 0
    
    # Process current congress first
    for congress in CONGRESSES_TO_CHECK:
        print(f"--- Congress {congress} ---")
        
        congress_bills_found = 0
        
        for bill_type in BILL_TYPES:
            # Get highest bill number in database for this type
            max_bill_num = get_highest_bill_number(congress, bill_type)
            
            print(f"  {bill_type.upper()}: Starting from {bill_type.upper()}{max_bill_num + 1}")
            
            # Try scraping next bills incrementally
            consecutive_failures = 0
            bill_num = max_bill_num + 1
            bills_checked = 0
            
            while consecutive_failures < 10 and bills_checked < 50:  # Check up to 50 bills, stop after 10 consecutive failures
                official_bill_number = f"{bill_type.upper()}{bill_num}"
                
                # Skip if already exists
                if (official_bill_number, congress) in existing_bills_set:
                    bill_num += 1
                    bills_checked += 1
                    consecutive_failures = 0  # Reset since we found a bill
                    continue
                
                # Scrape the bill (verbose on first 2 attempts for debugging)
                verbose = bills_checked < 2
                xml_path = scrape_bill(congress, bill_type, bill_num, verbose=verbose)
                
                if xml_path:
                    # Parse the XML
                    parsed_data = parse_bill_xml(xml_path)
                    
                    if parsed_data:
                        bill_data = parsed_data['bill']
                        cosponsors = parsed_data['cosponsors']
                        
                        # Check if introduced recently
                        introduced_date = bill_data.get('date_introduced')
                        if introduced_date and introduced_date >= last_update.date():
                            # Upsert to database
                            if upsert_bill_and_cosponsors(bill_data, cosponsors):
                                print(f"      ✓ {official_bill_number} added ({len(cosponsors)} cosponsors)")
                                total_bills_added += 1
                                congress_bills_found += 1
                                consecutive_failures = 0
                            else:
                                print(f"      ✗ {official_bill_number} failed to save")
                                consecutive_failures += 1
                        else:
                            # Old bill - but it exists, so reset counter
                            if verbose:
                                print(f"      → {official_bill_number} introduced before cutoff ({introduced_date})")
                            consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                    
                    total_bills_scraped += 1
                else:
                    consecutive_failures += 1
                    if verbose:
                        print(f"      ○ {official_bill_number} not found")
                
                bill_num += 1
                bills_checked += 1
                time.sleep(0.5)  # Rate limiting
            
            if consecutive_failures >= 10:
                print(f"      → No more {bill_type.upper()} bills found (10 consecutive missing)")
            elif bills_checked >= 50:
                print(f"      → Checked 50 bills for {bill_type.upper()}, stopping")
        
        print(f"  Total new bills found in Congress {congress}: {congress_bills_found}\n")
    
    # Log the update
    log_update("bills", total_bills_added, "success")
    
    print("=" * 80)
    print("Bills update completed!")
    print(f"Total bills scraped: {total_bills_scraped}")
    print(f"Total bills added to DB: {total_bills_added}")
    print("=" * 80)


if __name__ == "__main__":
    main()
