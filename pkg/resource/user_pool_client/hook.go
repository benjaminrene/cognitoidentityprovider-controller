package user_pool_client

import (
	"context"

	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider/types"

	svcapitypes "github.com/aws-controllers-k8s/cognitoidentityprovider-controller/apis/v1alpha1"
)

// EventuallyExportSecret writes the app client secret returned by the Cognito
// API into the Kubernetes Secret referenced by Spec.ExportClientSecret. The
// write is idempotent: the current value of the target Secret is read first and
// the write is skipped when it already matches. This avoids rewriting the
// Secret on every reconcile and re-exports the value when the user points
// ExportClientSecret at a different Secret.
func (rm *resourceManager) EventuallyExportSecret(
	ctx context.Context,
	ko *svcapitypes.UserPoolClient,
	userPoolClient *svcsdktypes.UserPoolClientType,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.EventuallyExportSecret")
	defer func() { exit(err) }()

	if ko.Spec.ExportClientSecret == nil || userPoolClient == nil ||
		userPoolClient.ClientSecret == nil {
		return nil
	}
	ref := ko.Spec.ExportClientSecret

	// Skip the write when the target Secret already holds the current value.
	// A read error (e.g. the Secret/key does not exist yet) falls through to
	// the write below.
	if current, rerr := rm.rr.SecretValueFromReference(ctx, ref); rerr == nil &&
		current == *userPoolClient.ClientSecret {
		return nil
	}

	namespace := ko.Namespace
	if ref.Namespace != "" {
		namespace = ref.Namespace
	}
	return rm.rr.WriteToSecret(ctx, *userPoolClient.ClientSecret, namespace, ref.Name, ref.Key)
}
