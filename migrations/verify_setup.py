"""
Verify DynamoDB setup - check that table exists and has default data.
"""

import os
import sys
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(".env.local")

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TENANT_ID = os.getenv("TENANT_ID", "default")


def verify_table():
    """Verify table exists and is active."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    try:
        response = dynamodb.describe_table(TableName=TABLE_NAME)
        table = response["Table"]
        
        print(f"[OK] Table exists: {table['TableName']}")
        print(f"  Status: {table['TableStatus']}")
        print(f"  Item Count: {table.get('ItemCount', 0)}")
        print(f"  Billing Mode: {table.get('BillingModeSummary', {}).get('BillingMode', 'N/A')}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"[FAIL] Table {TABLE_NAME} does not exist")
            return False
        else:
            print(f"[FAIL] Error: {e}")
            return False


def verify_default_profile_pointer():
    """Verify default profile pointer exists."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    try:
        response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"TENANT#{TENANT_ID}"},
                "sk": {"S": "PROFILE_DEFAULT"},
            },
        )
        
        if "Item" in response:
            profile_id = response["Item"].get("profile_id", {}).get("S", "unknown")
            print(f"[OK] Default profile pointer exists: {profile_id}")
            return True
        else:
            print("[FAIL] Default profile pointer not found")
            return False
    except Exception as e:
        print(f"[FAIL] Error checking default profile pointer: {e}")
        return False


def verify_default_profile():
    """Verify default profile exists."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    try:
        response = dynamodb.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"TENANT#{TENANT_ID}"},
                "sk": {"S": "PROFILE#default#V#1"},
            },
        )
        
        if "Item" in response:
            profile_id = response["Item"].get("profile_id", {}).get("S", "unknown")
            version = response["Item"].get("version", {}).get("S", "unknown")
            print(f"[OK] Default profile exists: {profile_id} v{version}")
            return True
        else:
            print("[FAIL] Default profile not found")
            return False
    except Exception as e:
        print(f"[FAIL] Error checking default profile: {e}")
        return False


def verify_presets():
    """Verify model presets exist."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    presets = [
        ("LLM", "ID#gpt-5.1#V#1"),
        ("STT", "ID#nova-3#V#1"),
        ("TTS", "ID#sonic-3#V#1"),
        ("REALTIME", "ID#amazon.nova-2-sonic-v1:0#V#1"),
    ]
    
    all_found = True
    for preset_type, sk in presets:
        try:
            response = dynamodb.get_item(
                TableName=TABLE_NAME,
                Key={
                    "pk": {"S": f"PRESET#{preset_type}"},
                    "sk": {"S": sk},
                },
            )
            
            if "Item" in response:
                preset_id = response["Item"].get("preset_id", {}).get("S", "unknown")
                print(f"[OK] {preset_type} preset exists: {preset_id}")
            else:
                print(f"[FAIL] {preset_type} preset not found")
                all_found = False
        except Exception as e:
            print(f"[FAIL] Error checking {preset_type} preset: {e}")
            all_found = False
    
    return all_found


def main():
    print("=" * 60)
    print("DynamoDB Setup Verification")
    print("=" * 60)
    print()
    
    results = []
    results.append(("Table", verify_table()))
    print()
    results.append(("Default Profile Pointer", verify_default_profile_pointer()))
    print()
    results.append(("Default Profile", verify_default_profile()))
    print()
    results.append(("Model Presets", verify_presets()))
    print()
    
    print("=" * 60)
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("[SUCCESS] All verifications passed!")
    else:
        print("[FAILED] Some verifications failed. Run migrations to fix.")
        print()
        print("Run: python migrations/run_migrations.py")
    
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

