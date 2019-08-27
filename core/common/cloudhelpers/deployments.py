import random
import os
import time
import sys

import jinja2
import google.auth
from googleapiclient import discovery
from googleapiclient.errors import HttpError
from . import iam, gcstorage
from .. import levels
import yaml


def read_render_config(file_name, template_args={}):
    with open(file_name) as f:
        content = f.read()
    if not template_args == {}:
        return jinja2.Template(content).render(**template_args)
    else:
        return content


def insert(level_path, template_files=[],
           config_template_args={}, labels={}):
    # Get current credentials from environment variables and build deployment API object
    credentials, project_id = google.auth.default()
    deployment_api = discovery.build(
        'deploymentmanager', 'v2', credentials=credentials)

    level_name = os.path.basename(level_path)
    # Create request to insert deployment
    request_body = {
        "name": "thunder",
        "target": {
            "config": {
                "content": read_render_config(
                    f'core/levels/{level_path}/{level_name}.yaml',
                    template_args=config_template_args)
            },
            "imports": []
        },
        "labels": []
    }
    # Add imports to deployment json
    for template in template_files:
        request_body['target']['imports'].append(
            {"name": os.path.basename(template),
             "content": read_render_config(template)})
        # If schema is present in sibling directory to template, import it
        schema_path = f'{os.path.dirname(template)}/schema/{os.path.basename(template)}.schema'
        if os.path.exists(schema_path):
            request_body['target']['imports'].append(
                {"name": os.path.basename(template) + '.schema',
                 "content": read_render_config(schema_path)})
    # Add labels to deployment json
    for key in labels.keys():
        request_body['labels'].append({
            "key": key,
            "value": labels[key]
        })
    request_body['labels'].append({
        "key": 'level',
        "value": level_path.replace('/','-')
    })
    # Send insert request then wait for operation
    operation = deployment_api.deployments().insert(
        project=project_id, body=request_body).execute()
    op_name = operation['name']
    wait_for_operation(op_name, deployment_api,
                       project_id, level_path=level_path)


def delete(level_path, buckets=[], service_accounts=[]):
    print('Level destruction started for: ' + level_path)
    # Delete iam entries
    if not service_accounts == []:
        iam.remove_iam_entries(service_accounts)
    # Force delete buckets
    for bucket_name in buckets:
        gcstorage.delete_bucket(bucket_name)

    # Get current credentials from environment variables and build deployment API object
    credentials, project_id = google.auth.default()
    deployment_api = discovery.build(
        'deploymentmanager', 'v2', credentials=credentials)
    # Send delete request
    operation = deployment_api.deployments().delete(
        project=project_id, deployment='thunder').execute()
    op_name = operation['name']
    wait_for_operation(op_name, deployment_api, project_id)


def wait_for_operation(op_name, deployment_api, project_id, level_path=None):
    # Wait till  operation finishes, giving updates every 5 seconds
    op_done = False
    t = 0
    start_time = time.time()
    time_string = ''
    while not op_done:
        time_string = f'[{int(t/60)}m {(t%60)//10}{t%10}s]'
        sys.stdout.write(
            f'\r{time_string} Deployment operation in progress...')
        t += 5
        while t < time.time()-start_time:
            t += 5
        time.sleep(t-(time.time()-start_time))
        op_status = deployment_api.operations().get(
            project=project_id,
            operation=op_name).execute()['status']
        op_done = (op_status == 'DONE')
    sys.stdout.write(
        f'\r{time_string} Deployment operation in progress... Done\n')
    operation = op_status = deployment_api.operations().get(
        project=project_id,
        operation=op_name).execute()
    if 'error' in operation and level_path:
        print("\nDeployment Error:\n" + yaml.dump(operation['error']))
        if 'y' == input('\nDeployment error caused deployment to fail. '
                        'Would you like to destroy the deployment [y] or continue [n]? [y/n] ').lower().strip()[0]:
            level_module = levels.import_level(level_path)
            level_module.destroy()
            exit()


def get_labels():
    # Get current credentials from environment variables and build deployment API object
    credentials, project_id = google.auth.default()
    deployment_api = discovery.build(
        'deploymentmanager', 'v2', credentials=credentials)
    # Get deployment information
    try:
        deployment = deployment_api.deployments().get(
            project=project_id,
            deployment='thunder').execute()
    except HttpError:
        return None

    # Get labels as list of k/v pairs
    labels_list = deployment['labels']

    # Insert all k/v pairs into python dictionary
    labels_dict = {}
    for label in labels_list:
        labels_dict[label['key']] = label['value']
    labels_dict['level'] = labels_dict['level'].replace('-', '/')
    return labels_dict


def get_active_level():
    labels = get_labels()
    if labels:
        return labels['level']
    else:
        return None