import frappe
from frappe.utils import flt

from commera_picker.api import get_open_pick_list_for_order


def can_release_for_picking(doctype: str, name: str) -> bool:
	order = frappe.db.get_value("Sales Order", name, ["docstatus", "status", "per_picked"], as_dict=True)
	return bool(
		order
		and order.docstatus == 1
		and order.status not in ("Closed", "On Hold", "Completed")
		and flt(order.per_picked) < 100
		and frappe.has_permission("Pick List", "create")
		and not get_open_pick_list_for_order(name)
	)
