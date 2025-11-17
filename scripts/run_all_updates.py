"""
Master script to run all incremental updates in sequence.
This should be run daily (or as needed) to keep data fresh.
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Get the scripts directory
SCRIPTS_DIR = Path(__file__).parent

# Define update scripts in order of execution
UPDATE_SCRIPTS = [
    ("update_bills.py", "Bills", "Updates recently introduced bills"),
    ("update_bill_sponsors.py", "Bill Sponsors", "Updates sponsor_id for new bills"),
    #("update_cosponsors.py", "Bill Cosponsors", "Updates cosponsors for recent bills"),
    ("update_votes.py", "Votes", "Processes new vote data files"),
    # ("update_donations.py", "Donations", "Downloads and processes latest FEC data"),  # Skipped - run manually when needed
]


def run_script(script_name, description):
    """Run a single update script."""
    print("\n" + "=" * 80)
    print(f"  Running: {description}")
    print("=" * 80)
    
    script_path = SCRIPTS_DIR / script_name
    
    if not script_path.exists():
        print(f"  Script not found: {script_path}")
        return False
    
    try:
        # Run the script
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=False,
            text=True,
            check=True
        )
        
        print(f"\n  {description} completed successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n  {description} failed with error code {e.returncode}")
        return False
    except Exception as e:
        print(f"\n  Error running {description}: {e}")
        return False


def main():
    """Run all update scripts in sequence."""
    
    start_time = datetime.now()
    
    print("\n" + "=" * 80)
    print("  STARTING INCREMENTAL DATA UPDATE")
    print("=" * 80)
    print(f"  Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total scripts to run: {len(UPDATE_SCRIPTS)}\n")
    
    results = []
    
    for script_name, title, description in UPDATE_SCRIPTS:
        success = run_script(script_name, title)
        results.append((title, success))
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    # Summary
    print("\n\n" + "=" * 80)
    print("UPDATE SUMMARY")
    print("=" * 80)
    
    for title, success in results:
        status = "SUCCESS" if success else "FAILED"
        print(f"  {status}: {title}")
    
    print("\n" + "=" * 80)
    print(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total duration: {duration}")
    
    success_count = sum(1 for _, success in results if success)
    print(f"Success rate: {success_count}/{len(results)}")
    print("=" * 80 + "\n")
    
    # Exit with error code if any script failed
    if success_count < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
