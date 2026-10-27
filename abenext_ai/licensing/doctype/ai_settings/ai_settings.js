// Copyright (c) 2026, Abenext. All rights reserved.

frappe.ui.form.on("AI Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings first."));
				return;
			}
			frappe.call({ method: "abenext_ai.ai_client.test_connection", freeze: true, freeze_message: __("Contacting the Abenext server...") })
				.then((r) => {
					const m = r.message || {};
					frappe.msgprint({
						title: __("Connected"),
						indicator: "green",
						message: __("License {0} is {1}, valid till {2}.<br>AI provider: {3}", [
							m.license_id, m.status, m.valid_till || "-", m.ai || __("not checked"),
						]),
					});
					frm.reload_doc();
				});
		});
	},
});
