#!/usr/bin/env python3
import boto3
from botocore.exceptions import ClientError

def create_and_secure_bucket(bucket_name, region="us-east-1"):
    s3_client = boto3.client('s3', region_name=region)
    
    try:
        print(f"Creating S3 bucket: '{bucket_name}' in region '{region}'...")
        
        # 1. Create Bucket
        # Note: us-east-1 does not accept LocationConstraint configuration, other regions do.
        if region == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print("   ✅ Bucket created successfully.")

        # 2. Enable Server-Side Encryption (AES-256)
        print("   🔒 Enabling default server-side encryption...")
        s3_client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                'Rules': [
                    {
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'AES256'
                        }
                    },
                ]
            }
        )

        # 3. Enable Block Public Access (Security Best Practice)
        print("   🛡️ Applying S3 Block Public Access...")
        s3_client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            }
        )

        # 4. Apply Mandatory Governance Tags
        print("   🏷️ Applying mandatory governance tags...")
        mandatory_tags = [
            {'Key': 'Environment', 'Value': 'Production'},
            {'Key': 'Service', 'Value': 'Core-SaaS'},
            {'Key': 'Owner', 'Value': 'DevOps-Team'},
            {'Key': 'CostCenter', 'Value': 'CC-1001'}
        ]
        s3_client.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={'TagSet': mandatory_tags}
        )
        print(f"   ✅ Successfully tagged bucket '{bucket_name}'!")

    except ClientError as e:
        print(f"❌ Error setting up S3 bucket: {e.response['Error']['Message']}")

if __name__ == "__main__":
    # S3 bucket names must be globally unique across all AWS accounts!
    # Change this name to something unique (e.g., your-company-saas-assets-905418)
    BUCKET_NAME = "kodekloud-saas-assets-secure-905418"
    REGION = "us-east-1"
    
    create_and_secure_bucket(BUCKET_NAME, REGION)