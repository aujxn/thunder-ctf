import random
import os
import subprocess
import time
import json
import csv
import sqlalchemy
import google.auth

from googleapiclient import discovery
from sqlalchemy.sql import text
from google.oauth2 import service_account
from core.framework import levels
from google.cloud import storage
from core.framework.cloudhelpers import (
    deployments,
    iam,
    gcstorage,
    cloudfunctions
)

LEVEL_PATH = 'defender/audit'
FUNCTION_LOCATION = 'us-central1'

def create(second_deploy=True):
    print("Level initialization started for: " + LEVEL_PATH)
    nonce = str(random.randint(100000000000, 999999999999))

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
    logging_key = iam.generate_service_account_key('log-viewer')
    storage_client = storage.Client()
    vm_image_bucket = storage_client.get_bucket(f'vm-image-bucket-{nonce}')
    storage_blob = storage.Blob('main.py', vm_image_bucket)
    storage_blob.upload_from_filename(f'core/levels/{LEVEL_PATH}/resources/api-engine/main.py')


    print(f'Level creation complete for: {LEVEL_PATH}')
    start_message = ('Helpful start message')

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


def destroy():
    deployments.delete()
