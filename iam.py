import boto3
import json
from botocore.exceptions import ClientError

# Initialize IAM client in eu-west-1 (or global, as IAM is global)
iam = boto3.client('iam', region_name='eu-west-1')

def create_role_if_not_exists(role_name, assume_role_policy, description=""):
    try:
        response = iam.get_role(RoleName=role_name)
        print(f"[INFO] Role '{role_name}' already exists. ARN: {response['Role']['Arn']}")
        return response['Role']['Arn']
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            print(f"[INFO] Creating role '{role_name}'...")
            try:
                response = iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(assume_role_policy),
                    Description=description
                )
                print(f"[✅] Successfully created: {response['Role']['Arn']}")
                return response['Role']['Arn']
            except ClientError as create_err:
                print(f"[❌] Error creating role '{role_name}': {create_err}")
                return None
        else:
            print(f"[❌] Error checking role '{role_name}': {e}")
            return None

def attach_policies_to_role(role_name, policy_arns):
    for policy_arn in policy_arns:
        try:
            iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy_arn
            )
            print(f"     -> Attached policy: {policy_arn}")
        except ClientError as e:
            print(f"     -> [!] Error attaching policy {policy_arn} to {role_name}: {e}")

def provision_lab_roles():
    # Trust Policies for different AWS services
    ec2_trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
    }
    lambda_trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
    }
    rds_trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "rds.amazonaws.com"}, "Action": "sts:AssumeRole"}]
    }
    general_trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": ["ec2.amazonaws.com", "lambda.amazonaws.com", "rds.amazonaws.com"]}, "Action": "sts:AssumeRole"}]
    }

    # Complete configuration mapping for your 7 lab roles
    roles_definition = [
        {
            "name": "S3AccessRole",
            "description": "Role for accessing S3 buckets for logs, backups, and app packages",
            "trust": ec2_trust,
            "policies": ["arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"]
        },
        {
            "name": "kk-rds-role",
            "description": "RDS database integration and management role",
            "trust": rds_trust,
            "policies": ["arn:aws:iam::aws:policy/AmazonRDSFullAccess"]
        },
        {
            "name": "rds-proxy-role",
            "description": "Role for RDS Proxy and Secrets Manager integration",
            "trust": rds_trust,
            "policies": [
                "arn:aws:iam::aws:policy/AmazonRDSDataFullAccess",
                "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
            ]
        },
        {
            "name": "rds-monitoring-role",
            "description": "Enhanced monitoring role for RDS instances",
            "trust": rds_trust,
            "policies": ["arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"]
        },
        {
            "name": "kk_labs",
            "description": "General administrator and execution role for lab tasks",
            "trust": general_trust,
            "policies": ["arn:aws:iam::aws:policy/AdministratorAccess"]
        },
        {
            "name": "lambda_execution_role",
            "description": "Execution role for AWS Lambda functions across runtimes",
            "trust": lambda_trust,
            "policies": [
                "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess",
                "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
            ]
        },
        {
            "name": "EC2-CloudWatch-Role",
            "description": "Role enabling EC2 instances to send logs and system metrics to CloudWatch",
            "trust": ec2_trust,
            "policies": [
                "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
                "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            ]
        }
    ]

    print("==================================================")
    print("   PROVISIONING LAB IAM ROLES FOR kk_labs SESSION")
    print("==================================================\n")

    for role_spec in roles_definition:
        print(f"\nProcessing Role: {role_spec['name']}")
        role_arn = create_role_if_not_exists(
            role_name=role_spec["name"],
            assume_role_policy=role_spec["trust"],
            description=role_spec["description"]
        )
        if role_arn:
            attach_policies_to_role(role_spec["name"], role_spec["policies"])

    print("\n==================================================")
    print("   ROLE PROVISIONING COMPLETE")
    print("==================================================")

if __name__ == '__main__':
    provision_lab_roles()