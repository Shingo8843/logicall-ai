"""
Migration 001: Create DynamoDB table for agent configuration.

This migration creates the logicall_agent_config table with:
- Primary key: pk (String), sk (String)
- Global Secondary Indexes for efficient queries
- Billing mode: On-demand (pay per request)
"""

import os
import sys
import json
import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(".env.local")

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def create_table():
    """Create the DynamoDB table for agent configuration."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    table_definition = {
        "TableName": TABLE_NAME,
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "entity_type", "AttributeType": "S"},
            {"AttributeName": "profile_id", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",  # On-demand pricing
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "entity-type-index",
                "KeySchema": [
                    {"AttributeName": "entity_type", "KeyType": "HASH"},
                    {"AttributeName": "pk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "profile-id-index",
                "KeySchema": [
                    {"AttributeName": "profile_id", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "Tags": [
            {"Key": "Project", "Value": "Logicall-AI"},
            {"Key": "Component", "Value": "Agent-Config"},
        ],
    }
    
    try:
        print(f"Creating table {TABLE_NAME} in region {AWS_REGION}...")
        response = dynamodb.create_table(**table_definition)
        
        print(f"[OK] Table creation initiated: {response['TableDescription']['TableName']}")
        print(f"  Table Status: {response['TableDescription']['TableStatus']}")
        print(f"  Table ARN: {response['TableDescription']['TableArn']}")
        
        # Wait for table to be active
        print("\nWaiting for table to become active...")
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)
        
        print(f"[OK] Table {TABLE_NAME} is now active!")
        return True
        
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceInUseException":
            print(f"[SKIP] Table {TABLE_NAME} already exists. Skipping creation.")
            return True
        else:
            print(f"ERROR: Error creating table: {e}")
            return False
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        return False


def verify_table():
    """Verify the table was created correctly."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    try:
        response = dynamodb.describe_table(TableName=TABLE_NAME)
        table = response["Table"]
        
        print(f"\n[OK] Table verification:")
        print(f"  Name: {table['TableName']}")
        print(f"  Status: {table['TableStatus']}")
        print(f"  Billing Mode: {table.get('BillingModeSummary', {}).get('BillingMode', 'N/A')}")
        print(f"  Item Count: {table.get('ItemCount', 0)}")
        print(f"  GSIs: {len(table.get('GlobalSecondaryIndexes', []))}")
        
        return True
    except ClientError as e:
        print(f"ERROR: Error verifying table: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Migration 001: Create DynamoDB Table")
    print("=" * 60)
    
    success = create_table()
    
    if success:
        verify_table()
        print("\n" + "=" * 60)
        print("[SUCCESS] Migration 001 completed successfully!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Migration 001 failed!")
        print("=" * 60)
        sys.exit(1)

