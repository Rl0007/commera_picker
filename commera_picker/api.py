import frappe
from erpnext.selling.doctype.sales_order.sales_order import create_pick_list
from erpnext.stock.utils import scan_barcode
from frappe import _
from frappe.desk.form import assign_to
from frappe.model.workflow import apply_workflow
from frappe.utils import cint, flt, get_fullname

from commera_picker.install import (
	FINISH_PICKING,
	IN_PROGRESS,
	ON_HOLD,
	OPEN,
	PUT_ON_HOLD,
	READY_TO_SHIP,
	RESUME_PICKING,
	RETURN_TO_OPEN,
	START_PICKING,
	STATE_FIELD,
)

PICKING_STATES = (OPEN, ON_HOLD, IN_PROGRESS, READY_TO_SHIP)


class PickListLockedError(frappe.ValidationError):
	pass


@frappe.whitelist()
def release_for_picking(sales_order: str) -> str:
	frappe.has_permission("Sales Order", "read", sales_order, throw=True)
	frappe.has_permission("Pick List", "create", throw=True)

	if open_pick_list_name := get_open_pick_list_for_order(sales_order):
		frappe.throw(
			_("Sales Order {0} is already released for picking in {1}").format(
				frappe.bold(sales_order), frappe.bold(open_pick_list_name)
			)
		)

	frappe.flags.commera_picker_release = True
	try:
		pick_list = create_pick_list(sales_order)
	finally:
		frappe.flags.commera_picker_release = False
	pick_list.pick_manually = 1
	pick_list.insert()
	return pick_list.name


def get_open_pick_list_for_order(sales_order: str) -> str | None:
	open_pick_lists = frappe.get_all(
		"Pick List",
		filters=[["docstatus", "=", 0], ["Pick List Item", "sales_order", "=", sales_order]],
		pluck="name",
		limit=1,
	)
	return open_pick_lists[0] if open_pick_lists else None


def set_picking_warehouse(pick_list, method=None, sales_order=None) -> None:
	if frappe.flags.commera_picker_release and sales_order:
		pick_list.parent_warehouse = get_picking_warehouse(sales_order.name)


def get_picking_warehouse(sales_order: str) -> str | None:
	order_warehouse = frappe.db.get_value("Sales Order", sales_order, "set_warehouse") or frappe.db.get_value(
		"Sales Order Item", {"parent": sales_order, "warehouse": ("is", "set")}, "warehouse"
	)
	if not order_warehouse:
		return None
	return frappe.db.get_value("Warehouse", order_warehouse, "parent_warehouse") or order_warehouse


@frappe.whitelist()
def get_pick_lists(state: str = OPEN, start: int = 0, page_length: int = 20) -> dict:
	frappe.has_permission("Pick List", "read", throw=True)
	if state not in PICKING_STATES:
		frappe.throw(_("Unknown picking state {0}").format(frappe.bold(state)))

	filters = {"purpose": "Delivery", "docstatus": ("<", 2)}
	state_counts = frappe.get_list(
		"Pick List",
		filters=filters,
		fields=[STATE_FIELD, {"COUNT": "*", "as": "count"}],
		group_by=STATE_FIELD,
	)
	counts = dict.fromkeys(PICKING_STATES, 0)
	for state_count in state_counts:
		if state_count[STATE_FIELD] in counts:
			counts[state_count[STATE_FIELD]] = state_count["count"]

	pick_lists = frappe.get_list(
		"Pick List",
		filters={**filters, STATE_FIELD: state},
		fields=["name", "customer", "customer_name", "creation"],
		order_by="creation asc",
		start=cint(start),
		page_length=cint(page_length) or 20,
	)
	return {"counts": counts, "pick_lists": get_list_rows(pick_lists)}


def get_list_rows(pick_lists: list[dict]) -> list[dict]:
	if not pick_lists:
		return []

	pick_list_names = [pick_list.name for pick_list in pick_lists]
	sales_order_by_pick_list = {}
	article_count_by_pick_list = dict.fromkeys(pick_list_names, 0)
	for location in frappe.get_all(
		"Pick List Item",
		filters={"parent": ("in", pick_list_names), "parenttype": "Pick List"},
		fields=["parent", "sales_order"],
	):
		article_count_by_pick_list[location.parent] += 1
		if location.sales_order:
			sales_order_by_pick_list.setdefault(location.parent, location.sales_order)

	sales_orders = {
		sales_order.name: sales_order
		for sales_order in frappe.get_all(
			"Sales Order",
			filters={"name": ("in", list(set(sales_order_by_pick_list.values())))},
			fields=["name", "transaction_date", "customer_name", "shipping_address_name"],
		)
	}
	pincode_by_address = dict(
		frappe.get_all(
			"Address",
			filters={
				"name": (
					"in",
					[
						order.shipping_address_name
						for order in sales_orders.values()
						if order.shipping_address_name
					],
				)
			},
			fields=["name", "pincode"],
			as_list=True,
		)
	)
	assignee_by_pick_list = get_assignees(pick_list_names)

	rows = []
	for pick_list in pick_lists:
		sales_order = sales_orders.get(sales_order_by_pick_list.get(pick_list.name)) or frappe._dict()
		assignee = assignee_by_pick_list.get(pick_list.name)
		rows.append(
			{
				"name": pick_list.name,
				"sales_order": sales_order.name,
				"customer": sales_order.customer_name or pick_list.customer_name or pick_list.customer,
				"transaction_date": sales_order.transaction_date or pick_list.creation.date(),
				"pincode": pincode_by_address.get(sales_order.shipping_address_name),
				"article_count": article_count_by_pick_list[pick_list.name],
				"assignee": assignee,
				"assignee_name": get_fullname(assignee) if assignee else None,
			}
		)
	return rows


def get_assignees(pick_list_names: list[str]) -> dict[str, str]:
	return {
		todo.reference_name: todo.allocated_to
		for todo in frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Pick List",
				"reference_name": ("in", pick_list_names),
				"status": "Open",
			},
			fields=["reference_name", "allocated_to"],
		)
	}


@frappe.whitelist()
def get_pick_list(name: str) -> dict:
	frappe.has_permission("Pick List", "read", name, throw=True)
	pick_list = frappe.get_doc("Pick List", name)
	rows = get_rows(pick_list)
	sales_order_name = next((row.sales_order for row in pick_list.locations if row.sales_order), None)
	assignee = get_assignees([name]).get(name)

	return {
		"name": pick_list.name,
		"state": pick_list.get(STATE_FIELD),
		"docstatus": pick_list.docstatus,
		"assignee": assignee,
		"assignee_name": get_fullname(assignee) if assignee else None,
		"is_mine": assignee == frappe.session.user,
		"sales_order": sales_order_name,
		"customer": pick_list.customer_name or pick_list.customer,
		"shipping_address": get_shipping_address(sales_order_name),
		"comments": get_order_comments(sales_order_name),
		"open_rows": [row for row in rows if not row["picking_done"]],
		"picked_rows": [row for row in rows if row["picking_done"]],
	}


def get_rows(pick_list) -> list[dict]:
	item_codes = list({row.item_code for row in pick_list.locations})
	warehouses = list({row.warehouse for row in pick_list.locations if row.warehouse})
	if not item_codes:
		return []

	items = {
		item.name: item
		for item in frappe.get_all(
			"Item",
			filters={"name": ("in", item_codes)},
			fields=["name", "item_name", "image", "weight_per_unit", "weight_uom"],
		)
	}
	bin_codes = (
		dict(
			frappe.get_all(
				"Warehouse",
				filters={"name": ("in", warehouses)},
				fields=["name", "warehouse_name"],
				as_list=True,
			)
		)
		if warehouses
		else {}
	)
	stock_by_bin = (
		{
			(stock.item_code, stock.warehouse): stock.actual_qty
			for stock in frappe.get_all(
				"Bin",
				filters={"item_code": ("in", item_codes), "warehouse": ("in", warehouses)},
				fields=["item_code", "warehouse", "actual_qty"],
			)
		}
		if warehouses
		else {}
	)

	rows = []
	for row in pick_list.locations:
		item = items.get(row.item_code) or frappe._dict()
		conversion_factor = flt(row.conversion_factor) or 1
		rows.append(
			{
				"name": row.name,
				"item_code": row.item_code,
				"item_name": item.item_name or row.item_name,
				"image": item.image,
				"weight": flt(item.weight_per_unit),
				"weight_uom": item.weight_uom,
				"warehouse": row.warehouse,
				"bin": bin_codes.get(row.warehouse) or row.warehouse,
				"stock_in_bin": flt(stock_by_bin.get((row.item_code, row.warehouse))),
				"qty": flt(row.qty),
				"picked_qty": flt(row.picked_qty) / conversion_factor,
				"uom": row.uom,
				"picking_done": cint(row.get("picking_done")),
			}
		)
	return sorted(rows, key=lambda row: (row["bin"] or "", row["item_code"]))


def get_shipping_address(sales_order: str | None) -> dict | None:
	if not sales_order:
		return None
	address_name = frappe.db.get_value("Sales Order", sales_order, "shipping_address_name")
	if not address_name:
		return None
	return frappe.db.get_value(
		"Address",
		address_name,
		["address_title", "address_line1", "address_line2", "pincode", "city", "country"],
		as_dict=True,
	)


def get_order_comments(sales_order: str | None) -> list[dict]:
	if not sales_order:
		return []
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Sales Order",
			"reference_name": sales_order,
			"comment_type": "Comment",
		},
		fields=["content", "comment_by", "owner", "creation"],
		order_by="creation asc",
	)
	for comment in comments:
		owner = comment.pop("owner")
		comment.comment_by = comment.comment_by or get_fullname(owner)
	return comments


@frappe.whitelist()
def open_pick_list(name: str) -> dict:
	frappe.has_permission("Pick List", "write", name, throw=True)
	user = frappe.session.user

	state = frappe.db.get_value("Pick List", name, STATE_FIELD, for_update=True)
	assignee = frappe.db.get_value(
		"ToDo",
		{"reference_type": "Pick List", "reference_name": name, "status": "Open"},
		"allocated_to",
		for_update=True,
	)

	if assignee == user and state == IN_PROGRESS:
		return get_pick_list(name)
	if assignee or state == IN_PROGRESS:
		frappe.throw(
			_("This order is already being picked by {0}").format(
				frappe.bold(get_fullname(assignee) if assignee else _("another picker"))
			),
			PickListLockedError,
		)
	if state not in (OPEN, ON_HOLD):
		frappe.throw(_("This order can't be picked in state {0}").format(frappe.bold(state)))

	assign_to.add({"assign_to": [user], "doctype": "Pick List", "name": name})
	apply_workflow(frappe.get_doc("Pick List", name), START_PICKING if state == OPEN else RESUME_PICKING)
	return get_pick_list(name)


@frappe.whitelist()
def pick_next() -> dict:
	frappe.has_permission("Pick List", "write", throw=True)
	unassigned_pick_lists = frappe.get_list(
		"Pick List",
		filters={"purpose": "Delivery", "docstatus": 0, STATE_FIELD: OPEN},
		pluck="name",
		order_by="creation asc",
		page_length=10,
	)
	for pick_list_name in unassigned_pick_lists:
		try:
			return open_pick_list(pick_list_name)
		except PickListLockedError:
			frappe.clear_messages()

	frappe.throw(_("There are no open orders to pick"))


@frappe.whitelist()
def set_picked_qty(name: str, row_name: str, qty: float) -> dict:
	pick_list = get_pick_list_for_picking(name)
	row = get_open_row(pick_list, row_name)
	qty = flt(qty)
	if qty < 0 or qty > flt(row.qty):
		frappe.throw(
			_("Picked quantity must be between 0 and {0} for {1}").format(
				flt(row.qty), frappe.bold(row.item_code)
			)
		)

	row.picked_qty = qty * (flt(row.conversion_factor) or 1)
	return resolve_row(pick_list, row)


@frappe.whitelist()
def mark_unavailable(name: str, row_name: str) -> dict:
	pick_list = get_pick_list_for_picking(name)
	row = get_open_row(pick_list, row_name)
	row.picked_qty = 0
	return resolve_row(pick_list, row)


@frappe.whitelist()
def scan(name: str, barcode: str) -> dict:
	pick_list = get_pick_list_for_picking(name)
	barcode = (barcode or "").strip()
	item_code = scan_barcode(barcode).get("item_code") if barcode else None
	if not item_code:
		frappe.throw(_("No article found for barcode {0}").format(frappe.bold(barcode)))

	open_row_names = {
		row.name for row in pick_list.locations if row.item_code == item_code and not row.get("picking_done")
	}
	matching_row = next((row for row in get_rows(pick_list) if row["name"] in open_row_names), None)
	if not matching_row:
		item_name = frappe.db.get_value("Item", item_code, "item_name") or item_code
		frappe.throw(
			_("{0} ({1}) is not an open article in this order").format(frappe.bold(item_name), item_code)
		)
	return matching_row


@frappe.whitelist()
def hold(name: str) -> dict:
	pick_list = get_pick_list_for_picking(name)
	has_picked_rows = any(flt(row.picked_qty) for row in pick_list.locations)
	apply_workflow(pick_list, PUT_ON_HOLD if has_picked_rows else RETURN_TO_OPEN)
	assign_to.remove("Pick List", name, frappe.session.user)
	return get_pick_list(name)


def get_pick_list_for_picking(name: str):
	frappe.has_permission("Pick List", "write", name, throw=True)
	pick_list = frappe.get_doc("Pick List", name)
	if pick_list.get(STATE_FIELD) != IN_PROGRESS:
		frappe.throw(_("Open the order before picking it"))
	if get_assignees([name]).get(name) != frappe.session.user:
		frappe.throw(_("This order is being picked by someone else"), PickListLockedError)
	return pick_list


def get_open_row(pick_list, row_name: str):
	row = next((row for row in pick_list.locations if row.name == row_name), None)
	if not row:
		frappe.throw(_("Row {0} is not in this order").format(frappe.bold(row_name)))
	if row.get("picking_done"):
		frappe.throw(_("{0} is already picked").format(frappe.bold(row.item_code)))
	return row


def resolve_row(pick_list, row) -> dict:
	row.picking_done = 1
	if any(not location.get("picking_done") for location in pick_list.locations):
		pick_list.save()
		return get_pick_list(pick_list.name)

	if not any(flt(location.picked_qty) for location in pick_list.locations):
		frappe.throw(_("Nothing was picked. Put the order on hold."))

	finish(pick_list)
	return get_pick_list(pick_list.name)


def finish(pick_list) -> None:
	for row in list(pick_list.locations):
		if not flt(row.picked_qty):
			pick_list.remove(row)
			continue
		row.stock_qty = flt(row.picked_qty)
		row.qty = flt(row.picked_qty) / (flt(row.conversion_factor) or 1)

	for index, row in enumerate(pick_list.locations, start=1):
		row.idx = index
	pick_list.save()
	apply_workflow(pick_list, FINISH_PICKING)
	assign_to.close_all_assignments("Pick List", pick_list.name)
