"""
Script to populate the summary column in the bills table.
Uses the congress project tool to scrape bill summaries from congress data.
Only scrapes bills from 118th and 119th Congress.
"""
import os
import subprocess
import sqlalchemy
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from sqlalchemy.engine import create_engine
from pathlib import Path
import time

load_dotenv()
DB_URL = os.getenv('DB_URL')

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
BASE_DIR = PROJECT_DIR.parent  # Politicians ETL PostgreSQL Project
CONGRESS_REPO_DIR = BASE_DIR / "congress"
CONGRESS_DATA_DIR = CONGRESS_REPO_DIR / "congress" / "data"
CONGRESS_VENV_PYTHON = CONGRESS_REPO_DIR / "venv_congress" / "Scripts" / "python.exe"

# Only scrape summaries for these congresses
CONGRESSES_TO_SCRAPE = [118, 119]

try:
    engine = create_engine(DB_URL)
    print("Database connection successful.\n")
except Exception as e:
    print(f"Database connection failed: {e}")
    exit()


def get_bills_without_summaries():
    """Fetch all bills from 118th and 119th Congress that don't have summaries yet."""
    print("Fetching bills without summaries...")
    
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            """SELECT bill_id, official_bill_number, congress, bill_type 
               FROM bills 
               WHERE (summary IS NULL OR summary = '')
               AND congress IN (118, 119)
               ORDER BY congress ASC, bill_id"""  # Process 118th first (more likely to have summaries)
        ))
        bills = [{
            "bill_id": row.bill_id,
            "official_bill_number": row.official_bill_number,
            "congress": row.congress,
            "bill_type": row.bill_type
        } for row in result]
    
    print(f"Found {len(bills)} bills without summaries\n")
    return bills


def scrape_bill_data(congress, bill_type, bill_number):
    """
    Run the congress project tool to download and scrape a specific bill.
    Returns True if successful, False otherwise.
    """
    bill_id = f"{bill_type.lower()}{bill_number}-{congress}"
    
    # Step 1: Download bill data from govinfo
    govinfo_cmd = [
        str(CONGRESS_VENV_PYTHON),
        "run.py",
        "govinfo",
        "--bulkdata=BILLSTATUS",
        f"--congress={congress}",
        f"--extract=mods,xml,premis",
        f"--bill_id={bill_id}"
    ]
    
    try:
        # Download from govinfo first
        result = subprocess.run(
            govinfo_cmd,
            cwd=str(CONGRESS_DATA_DIR.parent),
            capture_output=True,
            text=True,
            timeout=180  # Give more time for downloads
        )
        
        if result.returncode != 0:
            return False
        
        # Step 2: Process the downloaded data with bills task
        bills_cmd = [
            str(CONGRESS_VENV_PYTHON),
            "run.py",
            "bills",
            f"--bill_id={bill_id}"
        ]
        
        result = subprocess.run(
            bills_cmd,
            cwd=str(CONGRESS_DATA_DIR.parent),
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Check if the bill folder was created
            bill_dir = CONGRESS_DATA_DIR / str(congress) / "bills" / bill_type.lower() / f"{bill_type.lower()}{bill_number}"
            return bill_dir.exists()
        else:
            return False
            
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        return False


def extract_summary_from_bill_data(congress, bill_type, bill_number):
    """
    Extract summary text from the scraped bill XML file.
    Returns summary text or None if not found.
    """
    bill_dir = CONGRESS_DATA_DIR / str(congress) / "bills" / bill_type.lower() / f"{bill_type.lower()}{bill_number}"
    xml_file = bill_dir / "fdsys_billstatus.xml"
    
    if not xml_file.exists():
        return None
    
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Navigate to summaries -> summary -> cdata -> text
        summaries = root.find('.//summaries')
        if summaries is not None:
            summary = summaries.find('summary')
            if summary is not None:
                cdata = summary.find('cdata')
                if cdata is not None:
                    text_elem = cdata.find('text')
                    if text_elem is not None and text_elem.text:
                        return text_elem.text.strip()
        
        return None
        
    except Exception as e:
        print(f"      Error reading bill XML: {e}")
        return None


def batch_update_summaries(bill_updates):
    """Batch update summaries for multiple bills in the database."""
    if not bill_updates:
        return 0
    
    try:
        with engine.connect() as conn:
            for update in bill_updates:
                conn.execute(
                    sqlalchemy.text(
                        "UPDATE bills SET summary = :summary WHERE bill_id = :bill_id"
                    ),
                    {"summary": update['summary'], "bill_id": update['bill_id']}
                )
            conn.commit()
            return len(bill_updates)
    except Exception as e:
        print(f"      Error batch updating summaries: {e}")
        return 0


def cleanup_bill_folder(congress, bill_type, bill_number):
    """Delete the scraped bill folder to save disk space."""
    bill_dir = CONGRESS_DATA_DIR / str(congress) / "bills" / bill_type.lower() / f"{bill_type.lower()}{bill_number}"
    
    try:
        if bill_dir.exists():
            import shutil
            shutil.rmtree(bill_dir)
            return True
    except Exception as e:
        print(f"      Warning: Could not delete {bill_dir}: {e}")
    return False


def main():
    """Main function to populate bill summaries."""
    
    print("Starting bill summaries population using congress repo tool...\n")
    print("=" * 80)
    
    # Validate paths
    if not CONGRESS_REPO_DIR.exists():
        print(f"ERROR: Congress repo not found at: {CONGRESS_REPO_DIR}")
        print("Please ensure the congress repo is cloned in the parent directory.")
        return
    
    if not CONGRESS_VENV_PYTHON.exists():
        print(f"ERROR: venv_congress Python not found at: {CONGRESS_VENV_PYTHON}")
        print("Please ensure venv_congress is set up correctly.")
        return
    
    bills = get_bills_without_summaries()
    
    if not bills:
        print("All bills already have summaries!")
        return
    
    total_updated = 0
    total_no_summary = 0
    total_scrape_failed = 0
    total_cleaned = 0
    
    # Batch processing
    BATCH_SIZE = 100
    batch_updates = []
    bills_to_cleanup = []
    
    for idx, bill in enumerate(bills, 1):
        bill_id = bill['bill_id']
        official_bill_number = bill['official_bill_number']
        congress = bill['congress']
        bill_type = bill['bill_type']
        
        # Extract numeric bill number from official_bill_number
        bill_number = official_bill_number.replace(bill_type.upper(), "")
        
        print(f"[{idx}/{len(bills)}] {official_bill_number} (Congress {congress})...", end=" ")
        
        # Check if bill data already exists locally
        bill_dir = CONGRESS_DATA_DIR / str(congress) / "bills" / bill_type.lower() / f"{bill_type.lower()}{bill_number}"
        was_scraped = False
        
        if not bill_dir.exists():
            # Scrape the bill
            print("Scraping...", end=" ")
            if not scrape_bill_data(congress, bill_type, bill_number):
                total_scrape_failed += 1
                print("SCRAPE FAILED")
                time.sleep(1)
                continue
            print("Scraped.", end=" ")
            was_scraped = True
        else:
            print("Cached.", end=" ")
        
        # Extract summary from bill data
        summary_text = extract_summary_from_bill_data(congress, bill_type, bill_number)
        
        if summary_text:
            # Add to batch
            batch_updates.append({
                'bill_id': bill_id,
                'summary': summary_text,
                'official_bill_number': official_bill_number
            })
            bills_to_cleanup.append((congress, bill_type, bill_number))
            
            summary_preview = summary_text[:80] + "..." if len(summary_text) > 80 else summary_text
            print(f"Queued for batch")
        else:
            total_no_summary += 1
            print("No summary in XML")
        
        # Process batch when full or at end
        if len(batch_updates) >= BATCH_SIZE or idx == len(bills):
            if batch_updates:
                print(f"\n  → Batch updating {len(batch_updates)} summaries to database...", end=" ")
                updated = batch_update_summaries(batch_updates)
                total_updated += updated
                print(f"Done ({updated} updated)")
                
                # Cleanup scraped folders after successful DB update
                print(f"  → Cleaning up {len(bills_to_cleanup)} folders...", end=" ")
                for cleanup_bill in bills_to_cleanup:
                    if cleanup_bill_folder(*cleanup_bill):
                        total_cleaned += 1
                print(f"Done ({total_cleaned} deleted)\n")
                
                # Clear batch
                batch_updates = []
                bills_to_cleanup = []
        
        # Progress report
        if idx % 50 == 0:
            print(f"\n{'='*80}")
            print(f"PROGRESS: Processed {idx}/{len(bills)} bills")
            print(f"Updated: {total_updated} | No summary: {total_no_summary} | Scrape failed: {total_scrape_failed}")
            print(f"Cleaned up: {total_cleaned} folders")
            print(f"{'='*80}\n")
            time.sleep(1)
        else:
            time.sleep(0.3)
    
    print("\n" + "=" * 80)
    print("Bill summaries population completed!")
    print(f"Total updated: {total_updated}")
    print(f"No summary available: {total_no_summary}")
    print(f"Scrape failed: {total_scrape_failed}")
    print(f"Folders cleaned up: {total_cleaned}")
    print("=" * 80)


if __name__ == "__main__":
    main()
