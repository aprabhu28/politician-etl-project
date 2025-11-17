"""
Incremental update script for donations table.
Downloads and processes only the latest FEC weekly file.
Much faster than re-processing all historical data.
"""
import os
import requests
import zipfile
import csv
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime
from pathlib import Path
import time

load_dotenv()
DB_URL = os.getenv('DB_URL')
FEC_API_KEY = os.getenv('FEC_API_KEY')

# FEC bulk data endpoints
FEC_BULK_DATA_URL = "https://www.fec.gov/files/bulk-downloads"

# Temp directory for downloaded files
TEMP_DIR = Path(__file__).parent.parent / "data" / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

try:
    engine = create_engine(DB_URL)
    print("  Database connection successful.\n")
except Exception as e:
    print(f"  Database connection failed: {e}")
    exit()


def log_update(table_name, records_updated, status="success", notes=None):
    """Log update to update_log table."""
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(
            """INSERT INTO update_log (table_name, last_update, records_updated, status, notes)
               VALUES (:table_name, CURRENT_TIMESTAMP, :records_updated, :status, :notes)"""
        ), {
            "table_name": table_name,
            "records_updated": records_updated,
            "status": status,
            "notes": notes
        })
        conn.commit()


def get_last_processed_date():
    """Get the last date we processed donations."""
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            """SELECT last_update FROM update_log 
               WHERE table_name = 'donations' AND status = 'success'
               ORDER BY last_update DESC LIMIT 1"""
        ))
        
        row = result.fetchone()
        if row:
            return row.last_update
    
    return None


def download_latest_fec_file(year=2024):
    """Download the latest FEC individual contributions file for a given year."""
    
    # FEC provides weekly files - we'll download the full file for the current cycle
    # For a truly incremental approach, you'd want to track which weekly files you've processed
    
    file_url = f"{FEC_BULK_DATA_URL}/{year}/indiv{year % 100}.zip"
    
    print(f"    Downloading FEC data from: {file_url}")
    
    zip_path = TEMP_DIR / f"indiv{year}.zip"
    
    try:
        response = requests.get(file_url, stream=True)
        
        if response.status_code != 200:
            print(f"      Failed to download: {response.status_code}")
            return None
        
        # Download with progress indicator
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded = 0
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"    Progress: {percent:.1f}%", end='\r')
        
        print(f"\n      Downloaded: {zip_path}")
        
        # Extract the zip file
        extract_dir = TEMP_DIR / f"indiv{year}"
        extract_dir.mkdir(exist_ok=True)
        
        print(f"      Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # Find the extracted CSV file
        csv_files = list(extract_dir.glob("*.txt"))
        if not csv_files:
            print(f"      No CSV files found in extracted archive")
            return None
        
        csv_path = csv_files[0]
        print(f"      Extracted: {csv_path}")
        
        return csv_path
        
    except Exception as e:
        print(f"      Error downloading file: {e}")
        return None


def process_fec_file(file_path, since_date=None):
    """Process FEC file and insert/update donations."""
    
    print(f"\n    Processing: {file_path.name}")
    
    # Get column mapping from header file
    header_file = Path(__file__).parent.parent / "data" / "indiv_header_file.csv"
    
    if not header_file.exists():
        print(f"       Header file not found: {header_file}")
        print("    Using default column names...")
        column_names = None
    else:
        with open(header_file, 'r') as f:
            reader = csv.reader(f)
            column_names = next(reader)
    
    donations_to_upsert = []
    donors_to_upsert = {}
    
    row_count = 0
    skipped_count = 0
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            if column_names:
                reader = csv.DictReader(f, fieldnames=column_names, delimiter='|')
            else:
                reader = csv.reader(f, delimiter='|')
            
            for row_data in reader:
                row_count += 1
                
                # Show progress every 10k rows
                if row_count % 10000 == 0:
                    print(f"    Processed {row_count:,} rows...", end='\r')
                
                try:
                    if column_names:
                        row = row_data
                    else:
                        # Without header, we need to map by index
                        # This is a fallback - ideally use the header file
                        row = {f'col_{i}': val for i, val in enumerate(row_data)}
                    
                    # Parse date
                    transaction_date_str = row.get('TRANSACTION_DT', '')
                    if transaction_date_str:
                        try:
                            transaction_date = datetime.strptime(transaction_date_str, "%m%d%Y").date()
                        except:
                            transaction_date = None
                    else:
                        transaction_date = None
                    
                    # If we're doing incremental updates, skip old records
                    if since_date and transaction_date and transaction_date < since_date.date():
                        skipped_count += 1
                        continue
                    
                    # Parse donation amount
                    amount_str = row.get('TRANSACTION_AMT', '0')
                    try:
                        amount = float(amount_str)
                    except:
                        amount = 0.0
                    
                    # Extract donor info
                    donor_name = row.get('NAME', '')
                    donor_city = row.get('CITY', '')
                    donor_state = row.get('STATE', '')
                    donor_zip = row.get('ZIP_CODE', '')
                    donor_employer = row.get('EMPLOYER', '')
                    donor_occupation = row.get('OCCUPATION', '')
                    
                    # Create unique donor key
                    donor_key = f"{donor_name}_{donor_city}_{donor_state}_{donor_zip}"
                    
                    # Track unique donors
                    if donor_key not in donors_to_upsert:
                        donors_to_upsert[donor_key] = {
                            "donor_source_key": donor_key,
                            "name": donor_name,
                            "city": donor_city,
                            "state": donor_state,
                            "zip_code": donor_zip,
                            "employer": donor_employer,
                            "occupation": donor_occupation
                        }
                    
                    # Extract recipient committee ID
                    committee_id = row.get('CMTE_ID', '')
                    
                    # Create donation record
                    donation_data = {
                        "donor_key": donor_key,
                        "committee_id": committee_id,
                        "amount": amount,
                        "transaction_date": transaction_date,
                        "transaction_type": row.get('TRANSACTION_TP', ''),
                        "memo_text": row.get('MEMO_TEXT', '')
                    }
                    
                    donations_to_upsert.append(donation_data)
                    
                    # Batch insert every 5000 records
                    if len(donations_to_upsert) >= 5000:
                        insert_batch(donors_to_upsert, donations_to_upsert)
                        donations_to_upsert = []
                        # Keep donors dict to avoid re-inserting
                    
                except Exception as e:
                    print(f"        Error parsing row {row_count}: {e}")
                    continue
        
        # Insert remaining records
        if donations_to_upsert:
            insert_batch(donors_to_upsert, donations_to_upsert)
        
            print(f"\n      Processed {row_count:,} total rows")
        print(f"      Skipped {skipped_count:,} old records")
        print(f"      Inserted/updated {row_count - skipped_count:,} donations")
        
        return row_count - skipped_count
        
    except Exception as e:
        print(f"      Error processing file: {e}")
        return 0


def insert_batch(donors_dict, donations_list):
    """Insert batch of donors and donations."""
    
    # First, upsert donors
    donors_table = sqlalchemy.Table('donors', sqlalchemy.MetaData(), autoload_with=engine)
    
    with engine.connect() as conn:
        for donor_data in donors_dict.values():
            try:
                stmt = pg_insert(donors_table).values(donor_data)
                update_stmt = stmt.on_conflict_do_nothing(
                    index_elements=['donor_source_key']
                )
                conn.execute(update_stmt)
            except Exception as e:
                print(f"        Error inserting donor: {e}")
        
        conn.commit()
    
    # Then insert donations
    # First need to look up donor IDs
    enriched_donations = []
    
    with engine.connect() as conn:
        for donation in donations_list:
            donor_key = donation['donor_key']
            
            result = conn.execute(
                sqlalchemy.text("SELECT id FROM donors WHERE donor_source_key = :key"),
                {"key": donor_key}
            )
            donor = result.fetchone()
            
            if donor:
                enriched_donations.append({
                    "donor_id": donor.id,
                    "recipient_committee_id": donation['committee_id'],
                    "amount": donation['amount'],
                    "transaction_date": donation['transaction_date'],
                    "transaction_type": donation['transaction_type'],
                    "memo_text": donation['memo_text']
                })
    
    # Bulk insert donations
    if enriched_donations:
        donations_table = sqlalchemy.Table('donations', sqlalchemy.MetaData(), autoload_with=engine)
        
        with engine.connect() as conn:
            conn.execute(donations_table.insert(), enriched_donations)
            conn.commit()


def main():
    """Main function to update donations incrementally."""
    
    print("  Starting incremental donations update...\n")
    print("=" * 80)
    
    # Get last update date
    last_update = get_last_processed_date()
    
    if last_update:
        print(f"  Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f" Processing donations after this date...\n")
    else:
        print("  No previous update found. Processing all available data.\n")
    
    # Download latest FEC file
    current_year = datetime.now().year
    fec_file = download_latest_fec_file(current_year)
    
    if not fec_file:
        print("  Failed to download FEC file")
        log_update("donations", 0, "error", "Failed to download FEC file")
        return
    
    # Process the file
    donations_added = process_fec_file(fec_file, since_date=last_update)
    
    # Log the update
    log_update("donations", donations_added, "success", f"Processed {current_year} FEC file")
    
    # Clean up temp files
    print("\n  Cleaning up temporary files...")
    try:
        fec_file.unlink()
        fec_file.parent.rmdir()
        (TEMP_DIR / f"indiv{current_year}.zip").unlink()
    except:
        pass
    
    print("\n" + "=" * 80)
    print("  Donations update completed!")
    print(f"  Total donations added/updated: {donations_added:,}")
    print("=" * 80)


if __name__ == "__main__":
    main()
