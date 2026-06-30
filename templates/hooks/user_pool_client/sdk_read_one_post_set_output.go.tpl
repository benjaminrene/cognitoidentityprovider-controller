	if err = rm.EventuallyExportSecret(ctx, ko, resp.UserPoolClient, r.ko.Status.LastModifiedDate); err != nil {
        return &resource{ko}, err
    }
