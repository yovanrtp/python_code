#!/usr/bin/env python3
import boto3
import urllib.request
import zipfile
import io
import json
import os

# Define known deprecated or legacy packages for modern runtimes
DEPRECATED_NPMS = {
    "request",           # Fully deprecated, use native fetch or axios
    "node-fetch",        # Older versions incompatible with Node 20 global fetch
    "uuidv4",            # Deprecated wrapper, use official 'uuid'
    "babel",             # Outdated build tools
    "colors",            # Vulnerability history
    "jade"               # Renamed to pug
}

DEPRECATED_PYTHONS = {
    "distutils",         # Removed in Python 3.12+
    "urllib3<2.0",       # Outdated versions with security warnings
    "cryptography<38",   # Incompatible with modern OpenSSL on Python 3.12/3.13
    "pyjwt<2.0",         # Outdated syntax
    "setuptools<60",     # Legacy packaging
    "aiofiles"           # Check compatibility with Python 3.13 async updates
}

def analyze_zip_contents(zip_bytes, func_name, runtime):
    print(f"\n📦 Analyzing function: [{func_name}] (Runtime: {runtime})")
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            file_list = z.namelist()
            
            # 1. Check for Node.js package.json
            if "package.json" in file_list:
                print("   Found package.json (Node.js)")
                with z.open("package.json") as f:
                    pkg_data = json.loads(f.read().decode('utf-8'))
                    dependencies = {
                        **pkg_data.get("dependencies", {}), 
                        **pkg_data.get("devDependencies", {})
                    }
                    for dep, version in dependencies.items():
                        if dep.lower() in DEPRECATED_NPMS:
                            print(f"      ❌ [Deprecated npm]: {dep} ({version})")
                        else:
                            print(f"      ✔ [npm]: {dep} ({version})")
                            
            # 2. Check for Python requirements.txt or setup.py
            req_files = [f for f in file_list if f.endswith("requirements.txt") or f == "setup.py" or f == "pyproject.toml"]
            for req_file in req_files:
                print(f"   Found dependency file: {req_file}")
                with z.open(req_file) as f:
                    content = f.read().decode('utf-8', errors='ignore')
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].strip()
                            if pkg_name.lower() in DEPRECATED_PYTHONS:
                                print(f"      ❌ [Deprecated pip]: {line}")
                            else:
                                print(f"      ✔ [pip]: {line}")
                                
            # Check if Lambda uses Layers (Layers contain external dependencies)
            # Note: Layers are listed in function configuration, not the deployment zip.
            
    except zipfile.BadZipFile:
        print("   ⚠️ Error: Could not parse function zip package (might be stored in a container image).")

def audit_all_lambdas(region="us-east-1"):
    client = boto3.client('lambda', region_name=region)
    paginator = client.get_paginator('list_functions')
    
    print(f"Starting dependency audit across region: {region}...")
    
    for page in paginator.paginate():
        for func in page.get('Functions', []):
            func_name = func['FunctionName']
            runtime = func.get('Runtime', 'Unknown')
            
            # Check if it's a container image deployment
            if func.get('PackageType') == 'Image':
                print(f"\n📦 Analyzing function: [{func_name}] uses Container Image (Skipping zip inspection).")
                continue
                
            # Get signed code download URL
            try:
                code_res = client.get_function(FunctionName=func_name)
                code_url = code_res.get('Code', {}).get('Location')
                
                if code_url:
                    # Download zip file into memory
                    with urllib.request.urlopen(code_url) as response:
                        zip_bytes = response.read()
                        analyze_zip_contents(zip_bytes, func_name, runtime)
            except Exception as e:
                print(f"   ⚠️ Could not fetch code for {func_name}: {str(e)}")

if __name__ == "__main__":
    region = os.environ.get("AWS_REGION", "us-east-1")
    audit_all_lambdas(region)