# テスト実行スクリプト (PowerShell)
Write-Host "Running tests..." -ForegroundColor Cyan

python -m pytest tests/test_api.py -v

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Tests failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "All tests passed!" -ForegroundColor Green
