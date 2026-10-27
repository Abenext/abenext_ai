// Copyright (c) 2026, Abenext. All rights reserved.

frappe.ui.form.on("AI Watchdog Finding", {
	refresh(frm) {
		if (frm.doc.reference_name) {
			frm.add_custom_button(__("Open {0}", [frm.doc.reference_name]),
				() => frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name));
		}
		if (frm.doc.related_name) {
			frm.add_custom_button(__("Open {0}", [frm.doc.related_name]),
				() => frappe.set_route("Form", frm.doc.related_doctype, frm.doc.related_name));
		}
		if (frm.doc.status === "Open") {
			frm.add_custom_button(__("Mark Fixed"), () => set_status(frm, "Fixed")).addClass("btn-primary");
			frm.add_custom_button(__("Ignore"), () => set_status(frm, "Ignored"));
		} else {
			frm.add_custom_button(__("Reopen"), () => set_status(frm, "Open"));
		}
	},
});

function set_status(frm, status) {
	frm.set_value("status", status);
	frm.save();
}
