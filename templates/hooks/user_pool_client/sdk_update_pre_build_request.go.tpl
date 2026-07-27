	if !delta.DifferentExcept("Spec.ExportClientSecret") {
		// Only the export target moved. sdkFind already wrote the client secret
		// to the new Secret earlier in this same reconcile, and Cognito has
		// nothing to update, so the API call is skipped. Returning a copy of
		// desired rather than desired itself is what makes the runtime persist
		// the annotation: patchResourceMetadataAndSpec diffs the resource
		// returned here against desired, and an identical object is not patched.
		ko := desired.ko.DeepCopy()
		carryExportTarget(ko, latest.ko)
		ko.Status = *latest.ko.Status.DeepCopy()
		return &resource{ko}, nil
	}
