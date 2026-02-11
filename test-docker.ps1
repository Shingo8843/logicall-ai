# Docker Test Script for Backend
# This script tests building and running the Docker image locally

Write-Host "=== Testing Docker Setup ===" -ForegroundColor Cyan

# Check if Docker is available
Write-Host "`n1. Checking Docker installation..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version
    Write-Host "✓ Docker is installed: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Docker is not installed or not in PATH" -ForegroundColor Red
    Write-Host "  Please install Docker Desktop for Windows from: https://www.docker.com/products/docker-desktop" -ForegroundColor Yellow
    exit 1
}

# Check if Docker daemon is running
Write-Host "`n2. Checking Docker daemon..." -ForegroundColor Yellow
try {
    docker info | Out-Null
    Write-Host "✓ Docker daemon is running" -ForegroundColor Green
} catch {
    Write-Host "✗ Docker daemon is not running" -ForegroundColor Red
    Write-Host "  Please start Docker Desktop" -ForegroundColor Yellow
    exit 1
}

# Build the Docker image
Write-Host "`n3. Building Docker image..." -ForegroundColor Yellow
docker build -t backend:test .
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Docker build failed" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Docker image built successfully" -ForegroundColor Green

# Run the container
Write-Host "`n4. Starting container..." -ForegroundColor Yellow
$containerId = docker run -d -p 8000:8000 --name backend-test backend:test
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to start container" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Container started: $containerId" -ForegroundColor Green

# Wait for the app to start
Write-Host "`n5. Waiting for application to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Test the health endpoint
Write-Host "`n6. Testing health endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
    Write-Host "✓ Health check passed: $($response.Content)" -ForegroundColor Green
} catch {
    Write-Host "✗ Health check failed: $_" -ForegroundColor Red
    docker logs backend-test
    docker stop backend-test
    docker rm backend-test
    exit 1
}

# Show container logs
Write-Host "`n7. Container logs:" -ForegroundColor Yellow
docker logs backend-test

# Cleanup
Write-Host "`n8. Cleaning up..." -ForegroundColor Yellow
docker stop backend-test
docker rm backend-test
Write-Host "✓ Container stopped and removed" -ForegroundColor Green

Write-Host "`n=== All tests passed! ===" -ForegroundColor Green
Write-Host "Your Docker setup is working correctly." -ForegroundColor Green

