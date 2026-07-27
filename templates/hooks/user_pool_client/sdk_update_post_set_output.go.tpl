	// Carry over the export target recorded by sdkFind earlier in this
	// reconcile. The runtime patches CR metadata on the update path, which is
	// how the annotation reaches etcd.
	carryExportTarget(ko, latest.ko)
