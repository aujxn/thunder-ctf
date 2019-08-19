import random
import os

from google.cloud import storage
from ...common.python import secrets, levels
from ...common.python.cloudhelpers import deployments, iam, gcstorage, cloudfunctions

LEVEL_NAME = 'a3password'
RESOURCE_PREFIX = 'a3'
FUNCTION_LOCATION = 'us-central1'


def create():
    print("Level initialization started for: " + LEVEL_NAME)
    # Create randomized nonce name to avoid namespace conflicts
    nonce = str(random.randint(100000000000, 999999999999))
    bucket_name = f'{RESOURCE_PREFIX}-bucket-{nonce}'
    # Create random function password
    func_xor_password = str(random.randint(100000000000, 999999999999))
    xor_factor = str(random.randint(100000000000, 999999999999))
    func_template_args = {'bucket_name': bucket_name,
                       'xor_factor': xor_factor}
    # Upload function and get upload url
    func_upload_url = cloudfunctions.upload_cloud_function(
        f'core/levels/{LEVEL_NAME}/function', FUNCTION_LOCATION, template_args=func_template_args)
    print("Level initialization finished for: " + LEVEL_NAME)

    # Insert deployment
    config_template_args = {'nonce': nonce,
                         'func_xor_password': func_xor_password,
                         'func_upload_url': func_upload_url}
    labels = {'nonce': nonce}
    template_files = [
        'core/common/templates/bucket_acl.jinja',
        'core/common/templates/cloud_function.jinja',
        'core/common/templates/service_account.jinja',
        'core/common/templates/iam_policy.jinja']
    deployments.insert(LEVEL_NAME, template_files=template_files,
                       config_template_args=config_template_args, labels=labels)

    print("Level setup started for: " + LEVEL_NAME)
    # Insert secret into bucket

    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)
    secret_blob = storage.Blob('secret.txt', bucket)
    secret = secrets.make_secret(LEVEL_NAME)
    secret_blob.upload_from_string(secret)

    # Create service account key file
    sa_key = iam.generate_service_account_key(f'{RESOURCE_PREFIX}-access')
    print(f'Level creation complete for: {LEVEL_NAME}')
    start_message = (
        f'Use the given compromised credentials to find the secret hidden in the level.')
    levels.write_start_info(
        LEVEL_NAME, start_message, file_name=f'{RESOURCE_PREFIX}-access.json', file_content=sa_key)
    print(
        f'Instruction for the level can be accessed at thunder-ctf.cloud/levels/{LEVEL_NAME}.html')


def destroy():
    print('Level tear-down started for: ' + LEVEL_NAME)
    # Delete starting files
    levels.delete_start_files(
        LEVEL_NAME, files=[f'{RESOURCE_PREFIX}-access.json'])
    print('Level tear-down finished for: ' + LEVEL_NAME)

    # Find bucket name from deployment label
    nonce = deployments.get_labels(LEVEL_NAME)['nonce']
    bucket_name = f'{RESOURCE_PREFIX}-bucket-{nonce}'

    service_accounts = [
        iam.service_account_email(f'{RESOURCE_PREFIX}-access')
    ]
    # Delete deployment
    deployments.delete(LEVEL_NAME,
                       buckets=[bucket_name],
                       service_accounts=service_accounts)
