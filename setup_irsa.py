#!/usr/bin/env python3
import os
import boto3
from botocore.exceptions import ClientError

# Configuration from environment variables (passed via Jenkins)
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME", "demo-eks")

def check_aws_connection():
    """Verify that AWS credentials and IAM role (IRSA) are working correctly."""
    print("Verifying AWS connection and current identity...")
    try:
        sts_client = boto3.client("sts", region_name=AWS_REGION)
        identity = sts_client.get_caller_identity()
        print(f"Successfully authenticated with AWS!")
        print(f"  Account ID : {identity.get('Account')}")
        print(f"  ARN        : {identity.get('Arn')}")
    except ClientError as e:
        print(f"❌ Failed to connect to AWS: {e}")
        raise

def ensure_prerequisites():
    """Add any custom boto3 logic here (e.g., checking/creating secrets, S3 buckets, etc.)"""
    print(f"Running infrastructure prerequisites setup for cluster: {CLUSTER_NAME} in region: {AWS_REGION}...")
    
    # Example: Interacting with Secrets Manager or Parameter Store if SonarQube needs external DB credentials
    # secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)
    # try:
    #     response = secrets_client.describe_secret(SecretId="sonar/db/credentials")
    #     print("✅ Found existing database secret in AWS Secrets Manager.")
    # except ClientError as e:
    #     print("⚠️ Secret not found or needs creation. Handle creation logic here if needed.")

    print("✅ Prerequisites check completed successfully.")

if __name__ == "__main__":
    print("=== Starting Python AWS/IRSA Setup Script ===" )
    check_aws_connection()
    ensure_prerequisites()
    print("=== Setup Script Completed Successfully ===")