"""
Migration 004: Add sip_outbound_trunk_id to all existing profiles.

Sets sip_outbound_trunk_id = ST_wCPfwPCXu7HV (or SIP_OUTBOUND_TRUNK_ID env)
on the default profile and all logistics profiles so outbound calls work.
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env.local")
load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TENANT_ID = os.getenv("TENANT_ID", "default")
SIP_TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID")

# All profile keys (tenant default): default + logistics
PROFILE_KEYS = [
    ("default", "1"),
    ("carrier-checkup", "1"),
    ("delivery-reschedule", "1"),
    ("delivery-reminder", "1"),
    ("post-delivery", "1"),
    ("inbound-triage", "1"),
    ("claims-intake", "1"),
    ("carrier-onboarding", "1"),
]


def run_migration() -> bool:
    import boto3
    from botocore.exceptions import ClientError

    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)

    try:
        dynamodb.describe_table(TableName=TABLE_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"ERROR: Table {TABLE_NAME} not found.")
            return False
        raise

    print(f"Adding sip_outbound_trunk_id = {SIP_TRUNK_ID} to all profiles (tenant={TENANT_ID})")
    print("=" * 60)

    success = True
    for profile_id, version in PROFILE_KEYS:
        pk = f"TENANT#{TENANT_ID}"
        sk = f"PROFILE#{profile_id}#V#{version}"
        try:
            dynamodb.update_item(
                TableName=TABLE_NAME,
                Key={
                    "pk": {"S": pk},
                    "sk": {"S": sk},
                },
                UpdateExpression="SET sip_outbound_trunk_id = :tid",
                ExpressionAttributeValues={":tid": {"S": SIP_TRUNK_ID}},
            )
            print(f"  [OK] {profile_id} v{version}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationException":
                # Item might not exist
                print(f"  [SKIP] {profile_id} v{version} (not found or no update)")
            else:
                print(f"  [FAIL] {profile_id} v{version}: {e}")
                success = False

    return success


if __name__ == "__main__":
    print("=" * 60)
    print("Migration 004: Add SIP trunk to all profiles")
    print("=" * 60)
    success = run_migration()
    if success:
        print("\n[SUCCESS] Migration 004 completed.")
    else:
        print("\n[FAILED] Migration 004 had errors.")
        sys.exit(1)
