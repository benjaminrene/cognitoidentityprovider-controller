	// In steady state the key is only filled when it is missing or empty, so the
	// controller does not fight another writer of a Secret it does not own. When
	// the target moved -- the reference was re-pointed, or the resource was
	// adopted and never exported -- the key holds a value that is not ours and
	// is replaced instead.
	if err = rm.exportClientSecret(ctx, ko, resp.UserPoolClient, exportTargetMoved(ko)); err != nil {
		return &resource{ko}, err
	}
