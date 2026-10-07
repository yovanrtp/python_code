import boto3
import zipfile
import io
import json
import os

# Define known deprecated packages in modern runtimes (Node 20 / Python 3.13)
DEPRECATED_NPMS = {"request", "node-fetch", "colors", "lodash.deepsplat"}
DEPRECATED_PYTHONS = {"urllib3<2", "distutils", "cryptography<38", "pyjwt<2"}

def audit_dependencies():
    client = boto3.client('lambda')
    paginator = client.get_paginator('list_functions')
    
    for page in paginator.paginate():
        for func in page.get('Functions', []):
            name = func['FunctionName']
            runtime = func.get('Runtime', '')
            code_res = client.get_function(FunctionName=name)
            code_url = code_res.get('Code', {}).get('Location')
            
            if not code_url:
                continue
                
            print(f"\nAnalyzing function: {name} ({runtime})")
            
            # Note: In production execution, you would stream and unzip `code_url` 
            # to parse requirements.txt or package.json. 
            # Below is the logic once the zip is extracted locally:
            
            # Example Node.js check:
            # if os.path.exists("package.json"):
            #     with open("package.json") as f:
            #         pkg = json.load(f)
            #         deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            #         for dep in deps:
            #             if dep in DEPRECATED_NPMS:
            #                 print(f"   ❌ Deprecated npm package found: {dep}")

if __name__ == "__main__":
    audit_dependencies()