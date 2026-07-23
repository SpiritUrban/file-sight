# Prepare FileSight for NVIDIA CUDA (GeForce GTX/RTX) on Windows.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/setup_nvidia.ps1
#
# Installs/uses .venv, removes conflicting onnxruntime wheels, installs
# onnxruntime-gpu, and prints provider / auto-backend status.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Write-Step "Repo: $Root"

# Prefer Python 3.12, then 3.11, then whatever `py` / `python` is.
$python = $null
foreach ($ver in @("-3.12", "-3.11", "-3")) {
    try {
        $candidate = & py $ver -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate) {
            $python = $candidate.Trim()
            break
        }
    } catch { }
}
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "No Python found. Install Python 3.11 or 3.12 (64-bit) and re-run."
}
Write-Host "Python: $python"
& $python -c "import sys; print(sys.version)"

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating .venv"
    & $python -m venv (Join-Path $Root ".venv")
}
$venvPython = (Resolve-Path $venvPython).Path
Write-Host "Venv: $venvPython"

Write-Step "Upgrading pip"
& $venvPython -m pip install -U pip setuptools wheel

Write-Step "Removing conflicting onnxruntime packages (only one may be installed)"
& $venvPython -m pip uninstall -y onnxruntime onnxruntime-directml onnxruntime-gpu 2>$null

Write-Step "Installing FileSight + CUDA extra"
& $venvPython -m pip install -e ".[dev,cuda]"

Write-Step "Checking NVIDIA driver (best effort)"
try {
    & nvidia-smi 2>$null | Select-Object -First 12
} catch {
    Write-Host "nvidia-smi not found — install/update the GeForce driver." -ForegroundColor Yellow
}

Write-Step "Inference probe"
& $venvPython (Join-Path $Root "scripts\check_inference.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Probe reported a problem (see above)." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

$modelRepo = Join-Path $Root "models\blip-onnx\vision_encoder.onnx"
if (-not (Test-Path $modelRepo)) {
    Write-Host ""
    Write-Host "Model pack not found at models\blip-onnx." -ForegroundColor Yellow
    Write-Host "Copy it from the AMD machine or set FILESIGHT_ONNX_MODEL_DIR."
} else {
    Write-Host "Model pack: models\blip-onnx OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done. Next:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m filesight scan <folder> --backend onnx-cuda --no-allow-fallback --max-files 1 --overwrite-report"
Write-Host "See docs/nvidia-setup.md for details."
