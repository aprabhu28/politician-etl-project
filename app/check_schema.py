"""Quick script to check actual BigQuery table schemas"""
from google.cloud import bigquery
import os
from dotenv import load_dotenv

load_dotenv()

client = bigquery.Client(project="starlit-verve-376800")

tables = [
    'politicians',
    'bills', 
    'donations',
    'donors',
    'votes',
    'committees',
    'committee_assignments',
    'bill_cosponsors'
]

for table_name in tables:
    print(f"\n{'='*60}")
    print(f"TABLE: {table_name}")
    print(f"{'='*60}")
    
    query = f"""
    SELECT column_name, data_type
    FROM `starlit-verve-376800.politician_analytics.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{table_name}'
    ORDER BY ordinal_position
    """
    
    results = client.query(query).result()
    
    for row in results:
        print(f"  {row.column_name:30} {row.data_type}")
