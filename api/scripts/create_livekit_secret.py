"""
Create or update the LiveKit secret in AWS Secrets Manager for Lambda (and optionally EKS).

Usage:
  Set env vars LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, then:
    uv run python api/scripts/create_livekit_secret.py
  Or pass secret name and region:
    LIVEKIT_SECRET_ID=my-secret AWS_REGION=us-east-1 uv run python api/scripts/create_livekit_secret.py

Requires: boto3, AWS credentials (env or profile).
"""

import json
import os
import sys
from pathlib import Path

# Project root
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env.local")
load_dotenv()

SECRET_ID = os.getenv("LIVEKIT_SECRET_ID", "livekit-agent-secrets")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def main():
    url = os.getenv("LIVEKIT_URL")
    key = os.getenv("LIVEKIT_API_KEY")
    secret = os.getenv("LIVEKIT_API_SECRET")

    if not url or not key or not secret:
        print("Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (e.g. in .env.local) then run again.")
        sys.exit(1)

    secret_string = json.dumps({
        "LIVEKIT_URL": url,
        "LIVEKIT_API_KEY": key,
        "LIVEKIT_API_SECRET": secret,
    })

    import boto3
    client = boto3.client("secretsmanager", region_name=AWS_REGION)

    try:
        client.create_secret(
            Name=SECRET_ID,
            SecretString=secret_string,
        )
        print(f"Created secret: {SECRET_ID}")
    except client.exceptions.ResourceExistsException:
        client.put_secret_value(
            SecretId=SECRET_ID,
            SecretString=secret_string,
        )
        print(f"Updated secret: {SECRET_ID}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
