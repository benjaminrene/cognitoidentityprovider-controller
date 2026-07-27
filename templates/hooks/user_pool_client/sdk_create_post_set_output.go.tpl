	// The app client was just created, so its secret has never been exported and
	// whatever the target Secret currently holds has to be replaced.
	if err = rm.exportClientSecret(ctx, ko, resp.UserPoolClient, true); err != nil {
		return &resource{ko}, err
	}
