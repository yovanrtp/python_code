#!/usr/bin/env python3
import boto3
import json

iam = boto3.client('iam')

def audit_admin_roles():
    paginator = iam.get_paginator('list_roles')
    print("Scanning IAM roles for administrative or wildcard permissions...")
    
    for page in paginator.paginate():
        for role in page['Roles']:
            role_name = role['RoleName']
            role_arn = role['Arn']
            
            # Check attached managed policies
            attached_policies = iam.list_attached_role_policies(RoleName=role_name)
            for policy in attached_policies.get('AttachedPolicies', []):
                if policy['PolicyName'] in ['AdministratorAccess', 'PowerUserAccess']:
                    print(f"⚠️ [Managed Policy] Role '{role_name}' has '{policy['PolicyName']}' attached.")
                    
            # Check inline policies
            inline_policies = iam.list_role_policies(RoleName=role_name)
            for policy_name in inline_policies.get('PolicyNames', []):
                policy_doc = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
                doc_str = json.dumps(policy_doc.get('PolicyDocument', {}))
                if '"Action": "*"' in doc_str and '"Resource": "*"' in doc_str:
                    print(f"🚨 [Inline Policy] Role '{role_name}' has full wildcard admin policy '{policy_name}'.")

if __name__ == "__main__":
    audit_admin_roles()