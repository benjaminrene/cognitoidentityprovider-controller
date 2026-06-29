	if err = rm.EventuallyExportSecret(ctx, ko, resp.UserPoolClient); err != nil {
        return &resource{ko}, err
    }
