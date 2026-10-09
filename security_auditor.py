import subprocess
import sys
import os

def run_scans():
    print("=== Starting Python-driven Security Audit (Checkov & Trivy) ===")
    
    # Target directory containing your Terraform files
    target_dir = "."
    
    # 1. Run Checkov Scan
    print("\n[1/2] Running Checkov IaC scan...")
    checkov_cmd = [
        "checkov",
        "-d", target_dir,
        "--framework", "terraform",
        "--soft-fail" # Set to False if you want it to block immediately on failure
    ]
    checkov_result = subprocess.run(checkov_cmd)
    
    # 2. Run Trivy Scan (Config misconfigurations & Secrets)
    print("\n[2/2] Running Trivy config and secret scan...")
    trivy_cmd = [
        "trivy", "fs",
        "--security-checks", "config,secret",
        "--exit-code", "1", # Fails the script if vulnerabilities are found
        target_dir
    ]
    trivy_result = subprocess.run(trivy_cmd)
    
    # Evaluate exit codes
    if trivy_result.returncode != 0:
        print("\n❌ Security Scan FAILED: Trivy detected high-risk misconfigurations or secrets.")
        sys.exit(1)
    else:
        print("\n✅ Security Scan PASSED successfully!")

if __name__ == "__main__":
    run_scans()