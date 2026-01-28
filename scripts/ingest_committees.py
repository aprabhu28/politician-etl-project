"""
Ingestion script for committees and committee assignments.
Fetches data from @unitedstates/congress-legislators GitHub repository.
Supports both top-level committees and subcommittees, with flattening logic.
"""
import os
import requests
import yaml
import sqlalchemy
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime

load_dotenv()
DB_URL = os.getenv('DB_URL')

# GitHub raw URLs for committee data
COMMITTEES_CURRENT_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/master/committees-current.yaml"
MEMBERSHIPS_CURRENT_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/master/committee-membership-current.yaml"

# Note: Historical committee membership data is not available in the congress-legislators repository
# Only committees-historical.yaml exists (committee definitions), not committee-membership-historical.yaml
# Therefore, we can only ingest current (119th Congress) membership data

# Congress numbers to process
CONGRESSES = [119]  # Only 119 available - no historical membership data exists

try:
    engine = create_engine(DB_URL)
    print("Database connection successful.\n")
except Exception as e:
    print(f"Database connection failed: {e}")
    exit()


def fetch_yaml_data(url):
    """Fetch and parse YAML data from a URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return yaml.safe_load(response.text)
    except Exception as e:
        print(f"Error fetching data from {url}: {e}")
        return None


def flatten_committees(committees_data):
    """
    Flatten committees data to handle subcommittees.
    Returns list of committee dicts, including subcommittees as separate entries.
    """
    flattened = []
    
    for committee in committees_data:
        # Extract main committee info
        committee_id = committee.get('thomas_id')
        if not committee_id:
            continue
        
        main_committee = {
            'committee_id': committee_id,
            'name': committee.get('name'),
            'chamber': committee.get('type'),  # 'type' field contains 'house', 'senate', 'joint'
            'type': committee.get('chamber'),  # 'chamber' field contains 'standing', 'select', etc.
            'url': committee.get('url'),
            'thomas_id': committee_id,
            'parent_committee_id': None
        }
        
        flattened.append(main_committee)
        
        # Process subcommittees if they exist
        subcommittees = committee.get('subcommittees', [])
        for subcommittee in subcommittees:
            sub_thomas_id = subcommittee.get('thomas_id')
            if not sub_thomas_id:
                continue
            
            # Create full subcommittee ID: parent_id + sub_thomas_id
            sub_committee_id = f"{committee_id}{sub_thomas_id}"
            
            sub_committee = {
                'committee_id': sub_committee_id,
                'name': subcommittee.get('name'),
                'chamber': committee.get('type'),  # Inherit from parent (YAML 'type' = chamber)
                'type': committee.get('chamber'),  # Inherit from parent (YAML 'chamber' = committee type)
                'url': subcommittee.get('url'),
                'thomas_id': sub_thomas_id,
                'parent_committee_id': committee_id
            }
            
            flattened.append(sub_committee)
    
    return flattened


def get_politician_id_by_bioguide(bioguide_id):
    """Look up politician_id from bioguide ID."""
    with engine.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT politician_id FROM politicians WHERE congress_id = :bioguide"),
            {"bioguide": bioguide_id}
        )
        row = result.fetchone()
        return row.politician_id if row else None


def ingest_committees(committees_data):
    """Insert or update committees in the database."""
    flattened = flatten_committees(committees_data)
    
    print(f"Processing {len(flattened)} committees (including subcommittees)...")
    
    committees_table = sqlalchemy.Table('committees', sqlalchemy.MetaData(), autoload_with=engine)
    
    inserted = 0
    updated = 0
    
    with engine.connect() as conn:
        for committee in flattened:
            try:
                stmt = pg_insert(committees_table).values(committee)
                
                # On conflict, update all fields
                update_stmt = stmt.on_conflict_do_update(
                    index_elements=['committee_id'],
                    set_={
                        'name': stmt.excluded.name,
                        'chamber': stmt.excluded.chamber,
                        'type': stmt.excluded.type,
                        'url': stmt.excluded.url,
                        'thomas_id': stmt.excluded.thomas_id,
                        'parent_committee_id': stmt.excluded.parent_committee_id
                    }
                )
                
                result = conn.execute(update_stmt)
                conn.commit()
                
                if result.rowcount > 0:
                    inserted += 1
                    if committee['parent_committee_id']:
                        print(f"  ↳ Subcommittee: {committee['committee_id']} - {committee['name']}")
                    else:
                        print(f"  • Committee: {committee['committee_id']} - {committee['name']}")
                
            except Exception as e:
                print(f"  Error inserting committee {committee.get('committee_id')}: {e}")
    
    print(f"\nCommittees ingestion complete: {inserted} committees processed\n")
    return inserted


def ingest_committee_assignments(memberships_data, congress):
    """Insert or update committee assignments in the database."""
    
    print(f"Processing committee assignments for Congress {congress}...")
    
    committee_assignments_table = sqlalchemy.Table('committee_assignments', sqlalchemy.MetaData(), autoload_with=engine)
    
    total_assignments = 0
    inserted = 0
    skipped_no_politician = 0
    
    with engine.connect() as conn:
        for committee_id, members in memberships_data.items():
            if not members:
                continue
            
            for member in members:
                total_assignments += 1
                
                bioguide_id = member.get('bioguide')
                if not bioguide_id:
                    continue
                
                # Look up politician_id
                politician_id = get_politician_id_by_bioguide(bioguide_id)
                if not politician_id:
                    skipped_no_politician += 1
                    print(f"  ⚠ Skipping {member.get('name')} (bioguide: {bioguide_id}) - not in politicians table")
                    continue
                
                # Prepare assignment data
                assignment = {
                    'politician_id': politician_id,
                    'committee_id': committee_id,
                    'rank': member.get('rank'),
                    'role': member.get('title', 'Member'),
                    'party': member.get('party'),  # 'majority' or 'minority'
                    'congress': congress
                }
                
                try:
                    stmt = pg_insert(committee_assignments_table).values(assignment)
                    
                    # On conflict, update rank/role/party (in case of changes)
                    update_stmt = stmt.on_conflict_do_update(
                        index_elements=['politician_id', 'committee_id', 'congress'],
                        set_={
                            'rank': stmt.excluded.rank,
                            'role': stmt.excluded.role,
                            'party': stmt.excluded.party
                        }
                    )
                    
                    result = conn.execute(update_stmt)
                    conn.commit()
                    
                    if result.rowcount > 0:
                        inserted += 1
                    
                except Exception as e:
                    print(f"  Error inserting assignment for {member.get('name')}: {e}")
    
    print(f"\nCommittee assignments complete for Congress {congress}:")
    print(f"  Total assignments processed: {total_assignments}")
    print(f"  Successfully inserted/updated: {inserted}")
    print(f"  Skipped (politician not found): {skipped_no_politician}\n")
    
    return inserted


def main():
    """Main ingestion function."""
    
    print("=" * 80)
    print("COMMITTEES AND ASSIGNMENTS INGESTION")
    print("=" * 80)
    print(f"Target Congress: 119 (current)\n")
    
    # Process current congress (119th)
    print("=" * 80)
    print("PROCESSING CONGRESS 119 (CURRENT)")
    print("=" * 80 + "\n")
    
    # Fetch current committees data
    print("Fetching current committees data from GitHub...")
    committees_current = fetch_yaml_data(COMMITTEES_CURRENT_URL)
    
    if not committees_current:
        print("Failed to fetch current committees data. Exiting.")
        return
    
    print(f"✓ Fetched {len(committees_current)} top-level committees\n")
    
    # Ingest current committees (including subcommittees)
    print("STEP 1: Ingesting Current Committees")
    print("-" * 80 + "\n")
    
    committees_count_119 = ingest_committees(committees_current)
    
    # Fetch current memberships data
    print("\nFetching current committee memberships data from GitHub...")
    memberships_current = fetch_yaml_data(MEMBERSHIPS_CURRENT_URL)
    
    if not memberships_current:
        print("Failed to fetch current memberships data.")
    else:
        print(f"✓ Fetched memberships for {len(memberships_current)} committees\n")
        
        # Ingest current committee assignments
        print("STEP 2: Ingesting Current Committee Assignments")
        print("-" * 80 + "\n")
        
        assignments_count_119 = ingest_committee_assignments(memberships_current, 119)
    
    # Summary
    print("\n" + "=" * 80)
    print("INGESTION COMPLETE")
    print("=" * 80)
    print(f"Committees processed: {committees_count_119}")
    print(f"119th Congress assignments: {assignments_count_119 if memberships_current else 0}")
    print("\nNote: Historical committee membership data (118th Congress) is not available")
    print("      in the congress-legislators repository. Only current assignments exist.")
    print("=" * 80)


if __name__ == "__main__":
    main()
