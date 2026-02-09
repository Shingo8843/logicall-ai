# Script to unlock Terraform state file
# Run this if state file is locked

Write-Host "Checking for locked Terraform state files..." -ForegroundColor Cyan

$stateFile = "terraform.tfstate"
$lockFile = ".terraform.tfstate.lock.info"

# Check if files exist
if (Test-Path $stateFile) {
    Write-Host "Found state file: $stateFile" -ForegroundColor Yellow
    
    # Try to remove lock file
    if (Test-Path $lockFile) {
        Write-Host "Removing lock file..." -ForegroundColor Yellow
        Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
        Write-Host "Lock file removed" -ForegroundColor Green
    }
    
    # Check if file is read-only
    $file = Get-Item $stateFile -Force
    if ($file.IsReadOnly) {
        Write-Host "State file is read-only, removing read-only attribute..." -ForegroundColor Yellow
        $file.IsReadOnly = $false
        Write-Host "Read-only attribute removed" -ForegroundColor Green
    }
}

Write-Host "`nIMPORTANT: Make sure:" -ForegroundColor Cyan
Write-Host "1. Close Cursor/VS Code if terraform.tfstate is open" -ForegroundColor White
Write-Host "2. Close any PowerShell windows running Terraform" -ForegroundColor White
Write-Host "3. Wait a few seconds, then try terraform import again" -ForegroundColor White


