// Copyright (c) 2026, Abenext. All rights reserved.
// Once per browser session, remind managers when the Abenext subscription needs attention.

$(document).on("app_ready", () => {
	if (!frappe.session || frappe.session.user === "Guest") {
		return;
	}
	if (!(frappe.user.has_role("System Manager") || frappe.user.has_role("Accounts Manager"))) {
		return;
	}
	const key = "abenext_license_notice_shown";
	if (sessionStorage.getItem(key)) {
		return;
	}
	frappe.xcall("abenext_ai.ai_client.license_status").then((status) => {
		const notices = {
			Grace: [__("The Abenext AI subscription payment is overdue. AI suggestions will pause soon."), "orange"],
			Suspended: [__("AI suggestions are paused: the Abenext AI subscription needs attention. Your ERPNext keeps working."), "red"],
		};
		if (notices[status]) {
			frappe.show_alert({ message: notices[status][0], indicator: notices[status][1] }, 15);
			sessionStorage.setItem(key, "1");
		}
	});
});
