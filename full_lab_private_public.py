import io
import json
import time
import uuid
import zipfile

import boto3
from botocore.exceptions import ClientError


# ============================================================
# CONFIGURATION
# ============================================================

REGION = "us-east-1"

# Lab-required Lambda role
LAMBDA_ROLE_NAME = "lambda_execution_role"

# Lambda runtime
LAMBDA_RUNTIME = "python3.12"

# Optional: set your email to receive SNS notifications.
# Example: SNS_EMAIL = "your-email@example.com"
SNS_EMAIL = ""

# Sample Cognito user for lab testing only.
COGNITO_SAMPLE_EMAIL = "lab.user@example.com"
COGNITO_SAMPLE_TEMP_PASSWORD = "LabTempPassword123"
CREATE_COGNITO_SAMPLE_USER = True

# Lab VPC ranges
VPC_CIDR = "10.50.0.0/16"
PUBLIC_SUBNET_CIDR = "10.50.1.0/24"
PRIVATE_SUBNET_CIDR = "10.50.2.0/24"


# ============================================================
# UNIQUE RESOURCE NAMES
# ============================================================

suffix = uuid.uuid4().hex[:10]

VPC_NAME = f"lab-vpc-{suffix}"
PUBLIC_SUBNET_NAME = f"lab-public-subnet-{suffix}"
PRIVATE_SUBNET_NAME = f"lab-private-subnet-{suffix}"
SECURITY_GROUP_NAME = f"lab-lambda-sg-{suffix}"

BUCKET_NAME = f"lab-upload-{suffix}"
SNS_TOPIC_NAME = f"lab-notifications-{suffix}"
LAMBDA_NAME = f"lab-processing-{suffix}"
EVENT_RULE_NAME = f"lab-s3-object-created-{suffix}"
COGNITO_POOL_NAME = f"lab-users-{suffix}"

KMS_ALIAS_NAME = f"alias/lab-key-{suffix}"
SECRET_NAME = f"lab/sample-app-config-{suffix}"


# ============================================================
# AWS CLIENTS
# ============================================================

boto3.setup_default_session(region_name=REGION)

sts_client = boto3.client("sts")
iam_client = boto3.client("iam")
ec2_client = boto3.client("ec2")
s3_client = boto3.client("s3")
sns_client = boto3.client("sns")
kms_client = boto3.client("kms")
secrets_client = boto3.client("secretsmanager")
lambda_client = boto3.client("lambda")
events_client = boto3.client("events")
cognito_client = boto3.client("cognito-idp")


# ============================================================
# HELPERS
# ============================================================

def print_section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def get_account_id():
    return sts_client.get_caller_identity()["Account"]


def wait_for_lambda_ready(function_name, max_attempts=60, delay=10):
    """
    Wait for Lambda to become Active.
    Maximum wait is approximately 10 minutes.
    """

    for attempt in range(1, max_attempts + 1):
        response = lambda_client.get_function_configuration(
            FunctionName=function_name
        )

        state = response.get("State")
        state_reason = response.get("StateReason")
        state_reason_code = response.get("StateReasonCode")

        update_status = response.get(
            "LastUpdateStatus",
            "Successful"
        )

        update_reason = response.get(
            "LastUpdateStatusReason"
        )

        print(
            f"Lambda attempt {attempt}/{max_attempts}: "
            f"State={state}, UpdateStatus={update_status}"
        )

        if state == "Active" and update_status == "Successful":
            return response["FunctionArn"]

        if state == "Failed":
            raise RuntimeError(
                "Lambda failed.\n"
                f"Reason: {state_reason}\n"
                f"Reason code: {state_reason_code}"
            )

        if update_status == "Failed":
            raise RuntimeError(
                "Lambda update failed.\n"
                f"Reason: {update_reason}"
            )

        time.sleep(delay)

    raise TimeoutError(
        "Timed out waiting for Lambda to become Active."
    )


# ============================================================
# IAM ROLE
# ============================================================

def get_or_create_lambda_execution_role():
    """
    Create or reuse the required lab Lambda execution role.
    """

    print_section("Getting or creating Lambda execution role")

    try:
        response = iam_client.get_role(
            RoleName=LAMBDA_ROLE_NAME
        )

        role_arn = response["Role"]["Arn"]

        print("Found existing Lambda role:", LAMBDA_ROLE_NAME)
        print("Role ARN:", role_arn)

    except ClientError as error:
        error_code = error.response["Error"].get("Code")

        if error_code != "NoSuchEntity":
            raise

        print(
            f"Role '{LAMBDA_ROLE_NAME}' does not exist. "
            "Creating it."
        )

        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }

        response = iam_client.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Lambda execution role for AWS lab testing"
        )

        role_arn = response["Role"]["Arn"]

        print("Lambda role created:", role_arn)

    # Required for Lambda CloudWatch Logs access.
    iam_client.attach_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyArn=(
            "arn:aws:iam::aws:policy/"
            "service-role/AWSLambdaBasicExecutionRole"
        )
    )

    # Required for Lambda inside private subnet / VPC.
    iam_client.attach_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyArn=(
            "arn:aws:iam::aws:policy/"
            "service-role/AWSLambdaVPCAccessExecutionRole"
        )
    )

    print("Attached AWSLambdaBasicExecutionRole.")
    print("Attached AWSLambdaVPCAccessExecutionRole.")

    print("Waiting for IAM role propagation...")
    time.sleep(20)

    return role_arn


# ============================================================
# VPC, SUBNETS, ROUTES, SECURITY GROUP
# ============================================================

def create_vpc_network():
    """
    Creates:
    - VPC
    - Internet Gateway
    - Public subnet
    - Private subnet
    - Public route table
    - Private route table
    - Security group
    """

    print_section("Creating VPC, public subnet, and private subnet")

    zones_response = ec2_client.describe_availability_zones(
        Filters=[
            {
                "Name": "state",
                "Values": ["available"]
            }
        ]
    )

    available_zones = [
        zone["ZoneName"]
        for zone in zones_response["AvailabilityZones"]
    ]

    if not available_zones:
        raise RuntimeError("No available Availability Zone found.")

    availability_zone = available_zones[0]

    # Create VPC
    response = ec2_client.create_vpc(
        CidrBlock=VPC_CIDR,
        TagSpecifications=[
            {
                "ResourceType": "vpc",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": VPC_NAME
                    },
                    {
                        "Key": "Environment",
                        "Value": "lab"
                    }
                ]
            }
        ]
    )

    vpc_id = response["Vpc"]["VpcId"]

    ec2_client.modify_vpc_attribute(
        VpcId=vpc_id,
        EnableDnsSupport={"Value": True}
    )

    ec2_client.modify_vpc_attribute(
        VpcId=vpc_id,
        EnableDnsHostnames={"Value": True}
    )

    print("VPC:", vpc_id)

    # Internet Gateway
    response = ec2_client.create_internet_gateway(
        TagSpecifications=[
            {
                "ResourceType": "internet-gateway",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": f"{VPC_NAME}-igw"
                    }
                ]
            }
        ]
    )

    internet_gateway_id = (
        response["InternetGateway"]["InternetGatewayId"]
    )

    ec2_client.attach_internet_gateway(
        InternetGatewayId=internet_gateway_id,
        VpcId=vpc_id
    )

    print("Internet Gateway:", internet_gateway_id)

    # Public subnet
    response = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock=PUBLIC_SUBNET_CIDR,
        AvailabilityZone=availability_zone,
        TagSpecifications=[
            {
                "ResourceType": "subnet",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": PUBLIC_SUBNET_NAME
                    }
                ]
            }
        ]
    )

    public_subnet_id = response["Subnet"]["SubnetId"]

    ec2_client.modify_subnet_attribute(
        SubnetId=public_subnet_id,
        MapPublicIpOnLaunch={"Value": True}
    )

    print("Public subnet:", public_subnet_id)

    # Private subnet
    response = ec2_client.create_subnet(
        VpcId=vpc_id,
        CidrBlock=PRIVATE_SUBNET_CIDR,
        AvailabilityZone=availability_zone,
        TagSpecifications=[
            {
                "ResourceType": "subnet",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": PRIVATE_SUBNET_NAME
                    }
                ]
            }
        ]
    )

    private_subnet_id = response["Subnet"]["SubnetId"]

    print("Private subnet:", private_subnet_id)

    # Public route table
    response = ec2_client.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "route-table",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": f"{VPC_NAME}-public-route-table"
                    }
                ]
            }
        ]
    )

    public_route_table_id = (
        response["RouteTable"]["RouteTableId"]
    )

    ec2_client.create_route(
        RouteTableId=public_route_table_id,
        DestinationCidrBlock="0.0.0.0/0",
        GatewayId=internet_gateway_id
    )

    ec2_client.associate_route_table(
        RouteTableId=public_route_table_id,
        SubnetId=public_subnet_id
    )

    print("Public route table:", public_route_table_id)

    # Private route table
    response = ec2_client.create_route_table(
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "route-table",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": f"{VPC_NAME}-private-route-table"
                    }
                ]
            }
        ]
    )

    private_route_table_id = (
        response["RouteTable"]["RouteTableId"]
    )

    ec2_client.associate_route_table(
        RouteTableId=private_route_table_id,
        SubnetId=private_subnet_id
    )

    print("Private route table:", private_route_table_id)

    # Security group
    response = ec2_client.create_security_group(
        GroupName=SECURITY_GROUP_NAME,
        Description=(
            "Security group for Lambda and VPC endpoints in the lab"
        ),
        VpcId=vpc_id,
        TagSpecifications=[
            {
                "ResourceType": "security-group",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": SECURITY_GROUP_NAME
                    }
                ]
            }
        ]
    )

    security_group_id = response["GroupId"]

    # Allow HTTPS from within the lab VPC.
    ec2_client.authorize_security_group_ingress(
        GroupId=security_group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "IpRanges": [
                    {
                        "CidrIp": VPC_CIDR,
                        "Description": "HTTPS traffic within lab VPC"
                    }
                ]
            }
        ]
    )

    print("Security group:", security_group_id)

    return {
        "vpc_id": vpc_id,
        "internet_gateway_id": internet_gateway_id,
        "public_subnet_id": public_subnet_id,
        "private_subnet_id": private_subnet_id,
        "private_route_table_id": private_route_table_id,
        "security_group_id": security_group_id
    }


# ============================================================
# VPC ENDPOINTS
# ============================================================

def create_vpc_endpoints(network):
    """
    Creates endpoints for private Lambda service access.

    Gateway endpoint:
    - S3

    Interface endpoints:
    - CloudWatch Logs
    - SNS
    - Secrets Manager
    """

    print_section("Creating VPC endpoints for private Lambda")

    vpc_id = network["vpc_id"]
    private_subnet_id = network["private_subnet_id"]
    private_route_table_id = network["private_route_table_id"]
    security_group_id = network["security_group_id"]

    # S3 gateway endpoint
    response = ec2_client.create_vpc_endpoint(
        VpcId=vpc_id,
        ServiceName=f"com.amazonaws.{REGION}.s3",
        VpcEndpointType="Gateway",
        RouteTableIds=[
            private_route_table_id
        ],
        TagSpecifications=[
            {
                "ResourceType": "vpc-endpoint",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": f"{VPC_NAME}-s3-endpoint"
                    }
                ]
            }
        ]
    )

    print(
        "S3 gateway endpoint:",
        response["VpcEndpoint"]["VpcEndpointId"]
    )

    # Interface endpoints
    for service_name in [
        "logs",
        "sns",
        "secretsmanager"
    ]:
        response = ec2_client.create_vpc_endpoint(
            VpcId=vpc_id,
            ServiceName=(
                f"com.amazonaws.{REGION}.{service_name}"
            ),
            VpcEndpointType="Interface",
            SubnetIds=[
                private_subnet_id
            ],
            SecurityGroupIds=[
                security_group_id
            ],
            PrivateDnsEnabled=True,
            TagSpecifications=[
                {
                    "ResourceType": "vpc-endpoint",
                    "Tags": [
                        {
                            "Key": "Name",
                            "Value": (
                                f"{VPC_NAME}-{service_name}-endpoint"
                            )
                        }
                    ]
                }
            ]
        )

        print(
            f"{service_name} interface endpoint:",
            response["VpcEndpoint"]["VpcEndpointId"]
        )


# ============================================================
# KMS
# ============================================================

def create_customer_managed_kms_key():
    print_section("Creating customer-managed KMS key")

    response = kms_client.create_key(
        Description=(
            "Lab KMS key for S3 and Secrets Manager encryption"
        ),
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        Tags=[
            {
                "TagKey": "Environment",
                "TagValue": "lab"
            },
            {
                "TagKey": "Purpose",
                "TagValue": "s3-secrets-encryption"
            }
        ]
    )

    key_id = response["KeyMetadata"]["KeyId"]
    key_arn = response["KeyMetadata"]["Arn"]

    kms_client.create_alias(
        AliasName=KMS_ALIAS_NAME,
        TargetKeyId=key_id
    )

    print("KMS key ID:", key_id)
    print("KMS key ARN:", key_arn)
    print("KMS alias:", KMS_ALIAS_NAME)

    return key_arn


# ============================================================
# S3 BUCKET
# ============================================================

def create_encrypted_s3_bucket(kms_key_arn):
    print_section("Creating KMS-encrypted S3 bucket")

    if REGION == "us-east-1":
        s3_client.create_bucket(
            Bucket=BUCKET_NAME
        )
    else:
        s3_client.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={
                "LocationConstraint": REGION
            }
        )

    s3_client.put_bucket_encryption(
        Bucket=BUCKET_NAME,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms",
                        "KMSMasterKeyID": kms_key_arn
                    },
                    "BucketKeyEnabled": True
                }
            ]
        }
    )

    s3_client.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True
        }
    )

    print("S3 bucket:", BUCKET_NAME)
    print("S3 SSE-KMS key:", kms_key_arn)


# ============================================================
# SECRETS MANAGER
# ============================================================

def create_sample_secret(kms_key_arn):
    print_section("Creating sample Secrets Manager secret")

    sample_secret_value = {
        "environment": "lab",
        "application_name": "s3-eventbridge-lambda-lab",
        "sample_api_key": "LAB-ONLY-NOT-A-REAL-API-KEY",
        "database_host": "lab-db.example.internal",
        "database_username": "lab_user",
        "database_password": "LabOnlyPassword-NotForProduction"
    }

    response = secrets_client.create_secret(
        Name=SECRET_NAME,
        Description="Lab-only sample application secret",
        KmsKeyId=kms_key_arn,
        SecretString=json.dumps(sample_secret_value),
        Tags=[
            {
                "Key": "Environment",
                "Value": "lab"
            }
        ]
    )

    secret_arn = response["ARN"]

    print("Secret name:", SECRET_NAME)
    print("Secret ARN:", secret_arn)

    return secret_arn


# ============================================================
# SNS
# ============================================================

def create_sns_topic():
    print_section("Creating SNS topic")

    response = sns_client.create_topic(
        Name=SNS_TOPIC_NAME
    )

    topic_arn = response["TopicArn"]

    print("SNS topic:", topic_arn)

    if SNS_EMAIL:
        sns_client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=SNS_EMAIL
        )

        print("SNS email subscription created.")
        print("Confirm the subscription from your email.")
    else:
        print("SNS_EMAIL is empty; no email subscription created.")

    return topic_arn


# ============================================================
# COGNITO
# ============================================================

def create_cognito_resources():
    print_section("Creating Cognito User Pool")

    response = cognito_client.create_user_pool(
        PoolName=COGNITO_POOL_NAME,
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 8,
                "RequireUppercase": False,
                "RequireLowercase": False,
                "RequireNumbers": True,
                "RequireSymbols": False,
                "TemporaryPasswordValidityDays": 7
            }
        },
        AutoVerifiedAttributes=[
            "email"
        ],
        UsernameAttributes=[
            "email"
        ],
        UserPoolTags={
            "Environment": "lab",
            "Purpose": "testing"
        }
    )

    user_pool = response["UserPool"]
    user_pool_id = user_pool["Id"]

    client_response = cognito_client.create_user_pool_client(
        UserPoolId=user_pool_id,
        ClientName=f"lab-client-{suffix}",
        GenerateSecret=False,
        ExplicitAuthFlows=[
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH"
        ]
    )

    cognito_client_id = (
        client_response["UserPoolClient"]["ClientId"]
    )

    print("Cognito User Pool ID:", user_pool_id)
    print("Cognito App Client ID:", cognito_client_id)

    if CREATE_COGNITO_SAMPLE_USER:
        cognito_client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=COGNITO_SAMPLE_EMAIL,
            TemporaryPassword=COGNITO_SAMPLE_TEMP_PASSWORD,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {
                    "Name": "email",
                    "Value": COGNITO_SAMPLE_EMAIL
                },
                {
                    "Name": "email_verified",
                    "Value": "true"
                }
            ]
        )

        print("Sample Cognito user:", COGNITO_SAMPLE_EMAIL)

    return user_pool_id, cognito_client_id


# ============================================================
# LAMBDA PACKAGE
# ============================================================

def create_lambda_deployment_package():
    lambda_code = r'''
import json
import os


def lambda_handler(event, context):
    print("Received EventBridge event:")
    print(json.dumps(event))

    detail = event.get("detail", {})

    bucket_name = detail.get(
        "bucket",
        {}
    ).get(
        "name",
        "unknown-bucket"
    )

    object_key = detail.get(
        "object",
        {}
    ).get(
        "key",
        "unknown-key"
    )

    object_size = detail.get(
        "object",
        {}
    ).get(
        "size",
        "unknown"
    )

    print("S3 object-created event processed.")
    print("Bucket:", bucket_name)
    print("Object:", object_key)
    print("Size:", object_size)

    # Only resource references are logged.
    # The secret value is not retrieved or logged.
    print("KMS key ARN:", os.environ.get("KMS_KEY_ARN"))
    print("Secret ARN:", os.environ.get("SECRET_ARN"))
    print(
        "Cognito pool:",
        os.environ.get("COGNITO_USER_POOL_ID")
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "S3 event processed successfully",
            "bucket": bucket_name,
            "key": object_key,
            "size": object_size
        })
    }
'''

    zip_output = io.BytesIO()

    with zipfile.ZipFile(
        zip_output,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zip_file:
        zip_file.writestr(
            "lambda_function.py",
            lambda_code
        )

    return zip_output.getvalue()


# ============================================================
# LAMBDA
# ============================================================

def deploy_lambda_function(
    role_arn,
    kms_key_arn,
    secret_arn,
    user_pool_id,
    cognito_client_id,
    network
):
    print_section("Deploying Lambda in private subnet")

    zip_bytes = create_lambda_deployment_package()

    lambda_environment = {
        "Variables": {
            "LAB_BUCKET_NAME": BUCKET_NAME,
            "KMS_KEY_ARN": kms_key_arn,
            "SECRET_ARN": secret_arn,
            "COGNITO_USER_POOL_ID": user_pool_id,
            "COGNITO_APP_CLIENT_ID": cognito_client_id
        }
    }

    response = lambda_client.create_function(
        FunctionName=LAMBDA_NAME,
        Runtime=LAMBDA_RUNTIME,
        Role=role_arn,
        Handler="lambda_function.lambda_handler",
        Code={
            "ZipFile": zip_bytes
        },
        Description="Private subnet Lambda for AWS lab",
        Timeout=30,
        MemorySize=128,
        Publish=True,
        Environment=lambda_environment,
        VpcConfig={
            "SubnetIds": [
                network["private_subnet_id"]
            ],
            "SecurityGroupIds": [
                network["security_group_id"]
            ]
        },
        Tags={
            "Environment": "lab",
            "Purpose": "s3-eventbridge-test"
        }
    )

    lambda_arn = response["FunctionArn"]

    print("Lambda created:", lambda_arn)

    wait_for_lambda_ready(
        LAMBDA_NAME,
        max_attempts=60,
        delay=10
    )

    return lambda_arn


# ============================================================
# EVENTBRIDGE
# ============================================================

def configure_eventbridge(lambda_arn, topic_arn):
    print_section("Configuring S3 -> EventBridge -> Lambda and SNS")

    s3_client.put_bucket_notification_configuration(
        Bucket=BUCKET_NAME,
        NotificationConfiguration={
            "EventBridgeConfiguration": {}
        }
    )

    print("S3 EventBridge notifications enabled.")

    event_pattern = {
        "source": [
            "aws.s3"
        ],
        "detail-type": [
            "Object Created"
        ],
        "detail": {
            "bucket": {
                "name": [
                    BUCKET_NAME
                ]
            }
        }
    }

    rule_response = events_client.put_rule(
        Name=EVENT_RULE_NAME,
        EventPattern=json.dumps(event_pattern),
        State="ENABLED",
        Description="S3 Object Created EventBridge lab rule"
    )

    rule_arn = rule_response["RuleArn"]

    print("EventBridge rule:", rule_arn)

    lambda_client.add_permission(
        FunctionName=LAMBDA_NAME,
        StatementId=f"eventbridge-{suffix}",
        Action="lambda:InvokeFunction",
        Principal="events.amazonaws.com",
        SourceArn=rule_arn
    )

    topic_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowEventBridgePublish",
                "Effect": "Allow",
                "Principal": {
                    "Service": "events.amazonaws.com"
                },
                "Action": "sns:Publish",
                "Resource": topic_arn,
                "Condition": {
                    "ArnEquals": {
                        "aws:SourceArn": rule_arn
                    }
                }
            }
        ]
    }

    sns_client.set_topic_attributes(
        TopicArn=topic_arn,
        AttributeName="Policy",
        AttributeValue=json.dumps(topic_policy)
    )

    events_client.put_targets(
        Rule=EVENT_RULE_NAME,
        Targets=[
            {
                "Id": "LambdaTarget",
                "Arn": lambda_arn
            },
            {
                "Id": "SnsTarget",
                "Arn": topic_arn,
                "InputTransformer": {
                    "InputPathsMap": {
                        "bucket": "$.detail.bucket.name",
                        "key": "$.detail.object.key",
                        "size": "$.detail.object.size"
                    },
                    "InputTemplate": (
                        '"S3 object created. '
                        'Bucket: <bucket>, '
                        'Object: <key>, '
                        'Size: <size>"'
                    )
                }
            }
        ]
    )

    print("EventBridge Lambda target configured.")
    print("EventBridge SNS target configured.")

    return rule_arn


# ============================================================
# TEST FILE UPLOAD
# ============================================================

def upload_test_object():
    print_section("Uploading S3 test object")

    content = (
        "Hello from the private Lambda AWS lab.\n"
        "This file uses S3 default SSE-KMS encryption.\n"
    )

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key="incoming/sample.txt",
        Body=content.encode("utf-8"),
        ContentType="text/plain"
    )

    print(
        f"Uploaded: s3://{BUCKET_NAME}/incoming/sample.txt"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print_section("Starting complete public/private subnet AWS lab")

    account_id = get_account_id()

    print("AWS account:", account_id)
    print("AWS Region:", REGION)
    print("Lambda role:", LAMBDA_ROLE_NAME)
    print("Resource suffix:", suffix)

    # 1. Lambda role
    role_arn = get_or_create_lambda_execution_role()

    # 2. Public/private subnet network
    network = create_vpc_network()

    # 3. Endpoints for private Lambda connectivity
    create_vpc_endpoints(network)

    # 4. Customer-managed KMS key
    kms_key_arn = create_customer_managed_kms_key()

    # 5. KMS-encrypted S3 bucket
    create_encrypted_s3_bucket(kms_key_arn)

    # 6. Sample Secrets Manager secret
    secret_arn = create_sample_secret(kms_key_arn)

    # 7. SNS topic
    topic_arn = create_sns_topic()

    # 8. Cognito pool, app client, sample user
    user_pool_id, cognito_client_id = create_cognito_resources()

    # 9. Lambda in private subnet
    lambda_arn = deploy_lambda_function(
        role_arn=role_arn,
        kms_key_arn=kms_key_arn,
        secret_arn=secret_arn,
        user_pool_id=user_pool_id,
        cognito_client_id=cognito_client_id,
        network=network
    )

    # 10. S3 -> EventBridge -> Lambda + SNS
    rule_arn = configure_eventbridge(
        lambda_arn=lambda_arn,
        topic_arn=topic_arn
    )

    # 11. Test the flow
    upload_test_object()

    print_section("LAB DEPLOYMENT COMPLETE")

    print("VPC:", network["vpc_id"])
    print("Public subnet:", network["public_subnet_id"])
    print("Private subnet:", network["private_subnet_id"])
    print("Security group:", network["security_group_id"])
    print("KMS key:", kms_key_arn)
    print("S3 bucket:", BUCKET_NAME)
    print("Secret ARN:", secret_arn)
    print("SNS topic:", topic_arn)
    print("Lambda:", lambda_arn)
    print("Cognito User Pool:", user_pool_id)
    print("Cognito App Client:", cognito_client_id)
    print("Cognito sample user:", COGNITO_SAMPLE_EMAIL)
    print("EventBridge rule:", rule_arn)

    print("\nExpected flow:")
    print("S3 object upload")
    print("  -> EventBridge")
    print("  -> Lambda in private subnet")
    print("  -> SNS notification")

    print("\nView Lambda logs:")
    print(
        f"aws logs tail /aws/lambda/{LAMBDA_NAME} "
        f"--since 10m --region {REGION}"
    )