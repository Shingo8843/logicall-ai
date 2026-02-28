"""
List all agent profiles in DynamoDB (uses entity-type-index where entity_type = 'profile').
"""

import os
import sys
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def list_profiles():
    """Query DynamoDB for all items with entity_type = profile."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    profiles = []
    try:
        paginator = dynamodb.get_paginator("query")
        for page in paginator.paginate(
            TableName=TABLE_NAME,
            IndexName="entity-type-index",
            KeyConditionExpression="entity_type = :et",
            ExpressionAttributeValues={":et": {"S": "profile"}},
        ):
            for item in page.get("Items", []):
                profiles.append(
                    {
                        "profile_id": item.get("profile_id", {}).get("S", ""),
                        "version": item.get("version", {}).get("S", ""),
                        "tenant_id": item.get("tenant_id", {}).get("S", ""),
                        "mode": item.get("mode", {}).get("S", ""),
                        "status": item.get("status", {}).get("S", ""),
                        "pk": item.get("pk", {}).get("S", ""),
                        "sk": item.get("sk", {}).get("S", ""),
                    }
                )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Table {TABLE_NAME} not found. Run migrations first.")
        else:
            print(f"Error: {e}")
        return None
    return profiles


def main():
    print(f"DynamoDB table: {TABLE_NAME} (region: {AWS_REGION})")
    print()
    profiles = list_profiles()
    if profiles is None:
        return 1
    if not profiles:
        print("No profiles found.")
        return 0
    print(f"Available profiles ({len(profiles)}):")
    print("-" * 80)
    for p in sorted(profiles, key=lambda x: (x["tenant_id"], x["profile_id"], x["version"])):
        print(f"  tenant={p['tenant_id']:<10} profile_id={p['profile_id']:<25} version={p['version']:<6} mode={p['mode']:<10} status={p['status']}")
    print("-" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
