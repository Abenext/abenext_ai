// Copyright (c) 2026, Abenext. All rights reserved.

const AIBS = "abenext_ai.bank_rec.doctype.ai_bank_statement.ai_bank_statement";
const BUSY = ["Extracting", "Creating Transactions", "Matching", "Reconciling"];

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
		if (frm.doc.docstatus !== 0 || frm.is_new() || BUSY.includes(frm.doc.status)) {
			return;
		}

		const lines = frm.doc.lines || [];
		const linked = lines.some((row) => row.bank_transaction);
		const unlinked = lines.filter((row) => !row.bank_transaction).length;

		if (frm.doc.statement_file && !linked) {
			frm.add_custom_button(lines.length ? __("Process Again") : __("Process Statement"),
				() => queue(frm, "process_statement", __("Reading the statement...")),
				lines.length ? __("Actions") : null);
		}

		if (["Extracted", "Transactions Created"].includes(frm.doc.status) && unlinked) {
			frm.add_custom_button(__("Create Bank Transactions"), () => {
				frappe.confirm(__("Create and submit {0} Bank Transactions for {1}?", [unlinked, frm.doc.bank_account]),
					() => queue(frm, "create_bank_transactions", __("Creating Bank Transactions...")));
			}).addClass("btn-primary");
		}

		if (frm.doc.status === "Transactions Created" && lines.length && !unlinked) {
			frm.add_custom_button(__("Find Matches"), () => queue(frm, "find_matches", __("Finding matches...")))
				.addClass("btn-primary");
		}

		if (frm.doc.status === "Ready for Review") {
			add_review_buttons(frm, lines);
		}
	},
});

function add_review_buttons(frm, lines) {
	const review = __("Review");
	const selected = () => frm.fields_dict.lines.grid.get_selected_children().map((row) => row.name);

	frm.add_custom_button(__("Accept Selected"), () => set_status(frm, selected(), "Accepted"), review);
	frm.add_custom_button(__("Skip Selected"), () => set_status(frm, selected(), "Skipped"), review);
	frm.add_custom_button(__("Back to Pending"), () => set_status(frm, selected(), "Pending"), review);
	frm.add_custom_button(__("Accept All Above Threshold"), () => {
		call(frm, "accept_above_threshold", {}).then((r) => {
			frappe.show_alert({ message: __("{0} line(s) accepted (confidence {1}% or more).", [r.changed, r.threshold]), indicator: "green" });
		});
	}, review);

	const unmatched = lines.filter((row) => row.line_status === "Pending" && !row.matched_voucher).length;
	if (unmatched) {
		frm.add_custom_button(__("Skip All Unmatched ({0})", [unmatched]), () => {
			frappe.confirm(__("Skip {0} pending line(s) that have no match? You can set them back to Pending later.", [unmatched]), () => {
				call(frm, "skip_unmatched", {}).then((r) => {
					frappe.show_alert({ message: __("{0} line(s) skipped.", [r.changed]), indicator: "green" });
				});
			});
		}, review);
	}

	const entries = __("Missing Entries");
	frm.add_custom_button(__("Create Entries for Unmatched Lines..."), () => missing_entries_dialog(frm), entries);
	frm.add_custom_button(__("Submit Created Entries"), () => {
		frappe.confirm(__("Submit the draft Journal Entries created from this statement?"), () => {
			call(frm, "submit_created_entries", {}).then((r) => {
				const extra = r.problems.length ? "<br>" + r.problems.join("<br>") : "";
				frappe.msgprint(__("{0} Journal Entr(ies) submitted.", [r.submitted]) + extra);
			});
		});
	}, entries);

	frm.add_custom_button(__("Match Again"), () => queue(frm, "find_matches", __("Finding matches...")), __("Actions"));

	const accepted = lines.filter((row) => row.line_status === "Accepted").length;
	if (accepted) {
		frm.add_custom_button(__("Reconcile {0} Accepted", [accepted]), () => {
			frappe.confirm(__("Reconcile {0} accepted line(s) in ERPNext? This links each Bank Transaction to its entries and sets their clearance dates.", [accepted]),
				() => queue(frm, "reconcile_accepted", __("Reconciling...")));
		}).addClass("btn-primary");
	}
}

function set_status(frm, rows, status) {
	if (!rows.length) {
		frappe.msgprint(__("Tick the lines in the Lines table first."));
		return;
	}
	call(frm, "set_line_status", { rows: rows, status: status }).then((r) => {
		let message = __("{0} line(s) updated.", [r.changed]);
		if (r.ignored) {
			message += " " + __("{0} skipped (reconciled, or no match to accept).", [r.ignored]);
		}
		frappe.show_alert({ message: message, indicator: "green" });
	});
}

function missing_entries_dialog(frm) {
	const selected = frm.fields_dict.lines.grid.get_selected_children()
		.filter((row) => row.line_status === "Pending" && !row.matched_voucher);
	const dialog = new frappe.ui.Dialog({
		title: __("Create Journal Entries for Unmatched Lines"),
		fields: [
			{
				fieldname: "account", fieldtype: "Link", options: "Account", reqd: 1, label: __("Account"),
				get_query: () => ({ filters: { company: frm.doc.company, is_group: 0 } }),
			},
			{
				fieldname: "keyword", fieldtype: "Data", label: __("Lines whose description contains"),
				default: selected.length ? "" : "CHARGES", read_only: selected.length ? 1 : 0,
				description: selected.length
					? __("{0} ticked unmatched line(s) will be used.", [selected.length])
					: __("For example CHARGES or FED. Tick lines in the table instead to choose them yourself."),
			},
		],
		primary_action_label: __("Create Draft Entries"),
		primary_action(values) {
			dialog.hide();
			call(frm, "create_missing_entries", {
				account: values.account,
				keyword: values.keyword,
				rows: selected.map((row) => row.name),
			}).then((r) => {
				frappe.msgprint(__("{0} draft Journal Entr(ies) created. Check them, then use Missing Entries > Submit Created Entries.", [r.created]));
			});
		},
	});
	frappe.db.get_single_value("AI Reconciliation Settings", "bank_charges_account").then((account) => {
		if (account) {
			dialog.set_value("account", account);
		}
	});
	dialog.show();
}

function call(frm, method, args) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the statement first."));
		return Promise.reject();
	}
	return frappe.call({ method: `${AIBS}.${method}`, args: Object.assign({ name: frm.doc.name }, args), freeze: true })
		.then((r) => {
			frm.reload_doc();
			return r.message;
		});
}

function queue(frm, method, alert) {
	call(frm, method, {}).then(() => frappe.show_alert({ message: alert, indicator: "blue" }));
}

frappe.ui.form.on("AI Bank Statement Line", {
	form_render(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.matched_vouchers) {
			return;
		}
		const list = JSON.parse(row.matched_vouchers)
			.map((v) => `${v.voucher_type} ${v.voucher}: ${format_currency(v.amount)}`)
			.join("<br>");
		frm.fields_dict.lines.grid.grid_rows_by_docname[cdn].get_field("matched_vouchers").set_description(list);
	},
	matched_voucher_type(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "matched_voucher", "");
	},
});

function show_status(frm) {
	frm.set_intro("");
	const lines = frm.doc.lines || [];
	const count = (status) => lines.filter((row) => row.line_status === status).length;
	const linked = lines.filter((row) => row.bank_transaction).length;
	const messages = {
		"Extracting": [__("Reading the statement. This page updates when it is done."), "blue"],
		"Extracted": [frm.doc.error_log || __("{0} lines read. Every running balance agrees with the bank, from opening to closing balance.", [lines.length]), frm.doc.error_log ? "orange" : "green"],
		"Balance Mismatch": [__("{0} lines read, but some balances do not agree. See the Log section and the unticked Balance OK lines.", [lines.length]), "orange"],
		"Creating Transactions": [__("Creating Bank Transactions. This page updates when it is done."), "blue"],
		"Transactions Created": [__("{0} of {1} lines are linked to Bank Transactions. {2}", [linked, lines.length, frm.doc.error_log || ""]), "green"],
		"Matching": [__("Finding matches. This page updates when it is done."), "blue"],
		"Reconciling": [__("Reconciling. This page updates when it is done."), "blue"],
		"Ready for Review": [__("Pending: {0} · Accepted: {1} · Reconciled: {2} · Skipped: {3}", [count("Pending"), count("Accepted"), count("Reconciled"), count("Skipped")])
			+ (frm.doc.error_log ? "<br>" + frappe.utils.escape_html(frm.doc.error_log).replace(/\n/g, "<br>") : ""), "blue"],
		"Reconciled": [__("Every line is reconciled or skipped. {0}", [frm.doc.error_log || ""]), "green"],
		"Failed": [__("The statement could not be read. See the Log section."), "red"],
	};
	const message = messages[frm.doc.status];
	if (message) {
		frm.set_intro(message[0], message[1]);
	}
}
