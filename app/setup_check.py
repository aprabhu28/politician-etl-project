"""
Setup script for Politician Agenda Analyzer
Validates environment and connections before running the app
"""

import sys
import os
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.9+"""
    print("🐍 Checking Python version...")
    if sys.version_info < (3, 9):
        print("❌ Python 3.9+ required. Current:", sys.version)
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    return True

def check_env_file():
    """Check if .env file exists"""
    print("\n📝 Checking environment configuration...")
    env_path = Path(__file__).parent / ".env"
    
    if not env_path.exists():
        print("❌ .env file not found!")
        print("   Create it from template: cp .env.template .env")
        return False
    
    # Check for required keys
    with open(env_path) as f:
        env_content = f.read()
    
    required_keys = ["PINECONE_API_KEY", "OPENAI_API_KEY"]
    missing_keys = []
    
    for key in required_keys:
        if f"{key}=your_" in env_content or key not in env_content:
            missing_keys.append(key)
    
    if missing_keys:
        print(f"❌ Missing or unconfigured API keys: {', '.join(missing_keys)}")
        print("   Edit .env and add your actual API keys")
        return False
    
    print("✅ Environment file configured")
    return True

def check_dependencies():
    """Check if required packages are installed"""
    print("\n📦 Checking dependencies...")
    required_packages = [
        "streamlit",
        "google.cloud.bigquery",
        "pinecone",
        "openai",
        "pandas",
        "dotenv"
    ]
    
    missing = []
    for package in required_packages:
        package_name = package.replace(".", "_") if "." in package else package
        try:
            if package == "dotenv":
                __import__("dotenv")
            else:
                __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"❌ Missing packages: {', '.join(missing)}")
        print("   Install with: pip install -r requirements.txt")
        return False
    
    print("✅ All dependencies installed")
    return True

def check_gcloud_auth():
    """Check if gcloud is authenticated"""
    print("\n☁️  Checking Google Cloud authentication...")
    
    # Check if gcloud is installed
    import subprocess
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=True  # Required on Windows to find gcloud in PATH
        )
        
        if result.returncode == 0:
            print("✅ Google Cloud authenticated")
            return True
        else:
            print("⚠️  Not authenticated with Google Cloud")
            print("   Run: gcloud auth application-default login")
            return False
    
    except FileNotFoundError:
        print("⚠️  gcloud CLI not found")
        print("   Install from: https://cloud.google.com/sdk/docs/install")
        return False
    except Exception as e:
        print(f"⚠️  Could not verify gcloud auth: {e}")
        return False

def test_connections():
    """Test connections to all services"""
    print("\n🔌 Testing service connections...")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    # Test Pinecone
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        index = pc.Index("bills-index")
        stats = index.describe_index_stats()
        print(f"✅ Pinecone connected ({stats.total_vector_count:,} vectors)")
    except Exception as e:
        print(f"❌ Pinecone connection failed: {e}")
        return False
    
    # Test OpenAI
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # Quick test
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input="test"
        )
        print("✅ OpenAI connected")
    except Exception as e:
        print(f"❌ OpenAI connection failed: {e}")
        return False
    
    # Test BigQuery
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project="starlit-verve-376800")
        # Quick test query
        query = "SELECT COUNT(*) as count FROM `starlit-verve-376800.politician_analytics.bills` LIMIT 1"
        result = client.query(query).result()
        for row in result:
            print(f"✅ BigQuery connected ({row.count:,} bills)")
    except Exception as e:
        print(f"❌ BigQuery connection failed: {e}")
        return False
    
    return True

def main():
    """Run all checks"""
    print("=" * 60)
    print("🏛️  POLITICIAN AGENDA ANALYZER - SETUP CHECK")
    print("=" * 60)
    
    checks = [
        check_python_version(),
        check_dependencies(),
        check_env_file(),
        check_gcloud_auth(),
    ]
    
    if all(checks):
        # If basic checks pass, test connections
        if test_connections():
            print("\n" + "=" * 60)
            print("✅ ALL CHECKS PASSED!")
            print("=" * 60)
            print("\n🚀 Ready to launch! Run:")
            print("   streamlit run app.py")
            return 0
    
    print("\n" + "=" * 60)
    print("❌ SETUP INCOMPLETE")
    print("=" * 60)
    print("\nPlease fix the issues above before running the app.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
