# Quick Start Script for Politician Agenda Analyzer
# Run this in PowerShell from the app/ directory

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 59) -ForegroundColor Cyan
Write-Host "🏛️  POLITICIAN AGENDA ANALYZER - QUICK START" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 59) -ForegroundColor Cyan
Write-Host ""

# Step 1: Check if .env exists
Write-Host "📝 Step 1: Checking environment configuration..." -ForegroundColor Yellow
if (-Not (Test-Path ".env")) {
    Write-Host "   Creating .env from template..." -ForegroundColor Gray
    Copy-Item ".env.template" ".env"
    Write-Host "   ⚠️  IMPORTANT: Edit .env and add your API keys!" -ForegroundColor Red
    Write-Host "      - PINECONE_API_KEY" -ForegroundColor Gray
    Write-Host "      - OPENAI_API_KEY" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   Press Enter after you've updated .env..." -ForegroundColor Yellow
    Read-Host
} else {
    Write-Host "   ✅ .env file found" -ForegroundColor Green
}

# Step 2: Create virtual environment
Write-Host ""
Write-Host "🐍 Step 2: Setting up Python environment..." -ForegroundColor Yellow
if (-Not (Test-Path "venv")) {
    Write-Host "   Creating virtual environment..." -ForegroundColor Gray
    python -m venv venv
    Write-Host "   ✅ Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "   ✅ Virtual environment exists" -ForegroundColor Green
}

# Step 3: Activate virtual environment
Write-Host ""
Write-Host "🔧 Step 3: Activating virtual environment..." -ForegroundColor Yellow
& "venv\Scripts\Activate.ps1"
Write-Host "   ✅ Virtual environment activated" -ForegroundColor Green

# Step 4: Install dependencies
Write-Host ""
Write-Host "📦 Step 4: Installing dependencies..." -ForegroundColor Yellow
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
Write-Host "   ✅ Dependencies installed" -ForegroundColor Green

# Step 5: Check Google Cloud authentication
Write-Host ""
Write-Host "☁️  Step 5: Checking Google Cloud authentication..." -ForegroundColor Yellow
$gclouAuth = gcloud auth application-default print-access-token 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Google Cloud authenticated" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  Not authenticated. Running authentication..." -ForegroundColor Red
    Write-Host "      Follow the browser prompts to authenticate..." -ForegroundColor Gray
    gcloud auth application-default login
}

# Step 6: Run setup check
Write-Host ""
Write-Host "🔍 Step 6: Running connection tests..." -ForegroundColor Yellow
python setup_check.py

if ($LASTEXITCODE -eq 0) {
    # Step 7: Launch app
    Write-Host ""
    Write-Host "=" -NoNewline -ForegroundColor Cyan
    Write-Host ("=" * 59) -ForegroundColor Cyan
    Write-Host "🚀 LAUNCHING APPLICATION!" -ForegroundColor Green
    Write-Host "=" -NoNewline -ForegroundColor Cyan
    Write-Host ("=" * 59) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "The app will open in your browser at http://localhost:8501" -ForegroundColor Gray
    Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
    Write-Host ""
    
    streamlit run app.py
} else {
    Write-Host ""
    Write-Host "❌ Setup incomplete. Please fix the issues above." -ForegroundColor Red
    Write-Host ""
}
