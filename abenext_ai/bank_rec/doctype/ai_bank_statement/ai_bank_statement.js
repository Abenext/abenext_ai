// Copyright (c) 2026, Abenext. All rights reserved.

const AIBS_MODULE = "abenext_ai.bank_rec.doctype.ai_bank_statement.ai_bank_statement";

frappe.ui.form.on("AI Bank Statement", {
	setup() {
		frappe.realtime.off("ai_bank_statement_processed");
		frappe.realtime.on("ai_bank_statement_processed", (data) => {
			if (cur_frm && cur_frm.doctype === "AI Bank Statement" && data.name === cur_frm.doc.name) {
				cur_frm.reload_doc();
			}
		});
	},

	refresh(frm) {
		show_status(frm);
		if (frm.doc.docstatus !== 0 || frm.is_new()) {
			return;
		}

		const lines = frm.doc.lines || [];
		const linked = lines.some((row) => row.bank_transaction);
		const busy = ["Extracting", "Creating Transactions", "Matching"].includes(frm.doc.status);

		if (frm.doc.statement_file && !busy && !linked) {
			const label = lines.length ? __("Process Again") : __("Process Statement");
			frm.add_custom_button(label, () => run(frm, "process_statement", __("Reading the statement...")),
				lines.length ? __("Actions") : null);
		}

		const unlinked = lines.filter((r) => !r.bank_transaction).length;
		if (["Extracted", "Transactions Created"].includes(frm.doc.status) && unlinked) {
			frm.add_custom_button(__("Create Bank Transactions"), () => {
				frappe.confirm(
					__("Create and submit {0} Bank Transactions for {1}?", [unlinked, frm.doc.bank_account]),
					() => run(frm, "create_bank_transactions", __("Creating Bank Transactions..."))
				);
			}).addClass("btn-primary");
		}

		if (["Transactions Created", "Ready for Review"].includes(frm.doc.status) && lines.length && !unlinked) {
			const again = frm.doc.status === "Ready for Review";
			const button = frm.add_custom_button(again ? __("Match Again") : __("Find Matches"),
				() => run(frm, "find_matches", __("Finding matches...")),
				again ? __("Actions") : null);
			if (!again) {
				button.addClass("btn-primary");
			}
		}
	},
});

frappe.ui.form.on("AI Bank Statement Line", {
	form_render(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.matched_vouchers) {
			return;
		}
		const list = JSON.parse(row.matched_vouchers)
			.map((v) => `${v.voucher_type} ${v.voucher}: ${format_currency(v.amount)}`)
			.join("<br>");
		frm.fields_dict.lines.grid.grid_rows_by_docname[cdn].get_field("matched_vouchers")
			.set_description(list);
	},
});

function run(frm, method, alert) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the statement first."));
		return;
	}
	frappe.call({ method: `${AIBS_MODULE}.${method}`, args: { name: frm.doc.name } }).then(() => {
		frappe.show_alert({ message: alert, indicator: "blue" });
		frm.reload_doc();
	});
}

function show_status(frm) {
	frm.set_intro("");
	const lines = (frm.doc.lines || []).length;
	const linked = (frm.doc.lines || []).filter((row) => row.bank_transaction).length;
	const messages = {
		"Extracting": [__("Reading the statement. This page updates when it is done."), "blue"],
		"Extracted": [frm.doc.error_log || __("{0} lines read. Every running balance agrees with the bank, from opening to closing balance.", [lines]), frm.doc.error_log ? "orange" : "green"],
		"Balance Mismatch": [__("{0} lines read, but some balances do not agree. See the Log section and the unticked Balance OK lines.", [lines]), "orange"],
		"Creating Transactions": [__("Creating Bank Transactions. This page updates when it is done."), "blue"],
		"Transactions Created": [__("{0} of {1} lines are linked to Bank Transactions. {2}", [linked, lines, frm.doc.error_log || ""]), "green"],
		"Matching": [__("Finding matches. This page updates when it is done."), "blue"],
		"Ready for Review": [frm.doc.error_log || __("Matching is done."), "green"],
		"Failed": [__("The statement could not be read. See the Log section."), "red"],
	};
	const message = messages[frm.doc.status];
	if (message) {
		frm.set_intro(message[0], message[1]);
	}
}
