	if ko.Spec.ExportClientSecret != nil && resp.UserPoolClient.ClientSecret != nil {
		namespace := ko.Namespace
		if ko.Spec.ExportClientSecret.Namespace != "" {
			namespace = ko.Spec.ExportClientSecret.Namespace
		}
		if err = rm.rr.WriteToSecret(ctx, *resp.UserPoolClient.ClientSecret, namespace, ko.Spec.ExportClientSecret.Name, ko.Spec.ExportClientSecret.Key); err != nil {
			return nil, err
		}
	}
