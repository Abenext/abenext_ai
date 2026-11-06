// Copyright (c) 2026, Abenext. All rights reserved.

frappe.ui.form.on("AI Collections Settings", {
	refresh(frm) {
		if (!frm.doc.send_reminders) {
			frm.page.set_indicator(__("Reminders off"), "gray");
		} else if (frm.doc.test_mode) {
			frm.page.set_indicator(__("Test Mode"), "blue");
		} else {
			frm.page.set_indicator(__("Sending to customers"), "green");
		}
		if (frm.doc.send_reminders && !frm.doc.test_mode) {
			frm.set_intro(__("Reminders are going to real customers."), "orange");
		} else if (frm.doc.test_mode) {
			frm.set_intro(__("Test Mode: every message goes to {0}.", [frm.doc.test_recipient || __("(no test recipient set)")]), "blue");
		}
		frm.add_custom_button(__("Preview Today's Reminders"), () => {
			frappe.call({ method: "abenext_ai.collections_agent.agent.preview", freeze: true, freeze_message: __("Preparing reminders...") })
				.then((r) => show_preview(r.message || []));
		});
		frm.add_custom_button(__("Send Now"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save first."));
				return;
			}
			const where = frm.doc.test_mode ? __("to the Test Recipient only") : __("to real customers");
			frappe.confirm(__("Send today's reminders {0}?", [where]), () => {
				frappe.call({ method: "abenext_ai.collections_agent.agent.send_now", freeze: true })
					.then((r) => frappe.msgprint(r.message || __("Done.")));
			});
		});
	},
});

function show_preview(items) {
	if (!items.length) {
		frappe.msgprint(__("Nothing to send today."));
		return;
	}
	const esc = frappe.utils.escape_html;
	const html = items.map((item) => `
		<div style="border:1px solid var(--border-color);border-radius:8px;padding:12px;margin-bottom:12px">
			<div><b>${esc(item.customer)}</b> · ${esc(item.stage || "")} · ${esc(item.total_text || "")}</div>
			<div class="text-muted small">${item.recipient ? __("To: {0}", [esc(item.recipient)]) : ""} ${esc(item.note || "")}</div>
			${item.subject ? `<hr><div><b>${esc(item.subject)}</b></div><div>${item.message || ""}</div>` : ""}
		</div>`).join("");
	const dialog = new frappe.ui.Dialog({ title: __("Today's reminders (preview, nothing sent)"), size: "extra-large" });
	dialog.$body.html(`<div style="max-height:70vh;overflow:auto">${html}</div>`);
	dialog.show();
}

frappe.ui.form.on("AI Collections Settings", {
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
