	if ko.Spec.ExportClientSecret != nil && resp.UserPoolClient.ClientSecret != nil &&
	   (ko.Status.LastModifiedDate == nil || resp.UserPoolClient.LastModifiedDate == nil || ko.Status.LastModifiedDate.Time.Equal(*resp.UserPoolClient.LastModifiedDate)) {
		namespace := ko.Namespace
		if ko.Spec.ExportClientSecret.Namespace != "" {
			namespace = ko.Spec.ExportClientSecret.Namespace
		}
		if err = rm.rr.WriteToSecret(ctx, *resp.UserPoolClient.ClientSecret, namespace, ko.Spec.ExportClientSecret.Name, ko.Spec.ExportClientSecret.Key); err != nil {
			return &resource{ko}, err
		}
	}
