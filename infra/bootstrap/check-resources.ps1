# Script to check if AWS resources were created
# Run this after canceling terraform apply

Write-Host "Checking AWS resources..." -ForegroundColor Cyan

# Check S3 bucket
Write-Host "`nChecking S3 bucket: logicall-ai-terraform-state" -ForegroundColor Yellow
aws s3api head-bucket --bucket logicall-ai-terraform-state 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ S3 bucket exists" -ForegroundColor Green
} else {
    Write-Host "✗ S3 bucket does not exist" -ForegroundColor Red
}

# Check DynamoDB table
Write-Host "`nChecking DynamoDB table: Shingo8843" -ForegroundColor Yellow
aws dynamodb describe-table --table-name Shingo8843 --region us-west-2 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ DynamoDB table exists" -ForegroundColor Green
} else {
    Write-Host "✗ DynamoDB table does not exist" -ForegroundColor Red
}

# Check IAM role
Write-Host "`nChecking IAM role: GitHubActionsRole" -ForegroundColor Yellow
aws iam get-role --role-name GitHubActionsRole --region us-west-2 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ IAM role exists" -ForegroundColor Green
} else {
    Write-Host "✗ IAM role does not exist" -ForegroundColor Red
}

Write-Host "`nDone!" -ForegroundColor Cyan

