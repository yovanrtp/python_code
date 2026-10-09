import boto3

def audit_aws_security():
    violations = []
    
    # --- 1. IAM AUDIT (Unused credentials) ---
    iam = boto3.client('iam')
    users = iam.list_users()['Users']
    for user in users:
        summary = iam.get_login_profile(UserName=user['UserName']) if 'PasswordLastUsed' in user else None
        # Add your business logic/threshold check here...

    # --- 2. KMS AUDIT (Unrotated Keys) ---
    kms = boto3.client('kms')
    keys = kms.list_keys()['Keys']
    for key in keys:
        key_id = key['KeyId']
        rotation = kms.get_key_rotation_status(KeyId=key_id)
        if not rotation['KeyRotationEnabled']:
            violations.append(f"KMS Key {key_id} does not have rotation enabled.")

    # --- 3. SECRETS MANAGER AUDIT (Unrotated Secrets) ---
    secrets = boto3.client('secretsmanager')
    secret_list = secrets.list_secrets()['SecretList']
    for secret in secret_list:
        if not secret.get('RotationEnabled', False):
            violations.append(f"Secret {secret['Name']} has no rotation enabled.")

    # Fail pipeline if violations found
    if violations:
        print("SECURITY AUDIT FAILED:")
        for v in violations:
            print(f" - {v}")
        exit(1)
    else:
        print("Security audit passed with zero violations!")

if __name__ == "__main__":
    audit_aws_security()