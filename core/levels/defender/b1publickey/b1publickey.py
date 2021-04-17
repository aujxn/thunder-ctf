import random
import json
import os

from google.cloud import storage
from google.oauth2 import service_account
from core.framework import levels
from core.framework.cloudhelpers import deployments, iam, gcstorage, cloudfunctions

LEVEL_PATH = 'thunder/b1publickey'
RESOURCE_PREFIX = 'b1'
FUNCTION_LOCATION = 'us-central1'


def create(second_deploy=True):
    num_npc = 5
    print("Level initialization started for: " + LEVEL_PATH)
    # Create randomized nonce name to avoid namespace conflicts
    nonce = str(random.randint(100000000000, 999999999999))
    bucket_name = f'{RESOURCE_PREFIX}-bucket-{nonce}'
    bucket_name2 = f'{RESOURCE_PREFIX}-bucket2-{nonce}'
    print("Level initialization finished for: " + LEVEL_PATH)

    # Insert deployment
    config_template_args = {'nonce': nonce}
    template_files = [
        'core/framework/templates/bucket_acl.jinja',
        'core/framework/templates/service_account.jinja']
    
    if second_deploy:
        deployments.insert(LEVEL_PATH, template_files=template_files, config_template_args=config_template_args, second_deploy=True)
    else:
        deployments.insert(LEVEL_PATH, template_files=template_files,
                       config_template_args=config_template_args)
    try:
        print("Level setup started for: " + LEVEL_PATH)

        # create sa keys
        credentials = list()
        leaked_key = list()
        for i in range(0, num_npc):
            sa_key = iam.generate_service_account_key(f'{RESOURCE_PREFIX}-npc')
            credentials.append(service_account.Credentials.from_service_account_info(json.loads(sa_key)))
            if i == num_npc - 1:
                leaked_key.append(sa_key)

        # add misc data files from npc service accounts to buckets to add noise to the logs.
        index = 0
        for i in range(0, num_npc - 1):
            # use npc credentials
            storage_client = storage.client.Client(credentials=credentials[i])
            bucket = storage_client.get_bucket(bucket_name)

            for j in range(0, 6):
                data_blob = storage.Blob(f'data{index}.txt', bucket)
                data_blob.upload_from_string(str(random.randint(100000000000, 999999999999)))
                index += 1
            # switch buckets
            bucket = storage_client.get_bucket(bucket_name2)
            for j in range(0, 6):
                data_blob = storage.Blob(f'data{index}.txt', bucket)
                data_blob.upload_from_string(str(random.randint(100000000000, 999999999999)))
                index += 1

        storage_client = storage.client.Client(credentials=credentials[num_npc - 1])
        bucket = storage_client.get_bucket(bucket_name)
        secret = random.randrange(0, index - 1, 2)
        secret_blob = storage.Blob(f'data{int(secret)}.txt', bucket)


        print(f'Level creation complete for: {LEVEL_PATH}')
        start_message = (
            f'The access key in the start directory has been leaked. Find the bucket accessed through the leaked key '
            f'and the service account bound to it.')
        levels.write_start_info(
            LEVEL_PATH, start_message, file_name=f'{RESOURCE_PREFIX}-leaked.json', file_content=leaked_key[0])
        print(
            f'Instruction for the level can be accessed at thunder-ctf.cloud/thunder/{LEVEL_PATH}.html')
    except Exception as e:
        print('error')
        exit()

def destroy():
    # Delete starting files
    levels.delete_start_files()
    # Delete deployment
    deployments.delete()
