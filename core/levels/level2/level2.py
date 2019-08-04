import random
import os
import subprocess
import shutil

from google.cloud import storage, logging as glogging

from ...common.python import deployments, secrets, keys, cloudresources, levels

LEVEL_NAME = 'level2'

LOG_NAME = 'transactions'


def create():
    print("Level initialization started for: " + LEVEL_NAME)
    # Create randomized nonce name to avoid namespace conflicts
    nonce = str(random.randint(100000000000, 999999999999))
    bucket_name = f'level2-bucket-{nonce}'

    # Create ssh key
    ssh_private_key, ssh_public_key = keys.generate_ssh_key()
    ssh_username = "clouduser"

    try:
        # Construct git repo
        repo_path = os.path.dirname(os.getcwd()) + "/temp-repository-" + nonce
        create_repo_files(repo_path, ssh_private_key)
        print("Level initialization finished for: " + LEVEL_NAME)

        # Insert deployment
        config_properties = {'nonce': nonce,
                             'ssh_public_key': ssh_public_key,
                             'ssh_username': ssh_username}
        labels = {'nonce': nonce}
        deployments.insert(LEVEL_NAME,
                           template_files=[
                               'common/templates/bucket_acl.jinja',
                               'common/templates/instance.jinja',
                               'common/templates/service_account.jinja',
                               'common/templates/iam_policy.jinja'],
                           config_properties=config_properties, labels=labels)

        print("Level setup started for: " + LEVEL_NAME)
        # Upload repository to bucket
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(bucket_name)
        cloudresources.upload_directory_recursive(repo_path, repo_path, bucket)

        # Create logs
        create_logs()

        # Create service account key file
        sa_key = keys.generate_service_account_key('level2-access')
        levels.write_start_file('level2-access.json', sa_key)

        print(f'Level creation complete for: {LEVEL_NAME}\n'
              f'Instruction for the level can be accessed at thunder-ctf.cloud/levels/{LEVEL_NAME}')
    finally:
        # If there is an error, make sure to delete the temporary repository before exiting
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)


def create_repo_files(repo_path, ssh_private_key):
    cwd = os.getcwd()
    os.makedirs(repo_path + '/function')
    os.chdir(repo_path)
    # Make dummy cloud function files
    with open(repo_path+'/function/requirements.txt', 'w+') as f:
        f.write('')
    with open(repo_path+'/function/main.py', 'w+') as f:
        f.write('')
    # Add ssh key file
    with open(repo_path+'/ssh_key', 'w+') as f:
        f.write(ssh_private_key)
    os.chmod('ssh_key', 0o700)
    # Add files in first commit, then delete key in second
    subprocess.call(['git', 'init', '--q'])
    p = subprocess.Popen(['git', 'add', '*'])
    p.communicate()
    subprocess.call(['git', 'commit', '-q', '-m', 'added initial files', ])
    os.remove('ssh_key')
    p = subprocess.Popen(['git', 'add', '*'])
    p.communicate()
    subprocess.call(
        ['git', 'commit', '-q', '-m', 'Oops. Deleted accidental key upload'])
    # Reset working directory
    os.chdir(cwd)


def create_logs():
    logger = glogging.Client().logger(LOG_NAME)
    with open('core/levels/level2/first-names.txt') as f:
        first_names = f.read().split('\n')
    with open('core/levels/level2/last-names.txt') as f:
        last_names = f.read().split('\n')
    name_secret = (first_names[random.randint(0, 199)] +
                   last_names[random.randint(0, 299)])
    secret_position = random.randint(0, 99)
    for i in range(0, 100):
        if i == secret_position:
            logger.log_struct(
                {'name': name_secret,
                 'transaction-total': f'${random.randint(1,150)}.{random.randint(1,99)}',
                 'credit-card-number': secrets.make_secret(LEVEL_NAME, 16)})
        else:
            name = (first_names[random.randint(0, 199)] +
                    last_names[random.randint(0, 299)])
            if not name == name_secret:
                logger.log_struct(
                    {'name': name,
                     'transaction-total': f'${random.randint(1,150)}.{random.randint(1,99)}',
                     'credit-card-number': str(random.randint(1000000000000000, 9999999999999999))})


def destroy():
    print('Level tear-down started for: ' + LEVEL_NAME)
    # Delete logs
    client = glogging.Client()
    if len([entry for entry in client.list_entries(filter_=f'logName:{LOG_NAME}')]) > 0:
        logger = client.logger(LOG_NAME)
        logger.delete()

    # Delete starting key file
    levels.delete_start_file('level2-access.json')
    # Find bucket name from deployment label
    nonce = deployments.get_labels(LEVEL_NAME)['nonce']
    bucket_name = f'{LEVEL_NAME}-bucket-{nonce}'
    print('Level tear-down finished for: ' + LEVEL_NAME)
    # Delete deployment
    deployments.delete(LEVEL_NAME,
                       buckets=[bucket_name],
                       service_accounts=['level2-access', 'level2-logging-instance-sa'])
