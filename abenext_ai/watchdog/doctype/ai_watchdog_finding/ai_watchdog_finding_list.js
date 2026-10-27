// Copyright (c) 2026, Abenext. All rights reserved.

frappe.listview_settings["AI Watchdog Finding"] = {
	add_fields: ["status", "severity"],
	get_indicator(doc) {
		if (doc.status === "Fixed") {
			return [__("Fixed"), "green", "status,=,Fixed"];
		}
		if (doc.status === "Ignored") {
			return [__("Ignored"), "gray", "status,=,Ignored"];
		}
		const colors = { High: "red", Medium: "orange", Low: "yellow" };
		return [__("Open · {0}", [doc.severity]), colors[doc.severity] || "orange", "status,=,Open"];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Run Checks Now"), () => {
			frappe.call("abenext_ai.watchdog.runner.run_now").then(() => {
				frappe.show_alert({ message: __("Checks are running. Refresh in a minute."), indicator: "blue" });
			});
		});
		const bulk = (status) => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Tick findings first."));
				return;
			}
			frappe.call("abenext_ai.watchdog.runner.set_status", { names: names, status: status })
				.then(() => listview.refresh());
		};
		listview.page.add_actions_menu_item(__("Mark Fixed"), () => bulk("Fixed"));
		listview.page.add_actions_menu_item(__("Ignore"), () => bulk("Ignored"));
		listview.page.add_actions_menu_item(__("Reopen"), () => bulk("Open"));
	},
};
