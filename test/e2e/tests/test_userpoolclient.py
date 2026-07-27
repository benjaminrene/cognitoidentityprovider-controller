# Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may
# not use this file except in compliance with the License. A copy of the
# License is located at
#
# 	 http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

"""Integration tests for the Cognito UserPoolClient resource."""

import logging
import time
import base64

import pytest
from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name
from kubernetes import client
from e2e import CRD_GROUP, CRD_VERSION, load_cognitoidentityprovider_resource, service_marker
from e2e.replacement_values import REPLACEMENT_VALUES

from e2e.tests.helper import CognitoValidator

RESOURCE_PLURAL = 'userpoolclients'

CREATE_WAIT_AFTER_SECONDS = 10
UPDATE_WAIT_AFTER_SECONDS = 10
DELETE_WAIT_AFTER_SECONDS = 10

# Records the Secret the client secret was last written to. The controller uses
# it to tell a target it has already exported to from one it has not.
EXPORTED_TO_ANNOTATION = 'cognitoidentityprovider.services.k8s.aws/client-secret-exported-to'

@pytest.fixture(scope='module')
def simple_userpool(cognitoidentityprovider_client):
    userpool_name = random_suffix_name("userpool", 16)
    replacements = REPLACEMENT_VALUES.copy()
    replacements['USERPOOL_NAME'] = userpool_name

    resource_data = load_cognitoidentityprovider_resource(
        'userpool_nodelete_protection',
        additional_replacements=replacements
    )
    logging.debug(resource_data)

    # Create k8s resource
    ref = k8s.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, 'userpools',
        userpool_name, namespace="default")
    k8s.create_custom_resource(ref, resource_data)

    time.sleep(CREATE_WAIT_AFTER_SECONDS)
    cr = k8s.wait_resource_consumed_by_controller(ref)

    assert cr is not None
    assert k8s.get_resource_exists(ref)

    yield (ref, cr)

    # Delete k8s resource
    if k8s.get_resource_exists(ref):
        _, deleted = k8s.delete_custom_resource(
            ref,
            DELETE_WAIT_AFTER_SECONDS,
        )
        assert deleted
    assert not k8s.get_resource_exists(ref)

@pytest.fixture(scope='module')
def user_pool_for_client(cognitoidentityprovider_client):
    """Create a UserPool via boto3 to serve as the parent for UserPoolClient tests."""
    pool_name = random_suffix_name("pool-for-client", 24)
    response = cognitoidentityprovider_client.create_user_pool(PoolName=pool_name)
    user_pool_id = response['UserPool']['Id']
    logging.info(f"Created UserPool {user_pool_id} for UserPoolClient tests")
    yield user_pool_id
    # Cleanup
    try:
        cognitoidentityprovider_client.delete_user_pool(UserPoolId=user_pool_id)
        logging.info(f"Deleted UserPool {user_pool_id}")
    except Exception as e:
        logging.warning(f"Failed to delete UserPool {user_pool_id}: {e}")

def manage_userpoolclient_resource(userpoolclient_name, resource_data):
    logging.debug(resource_data)

    # Create k8s resource
    ref = k8s.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
        userpoolclient_name, namespace="default")
    k8s.create_custom_resource(ref, resource_data)

    time.sleep(CREATE_WAIT_AFTER_SECONDS)
    cr = k8s.wait_resource_consumed_by_controller(ref)

    assert cr is not None
    assert k8s.get_resource_exists(ref)

    yield (ref, cr)

    # Delete k8s resource
    if k8s.get_resource_exists(ref):
        _, deleted = k8s.delete_custom_resource(
            ref,
            DELETE_WAIT_AFTER_SECONDS,
        )
        assert deleted
    assert not k8s.get_resource_exists(ref)

@pytest.fixture(scope='module')
def simple_userpoolclient(cognitoidentityprovider_client, user_pool_for_client):
    userpoolclient_name = random_suffix_name("userpoolclient", 24)
    user_pool_id = user_pool_for_client

    replacements = REPLACEMENT_VALUES.copy()
    replacements['USERPOOLCLIENT_NAME'] = userpoolclient_name
    replacements['USERPOOL_ID'] = user_pool_id

    resource_data = load_cognitoidentityprovider_resource(
        'userpoolclient_simple',
        additional_replacements=replacements,
    )

    for ref, cr in manage_userpoolclient_resource(userpoolclient_name, resource_data):
        yield (ref, cr, user_pool_id)

@pytest.fixture(scope='module')
def simple_userpoolclient_fromref(cognitoidentityprovider_client, simple_userpool):
    userpoolclient_name = random_suffix_name("userpoolclient", 24)
    _, userpool_cr = simple_userpool
    replacements = REPLACEMENT_VALUES.copy()
    replacements['USERPOOLCLIENT_NAME'] = userpoolclient_name
    replacements['USERPOOL_NAME'] = userpool_cr['metadata']['name']

    resource_data = load_cognitoidentityprovider_resource(
        'userpoolclient_from_ref',
        additional_replacements=replacements,
    )

    for ref, cr in manage_userpoolclient_resource(userpoolclient_name, resource_data):
        yield (ref, cr, userpool_cr['status']['id'])

@pytest.fixture(scope='module')
def simple_userpoolclient_withexport(cognitoidentityprovider_client, user_pool_for_client):
    user_pool_id = user_pool_for_client
    secret_name = random_suffix_name("userpoolclient-secret", 27)
    k8s.create_opaque_secret('default', secret_name, "key", "value")
    # Second, initially unrelated Secret, used to check that re-pointing
    # spec.exportClientSecret writes the client secret to the new target.
    alt_secret_name = random_suffix_name("userpoolclient-secret-alt", 31)
    k8s.create_opaque_secret('default', alt_secret_name, "key", "value")

    userpoolclient_name = random_suffix_name("userpoolclient", 24)
    replacements = REPLACEMENT_VALUES.copy()
    replacements['USERPOOLCLIENT_NAME'] = userpoolclient_name
    replacements['USERPOOL_ID'] = user_pool_id
    replacements['USERPOOLCLIENT_SECRET_KEY'] = 'clientSecret'
    replacements['USERPOOLCLIENT_SECRET_NAME'] = secret_name

    resource_data = load_cognitoidentityprovider_resource(
        'userpoolclient_with_export',
        additional_replacements=replacements,
    )

    for ref, cr in manage_userpoolclient_resource(userpoolclient_name, resource_data):
        yield (ref, cr, user_pool_id, secret_name, alt_secret_name)
    # Delete k8s secrets
    k8s.delete_secret('default', secret_name)
    k8s.delete_secret('default', alt_secret_name)

@pytest.fixture(scope='module')
def userpoolclient_export_without_secret(cognitoidentityprovider_client, user_pool_for_client):
    """An app client asking for an export but created without generateSecret."""
    user_pool_id = user_pool_for_client
    secret_name = random_suffix_name("userpoolclient-nosecret", 29)
    k8s.create_opaque_secret('default', secret_name, "key", "value")

    userpoolclient_name = random_suffix_name("userpoolclient", 24)
    replacements = REPLACEMENT_VALUES.copy()
    replacements['USERPOOLCLIENT_NAME'] = userpoolclient_name
    replacements['USERPOOL_ID'] = user_pool_id
    replacements['USERPOOLCLIENT_SECRET_KEY'] = 'clientSecret'
    replacements['USERPOOLCLIENT_SECRET_NAME'] = secret_name

    resource_data = load_cognitoidentityprovider_resource(
        'userpoolclient_export_without_secret',
        additional_replacements=replacements,
    )

    for ref, cr in manage_userpoolclient_resource(userpoolclient_name, resource_data):
        yield (ref, cr, secret_name)
    k8s.delete_secret('default', secret_name)

@service_marker
@pytest.mark.canary
class TestUserPoolClient():
    def test_create_delete_simple_userpoolclient(
        self, simple_userpoolclient, cognitoidentityprovider_client
    ):
        (ref, cr, user_pool_id) = simple_userpoolclient
        assert cr is not None
        assert 'spec' in cr
        assert 'name' in cr['spec']
        assert 'userPoolID' in cr['spec']
        assert cr['spec']['userPoolID'] == user_pool_id

        assert 'status' in cr
        assert 'id' in cr['status']
        client_id = cr['status']['id']

        # Verify the resource exists in AWS
        validator = CognitoValidator(cognitoidentityprovider_client)
        assert validator.user_pool_client_exists(user_pool_id, client_id)

        # Verify explicit auth flows were set correctly
        aws_client = validator.get_user_pool_client(user_pool_id, client_id)
        assert 'ALLOW_USER_SRP_AUTH' in aws_client['ExplicitAuthFlows']
        assert 'ALLOW_REFRESH_TOKEN_AUTH' in aws_client['ExplicitAuthFlows']

        # Update: add callback URLs
        updates = {
            'spec': {
                'callbackURLs': [
                    'https://example.com/callback',
                ],
                'allowedOAuthFlowsUserPoolClient': True,
                'allowedOAuthFlows': ['code'],
                'allowedOAuthScopes': ['openid'],
            }
        }
        k8s.patch_custom_resource(ref, updates)
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)

        # Verify update in AWS
        aws_client = validator.get_user_pool_client(user_pool_id, client_id)
        assert 'https://example.com/callback' in aws_client['CallbackURLs']
        assert aws_client['AllowedOAuthFlowsUserPoolClient'] is True
        assert 'code' in aws_client['AllowedOAuthFlows']
        assert 'openid' in aws_client['AllowedOAuthScopes']

        # Delete
        _, deleted = k8s.delete_custom_resource(
            ref,
            DELETE_WAIT_AFTER_SECONDS,
        )
        assert deleted

        assert not validator.user_pool_client_exists(user_pool_id, client_id)

    def test_create_delete_simple_userpoolclient_fromref(
        self, simple_userpoolclient_fromref, cognitoidentityprovider_client
    ):
        (ref, cr, user_pool_id) = simple_userpoolclient_fromref
        assert cr is not None
        assert 'spec' in cr
        assert 'name' in cr['spec']
        assert 'userPoolRef' in cr['spec']
        assert cr['spec']['userPoolRef']['from']['name'] is not None

        assert 'status' in cr
        assert 'id' in cr['status']
        client_id = cr['status']['id']

        # Verify the resource exists in AWS
        validator = CognitoValidator(cognitoidentityprovider_client)
        assert validator.user_pool_client_exists(user_pool_id, client_id)

        # Delete
        _, deleted = k8s.delete_custom_resource(
            ref,
            DELETE_WAIT_AFTER_SECONDS,
        )
        assert deleted

        assert not validator.user_pool_client_exists(user_pool_id, client_id)

    def test_create_delete_simple_userpoolclient_withexport(
        self, simple_userpoolclient_withexport, cognitoidentityprovider_client
    ):
        (ref, cr, user_pool_id, secret_name, alt_secret_name) = simple_userpoolclient_withexport
        assert cr is not None
        assert 'spec' in cr
        assert 'name' in cr['spec']
        assert 'userPoolID' in cr['spec']
        assert cr['spec']['userPoolID'] == user_pool_id

        assert 'status' in cr
        assert 'id' in cr['status']
        client_id = cr['status']['id']

        # Verify the resource exists in AWS
        validator = CognitoValidator(cognitoidentityprovider_client)
        assert validator.user_pool_client_exists(user_pool_id, client_id)

        # Verify explicit auth flows were set correctly
        aws_client = validator.get_user_pool_client(user_pool_id, client_id)
        assert 'ALLOW_USER_SRP_AUTH' in aws_client['ExplicitAuthFlows']
        assert 'ALLOW_REFRESH_TOKEN_AUTH' in aws_client['ExplicitAuthFlows']

        core_api = client.CoreV1Api(k8s._get_k8s_api_client())
        custom_api = client.CustomObjectsApi(k8s._get_k8s_api_client())
        cr_name = cr['metadata']['name']

        def read_exported_key(name):
            secret = core_api.read_namespaced_secret(name, 'default')
            if secret.data is None or 'clientSecret' not in secret.data:
                return None
            return base64.b64decode(secret.data['clientSecret']).decode('utf-8')

        def read_export_annotation():
            latest = custom_api.get_namespaced_custom_object(
                CRD_GROUP, CRD_VERSION, 'default', RESOURCE_PLURAL, cr_name,
            )
            return latest['metadata'].get('annotations', {}).get(EXPORTED_TO_ANNOTATION)

        client_secret = validator.get_user_pool_client(user_pool_id, client_id)['ClientSecret']

        # Creating the app client exports its secret, and records where it went.
        assert read_exported_key(secret_name) == client_secret
        assert read_export_annotation() == f'default/{secret_name}/clientSecret'

        # Steady state: the controller does not own the Secret, so once the key
        # holds a value it leaves it alone. Overwrite the key and confirm it is
        # not reverted while nothing about the export target has changed.
        sentinel = base64.b64encode(b'sentinel').decode('utf-8')
        core_api.patch_namespaced_secret(secret_name, 'default', {'data': {'clientSecret': sentinel}})
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)
        assert read_exported_key(secret_name) == 'sentinel'

        # A missing key is refilled on the next reconcile, which covers the
        # Secret being deleted and recreated or the key being dropped, without
        # the controller having to rewrite it every time.
        #
        # The controller watches its own resources with a GenerationChanged
        # predicate and never watches Secrets, so editing the Secret triggers
        # nothing on its own: the reconcile has to be provoked with a spec
        # change here rather than waited for, since the resync period is 10
        # hours by default.
        core_api.patch_namespaced_secret(secret_name, 'default', {'data': {'clientSecret': None}})
        assert read_exported_key(secret_name) is None
        k8s.patch_custom_resource(ref, {'spec': {'authSessionValidity': 5}})
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)
        assert read_exported_key(secret_name) == client_secret

        # Re-pointing spec.exportClientSecret writes the client secret to the new
        # Secret and moves the recorded target with it. The reference has no AWS
        # counterpart, so this is driven by the synthetic delta rather than by any
        # difference the generated comparison could observe.
        assert read_exported_key(alt_secret_name) is None
        k8s.patch_custom_resource(ref, {
            'spec': {
                'exportClientSecret': {
                    'name': alt_secret_name,
                    'key': 'clientSecret',
                },
            },
        })
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)
        assert read_exported_key(alt_secret_name) == client_secret
        assert read_export_annotation() == f'default/{alt_secret_name}/clientSecret'

        # The former target is left as it was: the controller does not clean up a
        # Secret it no longer references.
        assert read_exported_key(secret_name) == client_secret

        # Re-pointing at a target that already holds a value still replaces it,
        # because that value was not written for this resource.
        core_api.patch_namespaced_secret(secret_name, 'default', {'data': {'clientSecret': sentinel}})
        k8s.patch_custom_resource(ref, {
            'spec': {
                'exportClientSecret': {
                    'name': secret_name,
                    'key': 'clientSecret',
                },
            },
        })
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)
        assert read_exported_key(secret_name) == client_secret
        assert read_export_annotation() == f'default/{secret_name}/clientSecret'

        # Delete
        _, deleted = k8s.delete_custom_resource(
            ref,
            DELETE_WAIT_AFTER_SECONDS,
        )
        assert deleted

        assert not validator.user_pool_client_exists(user_pool_id, client_id)

    def test_export_without_generate_secret_is_terminal(
        self, userpoolclient_export_without_secret
    ):
        """An export that can never succeed must say so instead of looking synced.

        generateSecret is immutable, so an app client created without one will
        never have a secret to export. Reconciling cannot fix it, and the
        resource must not keep reporting itself as synced while the target
        Secret stays empty.
        """
        (ref, cr, secret_name) = userpoolclient_export_without_secret
        core_api = client.CoreV1Api(k8s._get_k8s_api_client())
        custom_api = client.CustomObjectsApi(k8s._get_k8s_api_client())
        cr_name = cr['metadata']['name']

        def read_condition(cond_type):
            latest = custom_api.get_namespaced_custom_object(
                CRD_GROUP, CRD_VERSION, 'default', RESOURCE_PLURAL, cr_name,
            )
            for cond in latest.get('status', {}).get('conditions', []):
                if cond['type'] == cond_type:
                    return cond
            return None

        terminal = read_condition('ACK.Terminal')
        assert terminal is not None
        assert terminal['status'] == 'True'
        assert 'generateSecret' in terminal['message']

        # Nothing was written to the target Secret.
        secret = core_api.read_namespaced_secret(secret_name, 'default')
        assert 'clientSecret' not in (secret.data or {})

        # Dropping the export request clears the terminal condition: the app
        # client itself is fine, only the export was impossible.
        k8s.patch_custom_resource(ref, {'spec': {'exportClientSecret': None}})
        time.sleep(UPDATE_WAIT_AFTER_SECONDS)

        terminal = read_condition('ACK.Terminal')
        assert terminal is None or terminal['status'] == 'False'

