	if err = rm.EventuallyExportSecret(ctx, ko, resp.UserPoolClient, nil); err != nil {
        return &resource{ko}, err
    }
