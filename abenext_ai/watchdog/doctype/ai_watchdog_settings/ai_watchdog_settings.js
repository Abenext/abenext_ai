// Copyright (c) 2026, Abenext. All rights reserved.

frappe.ui.form.on("AI Watchdog Settings", {
	refresh(frm) {
		frappe.xcall("abenext_ai.setup.scheduler_paused").then((paused) => {
			if (paused) {
				frm.dashboard.set_headline_alert(
					__("Scheduled jobs are paused on this site, so nothing here runs automatically. Ask your administrator to resume the scheduler."),
					"orange");
			}
		});
	},
});
