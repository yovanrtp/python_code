import boto3
import json

def get_env_vars_and_secrets():
    client = boto3.client('lambda')
    paginator = client.get_paginator('list_functions')
    
    print(f"{'Function Name':<35} | {'Runtime':<15} | {'Environment Variables / Secrets'}")
    print("-" * 90)
    
    for page in paginator.paginate():
        for func in page.get('Functions', []):
            name = func['FunctionName']
            runtime = func.get('Runtime', 'Unknown')
            env_vars = func.get('Environment', {}).get('Variables', {})
            
            # Identify potential secrets or database URLs based on key names
            secret_keys = {k: v for k, v in env_vars.items() if any(sub in k.lower() for sub in ['pass', 'secret', 'key', 'token', 'db_', 'url'])}
            
            print(f"{name:<35} | {runtime:<15} | {json.dumps(env_vars)}")

if __name__ == "__main__":
    get_env_vars_and_secrets()