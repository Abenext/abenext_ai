// Copyright (c) 2026, Abenext. All rights reserved.

const AIBS_PROCESS = "abenext_ai.bank_rec.doctype.ai_bank_statement.ai_bank_statement.process_statement";

frappe.ui.form.on("AI Bank Statement", {
	setup(frm) {
		frappe.realtime.off("ai_bank_statement_processed");
		frappe.realtime.on("ai_bank_statement_processed", (data) => {
			if (cur_frm && cur_frm.doctype === "AI Bank Statement" && data.name === cur_frm.doc.name) {
				cur_frm.reload_doc();
			}
		});
	},

	refresh(frm) {
		show_status(frm);

		const can_process = frm.doc.docstatus === 0 && !frm.is_new()
			&& frm.doc.statement_file && frm.doc.status !== "Extracting";
		if (can_process) {
			const label = (frm.doc.lines || []).length ? __("Process Again") : __("Process Statement");
			frm.add_custom_button(label, () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save the statement first."));
					return;
				}
				frappe.call({ method: AIBS_PROCESS, args: { name: frm.doc.name } }).then(() => {
					frappe.show_alert({ message: __("Reading the statement..."), indicator: "blue" });
					frm.reload_doc();
				});
			}).addClass("btn-primary");
		}
	},
});

function show_status(frm) {
	frm.set_intro("");
	const lines = (frm.doc.lines || []).length;
	const messages = {
		"Extracting": [__("Reading the statement. This page updates when it is done."), "blue"],
		"Extracted": [__("{0} lines read. Every running balance agrees with the bank, from opening to closing balance.", [lines]), "green"],
		"Balance Mismatch": [__("{0} lines read, but some balances do not agree. See the Log section and the unticked Balance OK lines.", [lines]), "orange"],
		"Failed": [__("The statement could not be read. See the Log section."), "red"],
	};
	const message = messages[frm.doc.status];
	if (message) {
		frm.set_intro(message[0], message[1]);
	}
}
