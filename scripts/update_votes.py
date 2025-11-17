"""
Incremental update script for votes table.
Scrapes new votes from congress repo using the congress project tool.
Tracks latest house/senate votes and scrapes incrementally.
"""
import os
import sys
import json
import subprocess
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import create_engine
from datetime import datetime
from pathlib import Path
import re

load_dotenv()
DB_URL = os.getenv('DB_URL')

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
BASE_DIR = PROJECT_DIR.parent  # Politicians ETL PostgreSQL Project
CONGRESS_REPO_DIR = BASE_DIR / "congress"
CONGRESS_DATA_DIR = CONGRESS_REPO_DIR / "congress" / "data"
CONGRESS_VENV_PYTHON = CONGRESS_REPO_DIR / "venv_congress" / "Scripts" / "python.exe"

# Current congress
CURRENT_CONGRESS = 119

try:
    engine = create_engine(DB_URL)
    print("Database connection successful.\n")
except Exception as e:
    print(f"Database connection failed: {e}")
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


def get_current_year():
    """Get the current year."""
    return datetime.now().year


def get_latest_vote_numbers(congress, year):
    """
    Scan the votes directory for the latest house and senate vote numbers.
    Returns: (latest_house_num, latest_senate_num)
    """
    votes_year_dir = CONGRESS_DATA_DIR / str(congress) / "votes" / str(year)
    
    if not votes_year_dir.exists():
        print(f"  Year directory doesn't exist: {votes_year_dir}")
        return None, None
    
    house_votes = []
    senate_votes = []
    
    # Scan for h### and s### folders
    for item in votes_year_dir.iterdir():
        if item.is_dir():
            match = re.match(r'^([hs])(\d+)$', item.name)
            if match:
                chamber = match.group(1)
                number = int(match.group(2))
                
                if chamber == 'h':
                    house_votes.append(number)
                elif chamber == 's':
                    senate_votes.append(number)
    
    latest_house = max(house_votes) if house_votes else 0
    latest_senate = max(senate_votes) if senate_votes else 0
    
    print(f"  Latest House vote: h{latest_house}")
    print(f"  Latest Senate vote: s{latest_senate}")
    
    return latest_house, latest_senate


def scrape_vote(congress, chamber, vote_num, year):
    """
    Run the congress project tool to scrape a specific vote.
    Returns True if successful, False if vote doesn't exist.
    """
    vote_id = f"{chamber}{vote_num}-{congress}.{year}"
    
    print(f"    Attempting to scrape: {vote_id}...", end=" ")
    
    # Build command to run in congress/congress directory with venv_congress
    cmd = [
        str(CONGRESS_VENV_PYTHON),
        "run.py",
        "votes",
        f"--vote_id={vote_id}"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(CONGRESS_DATA_DIR.parent),  # congress/congress directory
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Check if the vote folder was created
            vote_dir = CONGRESS_DATA_DIR / str(congress) / "votes" / str(year) / f"{chamber}{vote_num}"
            if vote_dir.exists():
                print("SUCCESS")
                return True
            else:
                print("FAILED (no data)")
                return False
        else:
            print("FAILED")
            return False
            
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def get_politician_map():
    """Create a mapping of congress_id (bioguideId) to politician_id."""
    politician_map = {}
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT politician_id, congress_id FROM politicians WHERE congress_id IS NOT NULL"
        ))
        for row in result:
            politician_map[row.congress_id] = row.politician_id
    return politician_map


def get_bill_map():
    """Create a mapping of bill_key to bill_id."""
    bill_map = {}
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT bill_id, official_bill_number, congress FROM bills"
        ))
        for row in result:
            composite_key = f"{row.official_bill_number.upper()}-{row.congress}"
            bill_map[composite_key] = row.bill_id
    return bill_map


def process_new_vote_file(vote_file_path, politician_map, bill_map):
    """
    Process a single vote data.json file and insert votes into database.
    Returns number of votes inserted.
    """
    try:
        with open(vote_file_path, 'r', encoding='utf-8') as f:
            vote_data = json.load(f)
        
        # Validate and get bill_id
        vote_category = vote_data.get('category')
        
        # Skip nominations or votes not tied to a bill
        if vote_category == 'nomination' or not vote_data.get('bill'):
            return 0
        
        bill_obj = vote_data.get('bill')
        bill_type = bill_obj.get('type', '').upper()
        bill_number = bill_obj.get('number')
        bill_congress = bill_obj.get('congress')
        
        bill_key = f"{bill_type}{bill_number}-{bill_congress}"
        bill_id = bill_map.get(bill_key)
        
        if not bill_id:
            return 0  # Skip if bill not in our DB
        
        # Prepare votes
        vote_date = vote_data.get('date')
        votes_to_insert = []
        
        for vote_position, voters in vote_data.get('votes', {}).items():
            for voter in voters:
                # Skip non-dict entries (like "VP")
                if not isinstance(voter, dict):
                    continue
                
                bioguide_id = voter.get('id')
                politician_db_id = politician_map.get(bioguide_id)
                
                if politician_db_id:
                    votes_to_insert.append({
                        'politician_id': politician_db_id,
                        'bill_id': bill_id,
                        'date': vote_date,
                        'vote_position': vote_position,
                        'vote_category': vote_category
                    })
        
        # Batch insert votes
        if votes_to_insert:
            votes_table = sqlalchemy.Table('votes', sqlalchemy.MetaData(), autoload_with=engine)
            with engine.connect() as conn:
                conn.execute(votes_table.insert(), votes_to_insert)
                conn.commit()
            
            return len(votes_to_insert)
        
        return 0
        
    except Exception as e:
        print(f"      Error processing vote file: {e}")
        return 0


def scrape_and_process_incremental_votes(congress, year, politician_map, bill_map):
    """
    Scrape new votes incrementally starting from the latest vote + 1.
    Returns total number of votes inserted.
    """
    total_votes_inserted = 0
    
    # Get latest vote numbers
    latest_house, latest_senate = get_latest_vote_numbers(congress, year)
    
    if latest_house is None and latest_senate is None:
        print(f"  No votes found for {year}. Starting from h1 and s1...")
        latest_house = 0
        latest_senate = 0
    
    # Try scraping next house votes
    print(f"\n  Scraping new House votes...")
    next_house = latest_house + 1
    consecutive_failures = 0
    
    while consecutive_failures < 3:  # Stop after 3 consecutive failures
        if scrape_vote(congress, 'h', next_house, year):
            # Process the vote file
            vote_file = CONGRESS_DATA_DIR / str(congress) / "votes" / str(year) / f"h{next_house}" / "data.json"
            if vote_file.exists():
                votes_inserted = process_new_vote_file(vote_file, politician_map, bill_map)
                total_votes_inserted += votes_inserted
                print(f"      Inserted {votes_inserted} votes")
            
            next_house += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            next_house += 1
    
    # Try scraping next senate votes
    print(f"\n  Scraping new Senate votes...")
    next_senate = latest_senate + 1
    consecutive_failures = 0
    
    while consecutive_failures < 3:  # Stop after 3 consecutive failures
        if scrape_vote(congress, 's', next_senate, year):
            # Process the vote file
            vote_file = CONGRESS_DATA_DIR / str(congress) / "votes" / str(year) / f"s{next_senate}" / "data.json"
            if vote_file.exists():
                votes_inserted = process_new_vote_file(vote_file, politician_map, bill_map)
                total_votes_inserted += votes_inserted
                print(f"      Inserted {votes_inserted} votes")
            
            next_senate += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            next_senate += 1
    
    return total_votes_inserted


def main():
    """Main function to update votes incrementally."""
    
    print("Starting incremental votes update...\n")
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
    
    # Get current year
    current_year = get_current_year()
    print(f"Current year: {current_year}")
    print(f"Current congress: {CURRENT_CONGRESS}\n")
    
    # Check if we need to handle year transition
    year_dir = CONGRESS_DATA_DIR / str(CURRENT_CONGRESS) / "votes" / str(current_year)
    if not year_dir.exists():
        print(f"Year {current_year} directory doesn't exist. Creating by scraping first votes...")
        year_dir.mkdir(parents=True, exist_ok=True)
        
        # Scrape h1 and s1 to initialize the year
        scrape_vote(CURRENT_CONGRESS, 'h', 1, current_year)
        scrape_vote(CURRENT_CONGRESS, 's', 1, current_year)
    
    # Load politician and bill maps
    print("Loading politician and bill maps...")
    politician_map = get_politician_map()
    bill_map = get_bill_map()
    print(f"  Loaded {len(politician_map)} politicians")
    print(f"  Loaded {len(bill_map)} bills\n")
    
    # Scrape and process new votes
    total_votes_inserted = scrape_and_process_incremental_votes(
        CURRENT_CONGRESS, 
        current_year, 
        politician_map, 
        bill_map
    )
    
    # Log the update
    log_update("votes", total_votes_inserted, "success", f"Scraped votes for {current_year}")
    
    print("\n" + "=" * 80)
    print("Votes update completed!")
    print(f"Total votes inserted: {total_votes_inserted}")
    print("=" * 80)


if __name__ == "__main__":
    main()
