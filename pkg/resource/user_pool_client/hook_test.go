package user_pool_client

import (
	"testing"

	ackv1alpha1 "github.com/aws-controllers-k8s/runtime/apis/core/v1alpha1"
	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	svcapitypes "github.com/aws-controllers-k8s/cognitoidentityprovider-controller/apis/v1alpha1"
)

// userPoolClient builds a UserPoolClient in namespace "ns", optionally carrying
// an export reference and a recorded export target.
func userPoolClient(ref *ackv1alpha1.SecretKeyReference, exportedTo string) *svcapitypes.UserPoolClient {
	ko := &svcapitypes.UserPoolClient{
		ObjectMeta: metav1.ObjectMeta{Namespace: "ns"},
	}
	ko.Spec.ExportClientSecret = ref
	if exportedTo != "" {
		ko.Annotations = map[string]string{AnnotationExportedTo: exportedTo}
	}
	return ko
}

func secretRef(namespace, name, key string) *ackv1alpha1.SecretKeyReference {
	ref := &ackv1alpha1.SecretKeyReference{Key: key}
	ref.Name = name
	ref.Namespace = namespace
	return ref
}

func TestExportTargetID(t *testing.T) {
	for _, tc := range []struct {
		name string
		ref  *ackv1alpha1.SecretKeyReference
		want string
	}{
		{"no reference", nil, ""},
		{"namespace defaults to the resource's", secretRef("", "s", "k"), "ns/s/k"},
		{"explicit namespace wins", secretRef("other", "s", "k"), "other/s/k"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := exportTargetID(userPoolClient(tc.ref, "")); got != tc.want {
				t.Errorf("exportTargetID() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestExportTargetMoved(t *testing.T) {
	for _, tc := range []struct {
		name       string
		ref        *ackv1alpha1.SecretKeyReference
		exportedTo string
		want       bool
	}{
		{"no reference", nil, "", false},
		{"never exported", secretRef("", "s", "k"), "", true},
		{"same target", secretRef("", "s", "k"), "ns/s/k", false},
		{"secret re-pointed", secretRef("", "other", "k"), "ns/s/k", true},
		{"key re-pointed", secretRef("", "s", "other"), "ns/s/k", true},
		{"namespace re-pointed", secretRef("other", "s", "k"), "ns/s/k", true},
		// A reference dropped from the spec leaves the annotation behind, but
		// there is nothing left to export.
		{"reference removed", nil, "ns/s/k", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ko := userPoolClient(tc.ref, tc.exportedTo)
			if got := exportTargetMoved(ko); got != tc.want {
				t.Errorf("exportTargetMoved() = %v, want %v", got, tc.want)
			}
		})
	}
}

// TestCompareExportClientSecret covers the synthetic delta that replaces the
// generated comparison. Spec.ExportClientSecret is identical on both sides by
// construction -- sdkFind copies it from desired into latest -- so a difference
// can only come from the recorded target.
func TestCompareExportClientSecret(t *testing.T) {
	for _, tc := range []struct {
		name       string
		ref        *ackv1alpha1.SecretKeyReference
		exportedTo string
		wantDelta  bool
	}{
		{"no reference", nil, "", false},
		{"never exported", secretRef("", "s", "k"), "", true},
		{"steady state", secretRef("", "s", "k"), "ns/s/k", false},
		{"target moved", secretRef("", "other", "k"), "ns/s/k", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			ko := userPoolClient(tc.ref, tc.exportedTo)
			a := &resource{ko}
			b := &resource{ko.DeepCopy()}

			delta := ackcompare.NewDelta()
			compareExportClientSecret(delta, a, b)

			if got := delta.DifferentAt("Spec.ExportClientSecret"); got != tc.wantDelta {
				t.Fatalf("DifferentAt(Spec.ExportClientSecret) = %v, want %v", got, tc.wantDelta)
			}
			// The runtime only reaches sdkUpdate when the delta reports a
			// difference under Spec, and sdkUpdate only skips the AWS call when
			// the export target is the sole difference.
			if got := delta.DifferentAt("Spec"); got != tc.wantDelta {
				t.Errorf("DifferentAt(Spec) = %v, want %v", got, tc.wantDelta)
			}
			if got := delta.DifferentExcept("Spec.ExportClientSecret"); got {
				t.Errorf("DifferentExcept(Spec.ExportClientSecret) = true, want false")
			}
		})
	}
}

func TestCarryExportTarget(t *testing.T) {
	t.Run("copies the recorded target", func(t *testing.T) {
		src := userPoolClient(secretRef("", "s", "k"), "ns/s/k")
		dst := userPoolClient(secretRef("", "s", "k"), "")

		carryExportTarget(dst, src)

		if got := exportedTargetID(dst); got != "ns/s/k" {
			t.Errorf("exportedTargetID(dst) = %q, want %q", got, "ns/s/k")
		}
	})

	t.Run("leaves dst alone when src recorded nothing", func(t *testing.T) {
		src := userPoolClient(secretRef("", "s", "k"), "")
		dst := userPoolClient(secretRef("", "s", "k"), "ns/previous/k")

		carryExportTarget(dst, src)

		if got := exportedTargetID(dst); got != "ns/previous/k" {
			t.Errorf("exportedTargetID(dst) = %q, want %q", got, "ns/previous/k")
		}
	})
}

func TestRecordExportTarget(t *testing.T) {
	t.Run("stamps the declared target", func(t *testing.T) {
		ko := userPoolClient(secretRef("other", "s", "k"), "")

		recordExportTarget(ko)

		if got := exportedTargetID(ko); got != "other/s/k" {
			t.Errorf("exportedTargetID() = %q, want %q", got, "other/s/k")
		}
	})

	t.Run("records nothing without a reference", func(t *testing.T) {
		ko := userPoolClient(nil, "")

		recordExportTarget(ko)

		if _, ok := ko.Annotations[AnnotationExportedTo]; ok {
			t.Error("annotation was set without an export reference")
		}
	})
}
