import json
import zipfile
import io
import time
import boto3
from botocore.exceptions import ClientError

# Define list of deprecated/EOL runtimes
DEPRECATED_RUNTIMES = [
    'nodejs10.x', 'nodejs12.x', 'nodejs14.x',
    'python3.6', 'python3.7', 'python3.8',
    'java8', 'dotnetcore3.1', 'ruby2.7'
]

def audit_and_block_deprecated_runtimes(lambda_client):
    """
    Scans all existing Lambda functions in the account/region and 
    checks for deprecated or EOL runtimes.
    """
    print("🔍 Auditing existing Lambda functions for deprecated runtimes...")
    paginator = lambda_client.get_paginator('list_functions')
    deprecated_found = []

    for page in paginator.paginate():
        for fn in page['Functions']:
            func_name = fn['FunctionName']
            runtime = fn.get('Runtime', 'Unknown')
            
            if runtime in DEPRECATED_RUNTIMES:
                deprecated_found.append({
                    'FunctionName': func_name,
                    'Runtime': runtime
                })
                print(f"⚠️ [DEPRECATED RUNTIME DETECTED] Function: '{func_name}' is using runtime '{runtime}'")

    if deprecated_found:
        print(f"\n❌ Audit Warning: Found {len(deprecated_found)} function(s) using deprecated runtimes.")
        # Optional: Uncomment the line below to strictly block deployment if EOL runtimes exist
        # raise Exception("Deployment blocked: Deprecated Lambda runtimes detected in account!")
    else:
        print("✅ Fleet Audit Passed: No deprecated Lambda runtimes found.")

def create_lambda_deployment_package():
    """Creates an in-memory zip file containing a compliant Python handler."""
    lambda_code = '''
def lambda_handler(event, context):
    print("Received event: ", event)
    return {
        'statusCode': 200,
        'body': 'Hello from Lambda using lambda_execution_role!'
    }
'''
    zip_output = io.BytesIO()
    with zipfile.ZipFile(zip_output, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('lambda_function.py', lambda_code)
    return zip_output.getvalue()

def get_existing_lambda_execution_role(iam_client, role_name="lambda_execution_role"):
    """
    Retrieves the pre-existing lambda_execution_role. 
    If it doesn't exist, it creates it with the exact mandatory name.
    """
    try:
        response = iam_client.get_role(RoleName=role_name)
        print(f"✅ Found pre-existing IAM Role: {role_name}")
        return response['Role']['Arn']
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchEntity':
            print(f"⚠️ Role '{role_name}' not found. Creating it now with the exact required name...")
            
            trust_relationship = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            response = iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_relationship),
                Description='Mandatory execution role for AWS Lambda'
            )
            role_arn = response['Role']['Arn']
            
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
            )
            print(f"✅ Created and configured '{role_name}' successfully.")
            return role_arn
        else:
            raise e

def wait_for_lambda_ready(lambda_client, function_name, max_attempts=15, delay=5):
    """Polls the Lambda function until LastUpdateStatus is Successful and State is Active."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = lambda_client.get_function(FunctionName=function_name)
            state = response['Configuration'].get('State')
            update_status = response['Configuration'].get('LastUpdateStatus', 'Successful')
            
            print(f"⏳ (Attempt {attempt}/{max_attempts}) Lambda State: {state}, UpdateStatus: {update_status}...")
            
            if state == 'Active' and update_status == 'Successful':
                return response['Configuration']['FunctionArn']
            elif update_status == 'Failed':
                reason = response['Configuration'].get('LastUpdateStatusReason', 'Unknown reason')
                raise Exception(f"❌ Lambda update failed: {reason}")
                
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise e
        
        time.sleep(delay)
    
    raise Exception("❌ Timed out waiting for Lambda function to become ready.")

def deploy_lambda_function(lambda_client, role_arn, function_name="compliant-lambda-function"):
    """Deploys or updates the Lambda function with robust manual state waiting."""
    zip_bytes = create_lambda_deployment_package()
    
    max_retries = 10
    delay = 6
    
    for attempt in range(1, max_retries + 1):
        try:
            response = lambda_client.create_function(
                FunctionName=function_name,
                Runtime='python3.9',
                Role=role_arn,
                Handler='lambda_function.lambda_handler',
                Code={'ZipFile': zip_bytes},
                Description='Lambda function using mandatory lambda_execution_role',
                Timeout=10,
                MemorySize=256,
                Publish=True
            )
            print(f"✅ Successfully created Lambda function: {function_name}")
            return response['FunctionArn']
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'InvalidParameterValueException' and 'cannot be assumed by Lambda' in error_message:
                print(f"⏳ (Attempt {attempt}/{max_retries}) IAM role propagation in progress... waiting {delay}s...")
                time.sleep(delay)
            elif error_code == 'ResourceConflictException':
                print(f"ℹ️ Function {function_name} already exists. Waiting for any ongoing updates to settle...")
                
                wait_for_lambda_ready(lambda_client, function_name)
                
                print("📤 Updating function code...")
                lambda_client.update_function_code(
                    FunctionName=function_name,
                    ZipFile=zip_bytes,
                    Publish=True
                )
                
                print("⏳ Waiting for code update to complete...")
                wait_for_lambda_ready(lambda_client, function_name)
                
                print("⚙️ Updating function configuration and role...")
                lambda_client.update_function_configuration(
                    FunctionName=function_name,
                    Role=role_arn,
                    Timeout=10,
                    MemorySize=256
                )
                
                print("⏳ Waiting for configuration update to complete...")
                final_arn = wait_for_lambda_ready(lambda_client, function_name)
                
                print(f"✅ Successfully updated Lambda function: {function_name}")
                return final_arn
            else:
                raise e
    
    raise Exception("❌ Timed out waiting for IAM role propagation or Lambda update.")

def configure_api_gateway(api_client, lambda_client, function_arn, function_name="compliant-lambda-function", api_name="compliant-lambda-api"):
    """Creates an API Gateway HTTP API and integrates it with the Lambda function."""
    try:
        sts_client = boto3.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
        
        api_response = api_client.create_api(
            Name=api_name,
            ProtocolType='HTTP',
            Target=function_arn
        )
        api_id = api_response['ApiId']
        api_endpoint = api_response['ApiEndpoint']
        print(f"✅ Created API Gateway HTTP API: {api_name} ({api_endpoint})")

        source_arn = f"arn:aws:execute-api:us-east-1:{account_id}:{api_id}/*/*"
        
        try:
            lambda_client.add_permission(
                FunctionName=function_name,
                StatementId='AllowExecutionFromAPIGateway',
                Action='lambda:InvokeFunction',
                Principal='apigateway.amazonaws.com',
                SourceArn=source_arn
            )
            print("✅ Granted API Gateway permission to invoke Lambda.")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceConflictException':
                print("ℹ️ Lambda permission for API Gateway already exists.")
            else:
                raise e

        return api_endpoint
    except ClientError as e:
        print(f"⚠️ Error setting up API Gateway: {e.response['Error']['Message']}")
        return None

if __name__ == "__main__":
    REGION = "us-east-1"
    FUNCTION_NAME = "compliant-lambda-function"
    MANDATORY_ROLE_NAME = "lambda_execution_role"

    boto3.setup_default_session(region_name=REGION)
    lambda_client = boto3.client('lambda')
    iam_client = boto3.client('iam')
    api_client = boto3.client('apigatewayv2')

    print("🚀 Starting Compliant AWS Lambda Deployment with API Gateway...")

    # Step 0: Audit account for EOL/Deprecated runtimes
    audit_and_block_deprecated_runtimes(lambda_client)

    # Step 1: Get or create the exact mandatory role name
    role_arn = get_existing_lambda_execution_role(iam_client, MANDATORY_ROLE_NAME)

    # Step 2: Deploy Lambda function
    function_arn = deploy_lambda_function(lambda_client, role_arn, FUNCTION_NAME)

    # Step 3: Configure API Gateway HTTP API Integration
    api_endpoint = configure_api_gateway(api_client, lambda_client, function_arn, FUNCTION_NAME)

    print("\n🎉 Deployment Complete!")
    print(f"   - Function Name: {FUNCTION_NAME}")
    print(f"   - Assigned IAM Role: {MANDATORY_ROLE_NAME}")
    print(f"   - API Gateway Endpoint: {api_endpoint}")