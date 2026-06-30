package user_pool_client

import (
	"context"

	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider/types"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	svcapitypes "github.com/aws-controllers-k8s/cognitoidentityprovider-controller/apis/v1alpha1"
)

// EventuallyExportSecret writes the app client secret returned by the Cognito
// API into the Kubernetes Secret referenced by Spec.ExportClientSecret.
//
// The write is event-driven so that sdkFind does not rewrite the Secret (or
// touch the Kubernetes API) on every reconcile. lastObservedModifiedDate is the
// LastModifiedDate we recorded for the app client the previous time we observed
// it; userPoolClient.LastModifiedDate is the value just returned by AWS. We
// only (re)export when:
//
//   - lastObservedModifiedDate is nil — we have no prior observation, i.e. the
//     client was just created, adopted, or the controller restarted, so we must
//     export to be safe; or
//   - the AWS LastModifiedDate differs from what we last observed — the app
//     client was mutated in AWS, so the exported value may be stale.
//
// In steady state the two timestamps match and the call is a no-op.
func (rm *resourceManager) EventuallyExportSecret(
	ctx context.Context,
	ko *svcapitypes.UserPoolClient,
	userPoolClient *svcsdktypes.UserPoolClientType,
	lastObservedModifiedDate *metav1.Time,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.EventuallyExportSecret")
	defer func() { exit(err) }()

	if ko.Spec.ExportClientSecret == nil || userPoolClient == nil ||
		userPoolClient.ClientSecret == nil {
		return nil
	}

	// Skip the write when the app client has not been (re)created or mutated in
	// AWS since we last observed it. A nil lastObservedModifiedDate falls through
	// to the write below.
	if lastObservedModifiedDate != nil && userPoolClient.LastModifiedDate != nil &&
		lastObservedModifiedDate.Time.Equal(*userPoolClient.LastModifiedDate) {
		return nil
	}

	ref := ko.Spec.ExportClientSecret
	namespace := ko.Namespace
	if ref.Namespace != "" {
		namespace = ref.Namespace
	}
	return rm.rr.WriteToSecret(ctx, *userPoolClient.ClientSecret, namespace, ref.Name, ref.Key)
}
