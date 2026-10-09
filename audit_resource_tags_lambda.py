#!/usr/bin/env python3
import boto3
from botocore.exceptions import ClientError

# Define mandatory governance tags to check
MANDATORY_TAGS = {"Environment", "Service", "Owner", "CostCenter"}

def check_tags(resource_name, resource_type, existing_tags):
    """Helper function to check if mandatory tags are present."""
    # Normalize existing tag keys (case-insensitive check support)
    tag_keys = {k.lower(): v for k, v in existing_tags.items()}
    
    missing_tags = []
    for mandatory in MANDATORY_TAGS:
        if mandatory.lower() not in tag_keys:
            missing_tags.append(mandatory)
            
    if missing_tags:
        print(f"   ❌ [{resource_type}] '{resource_name}' is MISSING tags: {missing_tags}")
        print(f"      Current Tags: {existing_tags}")
        return False
    else:
        print(f"   ✅ [{resource_type}] '{resource_name}' is fully compliant.")
        return True

def audit_eks_clusters(region):
    print("\n----------------------------------------")
    print("Auditing EKS Clusters...")
    print("----------------------------------------")
    client = boto3.client('eks', region_name=region)
    try:
        clusters = client.list_clusters().get('clusters', [])
        for cluster_name in clusters:
            cluster_desc = client.describe_cluster(name=cluster_name)['cluster']
            tags = cluster_desc.get('tags', {})
            check_tags(cluster_name, "EKS Cluster", tags)
    except ClientError as e:
        print(f"Error accessing EKS: {e.response['Error']['Message']}")

def audit_ec2_instances(region):
    print("\n----------------------------------------")
    print("Auditing EC2 Instances (Worker Nodes & others)...")
    print("----------------------------------------")
    client = boto3.client('ec2', region_name=region)
    try:
        paginator = client.get_paginator('describe_instances')
        for page in paginator.paginate():
            for reservation in page.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    if instance['State']['Name'] == 'terminated':
                        continue
                        
                    instance_id = instance['InstanceId']
                    name_tag = next((t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'), instance_id)
                    tags = {t['Key']: t['Value'] for t in instance.get('Tags', [])}
                    check_tags(name_tag, "EC2 Instance", tags)
    except ClientError as e:
        print(f"Error accessing EC2: {e.response['Error']['Message']}")

def audit_s3_buckets():
    print("\n----------------------------------------")
    print("Auditing S3 Buckets...")
    print("----------------------------------------")
    client = boto3.client('s3')
    try:
        response = client.list_buckets()
        for bucket in response.get('Buckets', []):
            bucket_name = bucket['Name']
            try:
                tag_response = client.get_bucket_tagging(Bucket=bucket_name)
                tags = {t['Key']: t['Value'] for t in tag_response.get('TagSet', [])}
                check_tags(bucket_name, "S3 Bucket", tags)
            except client.exceptions.ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'NoSuchTagSet':
                    print(f"   ❌ [S3 Bucket] '{bucket_name}' has NO tags assigned at all.")
                else:
                    print(f"   ⚠️ [S3 Bucket] '{bucket_name}' error checking tags: {e}")
    except ClientError as e:
        print(f"Error accessing S3: {e.response['Error']['Message']}")

def audit_lambda_functions(region):
    print("\n----------------------------------------")
    print("Auditing Lambda Functions...")
    print("----------------------------------------")
    client = boto3.client('lambda', region_name=region)
    try:
        paginator = client.get_paginator('list_functions')
        for page in paginator.paginate():
            for func in page.get('Functions', []):
                func_name = func['FunctionName']
                func_arn = func['FunctionArn']
                
                # Retrieve tags for the Lambda function using its ARN
                tag_response = client.list_tags(Resource=func_arn)
                tags = tag_response.get('Tags', {})
                check_tags(func_name, "Lambda Function", tags)
    except ClientError as e:
        print(f"Error accessing Lambda: {e.response['Error']['Message']}")

if __name__ == "__main__":
    region = "us-east-1"
    print(f"Starting Tag Audit for Region: {region}")
    print(f"Mandatory Tags Required: {list(MANDATORY_TAGS)}")
    
    audit_eks_clusters(region)
    audit_ec2_instances(region)
    audit_s3_buckets()
    audit_lambda_functions(region)
    
    print("\n----------------------------------------")
    print("Tag Audit Complete.")
    print("----------------------------------------")