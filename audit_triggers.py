import boto3

def audit_lambda_triggers():
    client = boto3.client('lambda')
    paginator = client.get_paginator('list_functions')
    
    for page in paginator.paginate():
        for func in page.get('Functions', []):
            func_name = func['FunctionName']
            func_arn = func['FunctionArn']
            
            print(f"\n🔍 Function: {func_name}")
            
            # 1. Check Event Source Mappings (SQS, Streams)
            mappings = client.list_event_source_mappings(FunctionName=func_name)
            for m in mappings.get('EventSourceMappings', []):
                print(f"   ↳ Triggered by Event Source: {m.get('EventSourceArn')} [Status: {m.get('State')}]")
                
            # 2. Check Resource-Based Policies (API Gateway, S3, SNS, EventBridge)
            try:
                policy = client.get_policy(FunctionName=func_name)
                print(f"   ↳ Has Resource-Based Policy (e.g., API Gateway / SNS / S3)")
            except client.exceptions.ResourceNotFoundException:
                print(f"   ↳ No direct resource-based policy found (likely invoked via SDK).")

if __name__ == "__main__":
    audit_lambda_triggers()