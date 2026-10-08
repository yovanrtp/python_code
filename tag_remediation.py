#!/usr/bin/env python3
import boto3
from botocore.exceptions import ClientError

# Define standard governance tags to enforce
TARGET_TAGS = [
    {'Key': 'Environment', 'Value': 'Production'},
    {'Key': 'Service', 'Value': 'Core-SaaS'},
    {'Key': 'Owner', 'Value': 'DevOps-Team'},
    {'Key': 'CostCenter', 'Value': 'CC-1001'}
]

def tag_eks_clusters(region):
    client = boto3.client('eks', region_name=region)
    try:
        clusters = client.list_clusters().get('clusters', [])
        for cluster_name in clusters:
            # EKS uses resource ARNs for tagging
            cluster_desc = client.describe_cluster(name=cluster_name)['cluster']
            cluster_arn = cluster_desc['arn']
            
            print(f" tagging EKS Cluster: {cluster_name}")
            client.tag_resource(
                resourceArn=cluster_arn,
                tags={t['Key']: t['Value'] for t in TARGET_TAGS}
            )
    except ClientError as e:
        print(f"Error tagging EKS: {e.response['Error']['Message']}")

def tag_ec2_instances(region):
    client = boto3.client('ec2', region_name=region)
    try:
        # Find all running/stopped instances
        paginator = client.get_paginator('describe_instances')
        instance_ids = []
        for page in paginator.paginate():
            for reservation in page.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    if instance['State']['Name'] != 'terminated':
                        instance_ids.append(instance['InstanceId'])
                        
        if instance_ids:
            print(f" tagging {len(instance_ids)} EC2 Instance(s)...")
            client.create_tags(
                Resources=instance_ids,
                Tags=TARGET_TAGS
            )
    except ClientError as e:
        print(f"Error tagging EC2: {e.response['Error']['Message']}")

def tag_s3_buckets():
    client = boto3.client('s3')
    try:
        response = client.list_buckets()
        for bucket in response.get('Buckets', []):
            bucket_name = bucket['Name']
            print(f" tagging S3 Bucket: {bucket_name}")
            client.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={
                    'TagSet': TARGET_TAGS
                }
            )
    except ClientError as e:
        print(f"Error tagging S3: {e.response['Error']['Message']}")

if __name__ == "__main__":
    region = "us-east-1"
    print(f"Starting Auto-Tagging Remediation in region: {region}...\n")
    
    tag_eks_clusters(region)
    tag_ec2_instances(region)
    tag_s3_buckets()
    
    print("\n Remediation complete! Run your audit script again to verify compliance.")