import psycopg2
import os
from openai import OpenAI
from pinecone import Pinecone
from tqdm import tqdm  # Progress bar
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "bills-index")
DB_NAME = os.getenv("DB_NAME", "politicians_project")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD")       

# --- CONNECT ---
print("🔌 Connecting to services...")

# Connect to Local Postgres
try:
    conn = psycopg2.connect(
        dbname=DB_NAME, 
        user=DB_USER, 
        password=DB_PASS
    )
    cur = conn.cursor()
    print("✅ Connected to PostgreSQL")
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    exit()

# Connect to APIs
try:
    client = OpenAI(api_key=OPENAI_KEY)
    pc = Pinecone(api_key=PINECONE_KEY)
    index = pc.Index(INDEX_NAME)
    print("✅ Connected to OpenAI & Pinecone")
except Exception as e:
    print(f"❌ API connection failed: {e}")
    exit()

# --- FETCH DATA ---
print("📥 Fetching bills from local database...")
# We only fetch bills that actually HAVE a summary to analyze
cur.execute("""
    SELECT bill_id, official_bill_number, title, summary 
    FROM bills 
    WHERE summary IS NOT NULL AND length(summary) > 10
""")
bills = cur.fetchall()
print(f"📄 Found {len(bills)} bills to embed.")

# --- BATCH UPLOAD ---
BATCH_SIZE = 100

print("🚀 Starting embedding with ADAPTIVE TRUNCATION...")

for i in tqdm(range(0, len(bills), BATCH_SIZE)):
    batch = bills[i:i + BATCH_SIZE]
    
    # We process bills ONE BY ONE in this mode to handle errors precisely
    # (It's slightly slower but much safer for maximizing content)
    for b in batch:
        bill_id = str(b[0])
        bill_number = b[1]
        title = b[2] if b[2] else "No Title"
        summary = b[3] if b[3] else "No Summary"
        
        full_text = f"{title} \nSummary: {summary}"
        
        # --- SMART RETRY LOGIC ---
        # We try 3 levels of truncation:
        # Level 1: Aggressive (32k chars - near the limit)
        # Level 2: Moderate (20k chars)
        # Level 3: Safe (10k chars)
        
        attempts = [32000, 20000, 10000]
        success = False

        for limit in attempts:
            try:
                # Truncate to current limit
                text_to_embed = full_text[:limit]
                if len(full_text) > limit:
                     text_to_embed += " [TRUNCATED]"

                # Attempt to Embed
                response = client.embeddings.create(
                    input=text_to_embed,
                    model="text-embedding-3-small"
                )
                
                # If successful, upload and break the retry loop
                embedding = response.data[0].embedding
                index.upsert(vectors=[{
                    "id": bill_id,
                    "values": embedding,
                    "metadata": {
                        "bill_number": str(bill_number),
                        "title": str(title)[:1000], 
                        "text_preview": str(summary)[:500] 
                    }
                }])
                success = True
                break # It worked! Move to next bill.

            except Exception as e:
                # If it's a "Context Length" error, we ignore and try the next smaller limit
                if "maximum context length" in str(e):
                    continue 
                else:
                    print(f"❌ Unknown error on Bill {bill_number}: {e}")
                    break
        
        if not success:
            print(f"⚠️ Skipped Bill {bill_number}: Too massive even for safe mode.")

print("\n✅ DONE! All bills processed with max possible context.")