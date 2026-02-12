# DynamoDB Migrations

This folder contains migrations for setting up and managing the DynamoDB table for agent profiles.

## Structure

- `001_create_table.py` - Creates the DynamoDB table
- `002_seed_defaults.py` - Seeds default profile and presets
- `run_migrations.py` - Migration runner script

## Usage

### Prerequisites

1. AWS CLI configured with credentials
2. Python dependencies installed: `uv add boto3`
3. Environment variables set (or AWS credentials configured)

### Run All Migrations

```bash
python migrations/run_migrations.py
```

### Run Specific Migration

```bash
python migrations/001_create_table.py
python migrations/002_seed_defaults.py
```

### Using AWS CLI

**From project root:**
```bash
# Create table
aws dynamodb create-table --cli-input-json file://migrations/table-definition.json --region us-east-1

# Seed defaults
python migrations/002_seed_defaults.py
```

**From migrations directory:**
```bash
cd migrations

# Create table (use PowerShell script for Windows)
.\create_table_aws_cli.ps1

# Or use Python migration
python 001_create_table.py

# Seed defaults
python 002_seed_defaults.py
```

## Environment Variables

Set these in `.env.local` or as environment variables:

```bash
AWS_REGION=us-east-1
DYNAMODB_TABLE_NAME=logicall_agent_config
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
```

Or use AWS IAM roles (recommended for production).

