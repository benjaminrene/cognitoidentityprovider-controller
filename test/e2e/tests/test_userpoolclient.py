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

import pytest
from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name
from e2e import CRD_GROUP, CRD_VERSION, load_cognitoidentityprovider_resource, service_marker
from e2e.replacement_values import REPLACEMENT_VALUES

from e2e.tests.helper import CognitoValidator

RESOURCE_PLURAL = 'userpoolclients'

CREATE_WAIT_AFTER_SECONDS = 10
UPDATE_WAIT_AFTER_SECONDS = 10
DELETE_WAIT_AFTER_SECONDS = 10

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
        assert 'clientID' in cr['status']
        client_id = cr['status']['clientID']

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
        assert 'clientID' in cr['status']
        client_id = cr['status']['clientID']

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
