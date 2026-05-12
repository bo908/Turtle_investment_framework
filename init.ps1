# init.ps1 - Turtle Investment Framework environment setup (Windows)
# Run at the start of each session:  .\init.ps1
# Force reinstall:                   .\init.ps1 --force-install

$ErrorActionPreference = "Stop"

$PROJECT_ROOT = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $PROJECT_ROOT

Write-Host "=== Turtle Investment Framework - Environment Setup ===" -ForegroundColor Cyan
Write-Host "Project root: $PROJECT_ROOT"
Write-Host ""

# ── 1. Python environment (venv) ──────────────────────────────────────────────
$VENV_DIR    = Join-Path $PROJECT_ROOT ".venv"
$PYTHON_VENV = Join-Path $VENV_DIR "Scripts\python.exe"
$PIP_VENV    = Join-Path $VENV_DIR "Scripts\pip.exe"

Write-Host "[1/5] Setting up Python environment..."

# Find Python >= 3.10
$PYTHON_SYS = $null
foreach ($candidate in @("python", "python3", "py")) {
    $bin = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($bin) {
        $major = & $bin.Source -c "import sys; print(sys.version_info.major)" 2>$null
        $minor = & $bin.Source -c "import sys; print(sys.version_info.minor)" 2>$null
        if ([int]$major -ge 3 -and [int]$minor -ge 10) {
            $PYTHON_SYS = $bin.Source
            break
        }
    }
}

if (-not $PYTHON_SYS) {
    Write-Host "  ERROR: No Python >= 3.10 found on this system" -ForegroundColor Red
    Write-Host "  Download from: https://www.python.org/downloads/"
    Write-Host "  Or via winget:  winget install Python.Python.3.12"
    exit 1
}

$pyVer = & $PYTHON_SYS -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"

$VENV_JUST_CREATED = $false
if (-not (Test-Path $PYTHON_VENV)) {
    Write-Host "  Creating venv at $VENV_DIR (Python $pyVer) ..."
    & $PYTHON_SYS -m venv $VENV_DIR
    $VENV_JUST_CREATED = $true
} else {
    Write-Host "  venv already exists."
}

$actualVer = & $PYTHON_VENV --version
Write-Host "  Python: $actualVer"
Write-Host "  Using:  $PYTHON_VENV"

# ── 2. Install dependencies ───────────────────────────────────────────────────
Write-Host "[2/5] Installing Python dependencies..."

$forceInstall = $args -contains "--force-install"
if ($VENV_JUST_CREATED -or $forceInstall) {
    & $PIP_VENV install -q -r (Join-Path $PROJECT_ROOT "requirements.txt")
    Write-Host "  Dependencies installed." -ForegroundColor Green
} else {
    Write-Host "  Skipped (venv exists). Use '.\init.ps1 --force-install' to reinstall."
}

# ── 3. Verify Tushare token ───────────────────────────────────────────────────
Write-Host "[3/5] Checking Tushare token..."

$envFile = Join-Path $PROJECT_ROOT ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "^([^=]+)=(.*)$") {
            $key   = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            if (-not [System.Environment]::GetEnvironmentVariable($key)) {
                [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
    Write-Host "  Loaded .env file"
}

if (-not $env:TUSHARE_TOKEN) {
    Write-Host "  WARNING: TUSHARE_TOKEN not set" -ForegroundColor Yellow
    Write-Host "  Option 1: copy .env.sample .env  (then edit .env)"
    Write-Host "  Option 2: `$env:TUSHARE_TOKEN = 'your_token_here'"
    Write-Host "  Tests requiring live API will be skipped"
} else {
    $tokenLen = $env:TUSHARE_TOKEN.Length
    Write-Host "  TUSHARE_TOKEN: set ($tokenLen chars)" -ForegroundColor Green
}

# ── 4. Create output directory ────────────────────────────────────────────────
Write-Host "[4/5] Ensuring output directory..."
New-Item -ItemType Directory -Path (Join-Path $PROJECT_ROOT "output") -Force | Out-Null
Write-Host "  output/ ready"

# ── 5. Run basic tests ────────────────────────────────────────────────────────
Write-Host "[5/5] Running verification tests..."
& $PYTHON_VENV -m pytest (Join-Path $PROJECT_ROOT "tests") -x -q --tb=short 2>&1 | Select-Object -Last 5

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host "Jupyter kernel path: $PYTHON_VENV"
Write-Host "To activate venv in this shell: .venv\Scripts\Activate.ps1"
