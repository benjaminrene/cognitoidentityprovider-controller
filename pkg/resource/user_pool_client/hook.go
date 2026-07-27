package user_pool_client

import (
	"context"
	"errors"
	"fmt"

	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	ackerr "github.com/aws-controllers-k8s/runtime/pkg/errors"
	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider/types"

	svcapitypes "github.com/aws-controllers-k8s/cognitoidentityprovider-controller/apis/v1alpha1"
)

// AnnotationExportedTo records the Secret the app client secret was last
// written to, as "<namespace>/<name>/<key>".
//
// Spec.ExportClientSecret has no counterpart in the Cognito API, so sdkFind
// cannot observe where the secret was previously exported: it builds the latest
// resource from a DeepCopy of the desired one, which makes the reference always
// compare equal to itself. This annotation is the only record of what was
// actually written, and is what lets the controller notice that the reference
// was re-pointed at a different Secret, or that the resource was adopted and
// never exported at all.
const AnnotationExportedTo = "cognitoidentityprovider.services.k8s.aws/client-secret-exported-to"

// exportTarget returns the namespace, name and key of the Secret the client
// secret is to be written to, resolving the namespace fallback.
func exportTarget(ko *svcapitypes.UserPoolClient) (namespace string, name string, key string) {
	ref := ko.Spec.ExportClientSecret
	if ref == nil {
		return "", "", ""
	}
	namespace = ko.Namespace
	if ref.Namespace != "" {
		namespace = ref.Namespace
	}
	return namespace, ref.Name, ref.Key
}

// exportTargetID identifies the Secret currently declared on the resource, in
// the form recorded by AnnotationExportedTo.
func exportTargetID(ko *svcapitypes.UserPoolClient) string {
	if ko.Spec.ExportClientSecret == nil {
		return ""
	}
	namespace, name, key := exportTarget(ko)
	return fmt.Sprintf("%s/%s/%s", namespace, name, key)
}

// exportedTargetID returns the Secret the client secret was last written to, or
// the empty string if it never was.
func exportedTargetID(ko *svcapitypes.UserPoolClient) string {
	return ko.Annotations[AnnotationExportedTo]
}

// exportTargetMoved reports whether the Secret declared on the resource is not
// the one the client secret was last written to, which is the case when the
// reference has just been re-pointed, or when the resource was adopted and the
// controller has never exported anything for it.
func exportTargetMoved(ko *svcapitypes.UserPoolClient) bool {
	return ko.Spec.ExportClientSecret != nil &&
		exportedTargetID(ko) != exportTargetID(ko)
}

// recordExportTarget stamps the Secret that was just written on the resource.
// It is only ever called after a successful write, so the annotation never
// claims an export that did not happen.
func recordExportTarget(ko *svcapitypes.UserPoolClient) {
	target := exportTargetID(ko)
	if target == "" {
		return
	}
	if ko.Annotations == nil {
		ko.Annotations = map[string]string{}
	}
	ko.Annotations[AnnotationExportedTo] = target
}

// carryExportTarget copies the export target recorded on src onto dst.
//
// The runtime patches CR metadata on the create and update paths only, never
// after a plain sdkFind. On the update path the annotation therefore has to be
// carried from the observed resource onto the one sdkUpdate returns, or it
// never reaches etcd.
func carryExportTarget(dst *svcapitypes.UserPoolClient, src *svcapitypes.UserPoolClient) {
	exported := exportedTargetID(src)
	if exported == "" {
		return
	}
	if dst.Annotations == nil {
		dst.Annotations = map[string]string{}
	}
	dst.Annotations[AnnotationExportedTo] = exported
}

// compareExportClientSecret injects a synthetic Spec difference when the client
// secret was exported somewhere other than the Secret currently declared on the
// resource.
//
// The generated comparison of Spec.ExportClientSecret is disabled
// (compare.is_ignored in generator.yaml) because it can never fire: the field
// has no AWS counterpart, so sdkFind copies it verbatim from desired into
// latest. Comparing the declared target against the one recorded by
// AnnotationExportedTo is what actually detects a re-pointed reference or an
// adopted resource, and reaching sdkUpdate is what gets the annotation
// persisted.
func compareExportClientSecret(
	delta *ackcompare.Delta,
	a *resource,
	b *resource,
) {
	if !exportTargetMoved(a.ko) {
		return
	}
	delta.Add(
		"Spec.ExportClientSecret",
		exportedTargetID(a.ko),
		exportTargetID(a.ko),
	)
}

// exportClientSecret writes the app client secret returned by Cognito into the
// Secret referenced by Spec.ExportClientSecret, and records where it wrote.
//
// force selects between the two regimes:
//
//   - force is true on sdkCreate, and on sdkFind when the target moved: the app
//     client was just created, adopted, or re-pointed at a Secret that was never
//     written to, so whatever that key currently holds did not come from this
//     resource and has to be replaced.
//
//   - force is false in steady state: the key is only filled when it is missing
//     or empty. The controller does not own the Secret -- it never creates it,
//     holds no ownerReference on it, and the key may be shared -- so it must not
//     fight another writer on every reconcile. A deleted key or a recreated
//     Secret is refilled on the next reconcile; the controller does not watch
//     Secrets, so that happens on the next spec change or resync, not when the
//     Secret is edited.
//
// Cognito never rotates the secret of an existing app client, and the
// multi-secret operations are absent from the pinned SDK, so there is no
// upstream drift for the steady-state regime to miss.
func (rm *resourceManager) exportClientSecret(
	ctx context.Context,
	ko *svcapitypes.UserPoolClient,
	userPoolClient *svcsdktypes.UserPoolClientType,
	force bool,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.exportClientSecret")
	defer func() { exit(err) }()

	ref := ko.Spec.ExportClientSecret
	if ref == nil {
		return nil
	}
	if userPoolClient == nil {
		return nil
	}
	if userPoolClient.ClientSecret == nil {
		// The app client has no secret, which means it was created without
		// GenerateSecret. That field is immutable, so no amount of reconciling
		// will ever produce a secret to export: report it as terminal rather
		// than let the resource keep claiming it is synced while the target
		// Secret stays empty. Removing spec.exportClientSecret clears it.
		//
		// The condition is on the API response rather than on
		// Spec.GenerateSecret so that an app client adopted from outside ACK,
		// whose spec field may be unset, still exports the secret Cognito does
		// return for it.
		return ackerr.NewTerminalError(errors.New(
			"cannot export the client secret: this app client does not have " +
				"one. spec.generateSecret must be set at creation time and is " +
				"immutable; recreate the app client, or remove " +
				"spec.exportClientSecret",
		))
	}

	// Resolving the reference is also what runs the runtime's cross-namespace
	// validation, which WriteToSecret does not perform. Doing it on every path,
	// including the forced ones where the value read is discarded, keeps a
	// cross-namespace export from slipping past that guard.
	current, err := rm.rr.SecretValueFromReference(ctx, ref)
	switch {
	case err == nil:
		if !force && current != "" {
			return nil
		}
	case errors.Is(err, ackerr.SecretNotFound):
		// The runtime returns this same sentinel whether the Secret itself is
		// missing or it exists without our key, so it cannot tell the two apart.
		// Both mean the key needs writing: fall through, and let WriteToSecret
		// report the real error if it is the Secret that is gone.
		err = nil
	default:
		// Terminal cross-namespace rejection, non-Opaque Secret, ... none of
		// which WriteToSecret re-checks, so none of which may be swallowed.
		return err
	}

	namespace, name, key := exportTarget(ko)
	if err = rm.rr.WriteToSecret(
		ctx, *userPoolClient.ClientSecret, namespace, name, key,
	); err != nil {
		return err
	}
	recordExportTarget(ko)
	return nil
}
