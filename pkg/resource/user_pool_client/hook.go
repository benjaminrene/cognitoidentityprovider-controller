package user_pool_client

import (
	"context"

	svcapitypes "github.com/aws-controllers-k8s/cognitoidentityprovider-controller/apis/v1alpha1"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider/types"
)

func (rm *resourceManager) EventuallyExportSecret(ctx context.Context, ko *svcapitypes.UserPoolClient, userPoolClient *svcsdktypes.UserPoolClientType) error {
	if ko.Spec.ExportClientSecret != nil && userPoolClient.ClientSecret != nil &&
		(ko.Status.LastModifiedDate == nil || userPoolClient.LastModifiedDate == nil || ko.Status.LastModifiedDate.Time.Equal(*userPoolClient.LastModifiedDate)) {
		namespace := ko.Namespace
		if ko.Spec.ExportClientSecret.Namespace != "" {
			namespace = ko.Spec.ExportClientSecret.Namespace
		}
		if err := rm.rr.WriteToSecret(ctx, *userPoolClient.ClientSecret, namespace, ko.Spec.ExportClientSecret.Name, ko.Spec.ExportClientSecret.Key); err != nil {
			return err
		}
	}
	return nil
}
