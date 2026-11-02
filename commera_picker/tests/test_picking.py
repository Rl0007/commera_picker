import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, random_string, today

from commera_picker import api, conditions
from commera_picker.install import (
	IN_PROGRESS,
	ON_HOLD,
	OPEN,
	PICKER_ROLE,
	READY_TO_SHIP,
	STATE_FIELD,
	WORKFLOW_NAME,
	after_install,
)

PICKER = "picker-one@example.com"
SECOND_PICKER = "picker-two@example.com"
OUTSIDER = "not-a-picker@example.com"
GTIN = "40063810000019"
EAN = "4006381333931"


class TestPicking(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		after_install()
		cls.company = frappe.defaults.get_global_default("company")
		cls.abbr = frappe.get_cached_value("Company", cls.company, "abbr")
		cls.bins = add_bin_warehouses(cls.company)
		cls.store_warehouse = add_warehouse(cls.company, "Picking Dispatch", f"Hauptlager - {cls.abbr}")
		cls.customer = add_customer()
		cls.first_item = add_stock_item(cls.company, cls.bins[0], 1000)
		cls.second_item = add_stock_item(cls.company, cls.bins[1], 1000)
		cls.third_item = add_stock_item(cls.company, cls.bins[2], 1000)
		add_user(PICKER, [PICKER_ROLE, "Commera User"])
		add_user(SECOND_PICKER, [PICKER_ROLE, "Commera User"])
		add_user(OUTSIDER, [])

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_released_order(self, items):
		sales_order = make_sales_order(self.company, self.customer, self.store_warehouse, items)
		return api.release_for_picking(sales_order.name), sales_order

	def test_install_runs_twice_without_changes(self):
		def snapshot():
			return {
				doctype: sorted(
					frappe.get_all(doctype, filters=filters, fields=["name", "modified"], as_list=True)
				)
				for doctype, filters in {
					"Workflow": {"name": WORKFLOW_NAME},
					"Workflow Transition": {"parent": WORKFLOW_NAME},
					"Workflow Document State": {"parent": WORKFLOW_NAME},
					"Custom Field": {"module": "Commera Picker"},
					"Custom DocPerm": {"parent": "Pick List"},
					"Role Profile": {"name": PICKER_ROLE},
					"Has Role": {"parent": PICKER_ROLE, "parenttype": "Role Profile"},
				}.items()
			}

		before = snapshot()
		after_install()
		self.assertEqual(before, snapshot())
		self.assertEqual(
			sorted(
				frappe.get_all(
					"Has Role", {"parent": PICKER_ROLE, "parenttype": "Role Profile"}, pluck="role"
				)
			),
			["Commera User", PICKER_ROLE],
		)
		self.assertEqual(frappe.db.get_value("Workflow", WORKFLOW_NAME, "send_email_alert"), 0)

	def test_release_sorts_rows_into_bins_and_refuses_a_second_release(self):
		pick_list_name, sales_order = self.make_released_order([(self.first_item, 2), (self.second_item, 1)])
		pick_list = frappe.get_doc("Pick List", pick_list_name)

		self.assertEqual(pick_list.get(STATE_FIELD), OPEN)
		self.assertEqual(pick_list.parent_warehouse, f"Hauptlager - {self.abbr}")
		self.assertEqual(pick_list.pick_manually, 1)
		self.assertEqual({row.warehouse for row in pick_list.locations}, set(self.bins[:2]))
		with self.assertRaises(frappe.ValidationError):
			api.release_for_picking(sales_order.name)

	def test_pick_partial_unavailable_and_finish(self):
		pick_list_name, sales_order = self.make_released_order(
			[(self.first_item, 3), (self.second_item, 2), (self.third_item, 1)]
		)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Sales Order",
				"reference_name": sales_order.name,
				"content": "Leave at the back door",
			}
		).insert(ignore_permissions=True)

		frappe.set_user(PICKER)
		picking = api.open_pick_list(pick_list_name)
		self.assertEqual(picking["state"], IN_PROGRESS)
		self.assertTrue(picking["is_mine"])
		self.assertEqual(
			[row["bin"] for row in picking["open_rows"]], sorted(row["bin"] for row in picking["open_rows"])
		)
		self.assertEqual(picking["comments"][0]["content"], "Leave at the back door")
		self.assertEqual(picking["comments"][0]["comment_by"], "Administrator")
		self.assertEqual(picking["shipping_address"]["pincode"], "10115")

		rows_by_item = {row["item_code"]: row["name"] for row in picking["open_rows"]}
		api.set_picked_qty(pick_list_name, rows_by_item[self.first_item], 3)
		api.set_picked_qty(pick_list_name, rows_by_item[self.second_item], 1)
		finished = api.mark_unavailable(pick_list_name, rows_by_item[self.third_item])

		self.assertEqual(finished["state"], READY_TO_SHIP)
		self.assertEqual(finished["docstatus"], 1)
		self.assertEqual(
			{row["item_code"]: (row["qty"], row["picked_qty"]) for row in finished["picked_rows"]},
			{self.first_item: (3, 3), self.second_item: (1, 1)},
		)
		self.assertEqual(finished["open_rows"], [])

		picked_qty_by_item = dict(
			frappe.get_all(
				"Sales Order Item",
				filters={"parent": sales_order.name},
				fields=["item_code", "picked_qty"],
				as_list=True,
			)
		)
		self.assertEqual(
			{item_code: flt(qty) for item_code, qty in picked_qty_by_item.items()},
			{self.first_item: 3, self.second_item: 1, self.third_item: 0},
		)
		self.assertEqual(
			frappe.get_all(
				"ToDo", {"reference_type": "Pick List", "reference_name": pick_list_name}, pluck="status"
			),
			["Closed"],
		)

	def test_order_action_and_status_follow_the_pick(self):
		sales_order = make_sales_order(
			self.company, self.customer, self.store_warehouse, [(self.first_item, 2), (self.second_item, 1)]
		)
		self.assertTrue(conditions.can_release_for_picking("Sales Order", sales_order.name))
		self.assertIsNone(api.get_order_picking_status(sales_order.name))

		message = api.release_order_for_picking(sales_order.name)
		pick_list_name = api.get_open_pick_list_for_order(sales_order.name)
		self.assertIn(pick_list_name, message)
		self.assertFalse(conditions.can_release_for_picking("Sales Order", sales_order.name))
		self.assertEqual(
			api.get_order_picking_status(sales_order.name),
			{"name": pick_list_name, "state": OPEN, "picker": None, "picked_qty": 0, "total_qty": 3},
		)

		frappe.set_user(PICKER)
		rows_by_item = {
			row["item_code"]: row["name"] for row in api.open_pick_list(pick_list_name)["open_rows"]
		}
		api.set_picked_qty(pick_list_name, rows_by_item[self.first_item], 2)
		frappe.set_user("Administrator")
		status = api.get_order_picking_status(sales_order.name)
		self.assertEqual(
			(status["state"], status["picker"], status["picked_qty"]), (IN_PROGRESS, "picker-one", 2)
		)

		frappe.set_user(PICKER)
		api.mark_unavailable(pick_list_name, rows_by_item[self.second_item])
		frappe.set_user("Administrator")
		status = api.get_order_picking_status(sales_order.name)
		self.assertEqual(
			(status["state"], status["picker"], status["picked_qty"], status["total_qty"]),
			(READY_TO_SHIP, "picker-one", 2, 3),
		)
		self.assertTrue(conditions.can_release_for_picking("Sales Order", sales_order.name))

	def test_draft_order_cannot_be_released(self):
		draft = make_sales_order(
			self.company, self.customer, self.store_warehouse, [(self.first_item, 1)], submit=False
		)
		self.assertFalse(conditions.can_release_for_picking("Sales Order", draft.name))
		with self.assertRaises(frappe.ValidationError):
			api.release_for_picking(draft.name)

	def test_second_picker_gets_already_being_picked(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 1)])

		frappe.set_user(PICKER)
		api.open_pick_list(pick_list_name)

		frappe.set_user(SECOND_PICKER)
		with self.assertRaisesRegex(api.PickListLockedError, "already being picked"):
			api.open_pick_list(pick_list_name)
		with self.assertRaises(api.PickListLockedError):
			api.set_picked_qty(
				pick_list_name,
				frappe.get_all("Pick List Item", {"parent": pick_list_name}, pluck="name")[0],
				1,
			)

	def test_hold_before_picking_returns_to_open(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 1), (self.second_item, 1)])

		frappe.set_user(PICKER)
		api.open_pick_list(pick_list_name)
		held = api.hold(pick_list_name)

		self.assertEqual(held["state"], OPEN)
		self.assertIsNone(held["assignee"])
		self.assertEqual(
			frappe.get_all(
				"ToDo", {"reference_type": "Pick List", "reference_name": pick_list_name}, pluck="status"
			),
			["Cancelled"],
		)

	def test_hold_after_picking_parks_the_order_for_any_picker(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 2), (self.second_item, 1)])

		frappe.set_user(PICKER)
		picking = api.open_pick_list(pick_list_name)
		api.set_picked_qty(pick_list_name, picking["open_rows"][0]["name"], 1)
		held = api.hold(pick_list_name)
		self.assertEqual(held["state"], ON_HOLD)
		self.assertEqual(len(held["picked_rows"]), 1)

		frappe.set_user(SECOND_PICKER)
		resumed = api.open_pick_list(pick_list_name)
		self.assertEqual(resumed["state"], IN_PROGRESS)
		self.assertEqual(resumed["assignee"], SECOND_PICKER)
		self.assertEqual(len(resumed["open_rows"]), 1)

	def test_nothing_picked_cannot_finish(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 1)])

		frappe.set_user(PICKER)
		picking = api.open_pick_list(pick_list_name)
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing was picked"):
			api.mark_unavailable(pick_list_name, picking["open_rows"][0]["name"])

	def test_picked_qty_cannot_exceed_row_qty(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 2)])

		frappe.set_user(PICKER)
		picking = api.open_pick_list(pick_list_name)
		with self.assertRaises(frappe.ValidationError):
			api.set_picked_qty(pick_list_name, picking["open_rows"][0]["name"], 3)

	def test_scan_finds_the_open_row_and_names_a_wrong_item(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 1)])

		frappe.set_user(PICKER)
		api.open_pick_list(pick_list_name)
		self.assertEqual(api.scan(pick_list_name, f"BC-{self.first_item}")["item_code"], self.first_item)
		with self.assertRaisesRegex(frappe.ValidationError, self.second_item):
			api.scan(pick_list_name, f"BC-{self.second_item}")
		with self.assertRaisesRegex(frappe.ValidationError, "No article found"):
			api.scan(pick_list_name, "NO-SUCH-BARCODE")

	def test_scan_reads_gs1_and_retail_barcodes(self):
		gtin_item = add_stock_item(self.company, self.bins[0], 10, barcode=GTIN)
		ean_item = add_stock_item(self.company, self.bins[1], 10, barcode=EAN)
		pick_list_name, _sales_order = self.make_released_order(
			[(gtin_item, 1), (ean_item, 1), (self.third_item, 1)]
		)

		frappe.set_user(PICKER)
		api.open_pick_list(pick_list_name)
		for barcode, item_code in (
			(f"(01){GTIN}", gtin_item),
			(f"]C101{GTIN}", gtin_item),
			(f"01{GTIN}\x1d10ABC", gtin_item),
			(EAN, ean_item),
			(f"]E0{EAN}", ean_item),
			(f"(01)0{EAN}", ean_item),
			(f"BC-{self.third_item}", self.third_item),
		):
			with self.subTest(barcode=barcode):
				self.assertEqual(api.scan(pick_list_name, barcode)["item_code"], item_code)

	def test_barcode_candidates_try_the_raw_code_first(self):
		self.assertEqual(api.get_barcode_candidates(f"(01){GTIN}"), [f"(01){GTIN}", f"01{GTIN}", GTIN])
		self.assertEqual(
			api.get_barcode_candidates(f"(01)0{EAN}"), [f"(01)0{EAN}", f"010{EAN}", f"0{EAN}", EAN]
		)
		self.assertEqual(api.get_barcode_candidates(EAN), [EAN])
		self.assertEqual(api.get_barcode_candidates("ABC-(01)"), ["ABC-(01)", "ABC-01"])

	def test_pick_next_opens_the_oldest_open_order(self):
		frappe.db.set_value("Pick List", {STATE_FIELD: OPEN, "docstatus": 0}, STATE_FIELD, IN_PROGRESS)
		older_pick_list, _sales_order = self.make_released_order([(self.first_item, 1)])
		self.make_released_order([(self.second_item, 1)])

		frappe.set_user(PICKER)
		self.assertEqual(api.pick_next()["name"], older_pick_list)

	def test_list_returns_rows_and_counts(self):
		pick_list_name, sales_order = self.make_released_order([(self.first_item, 1), (self.second_item, 2)])

		frappe.set_user(PICKER)
		result = api.get_pick_lists(OPEN, 0, 500)
		row = next(row for row in result["pick_lists"] if row["name"] == pick_list_name)
		self.assertEqual(row["sales_order"], sales_order.name)
		self.assertEqual(row["pincode"], "10115")
		self.assertEqual(row["article_count"], 2)
		self.assertGreaterEqual(result["counts"][OPEN], 1)
		self.assertEqual(set(result["counts"]), {OPEN, ON_HOLD, IN_PROGRESS, READY_TO_SHIP})

	def test_user_without_picker_role_is_refused(self):
		pick_list_name, _sales_order = self.make_released_order([(self.first_item, 1)])

		frappe.set_user(OUTSIDER)
		for call in (
			lambda: api.open_pick_list(pick_list_name),
			lambda: api.get_pick_list(pick_list_name),
			lambda: api.get_pick_lists(OPEN),
			lambda: api.pick_next(),
		):
			with self.assertRaises(frappe.PermissionError):
				call()


def add_warehouse(company: str, warehouse_name: str, parent_warehouse: str, is_group: int = 0) -> str:
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{warehouse_name} - {abbr}"
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": company,
				"parent_warehouse": parent_warehouse,
				"is_group": is_group,
			}
		).insert(ignore_permissions=True)
	return name


def add_bin_warehouses(company: str) -> list[str]:
	root_warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ("is", "not set")}
	)
	group = add_warehouse(company, "Hauptlager", root_warehouse, is_group=1)
	return [add_warehouse(company, bin_code, group) for bin_code in ("A-01-1", "A-01-2", "B-02-1")]


def add_customer() -> str:
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Picking Customer {random_string(6)}",
			"customer_type": "Individual",
		}
	).insert(ignore_permissions=True)
	return customer.name


def add_stock_item(company: str, warehouse: str, qty: float, barcode: str | None = None) -> str:
	item_code = f"PICK-{random_string(6).upper()}"
	barcode = barcode or f"BC-{item_code}"
	frappe.db.delete("Item Barcode", {"barcode": barcode})
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": f"Picking Article {item_code}",
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}),
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"weight_per_unit": 0.5,
			"weight_uom": "Kg",
			"barcodes": [{"barcode": barcode}],
		}
	).insert(ignore_permissions=True)
	make_stock_entry(item_code=item_code, target=warehouse, qty=qty, rate=10, company=company)
	return item_code


def make_sales_order(
	company: str, customer: str, warehouse: str, items: list[tuple[str, float]], submit: bool = True
):
	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": customer,
			"address_type": "Shipping",
			"address_line1": "Hauptstraße 1",
			"city": "Berlin",
			"pincode": "10115",
			"country": "Germany",
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}
	).insert(ignore_permissions=True)
	sales_order = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"company": company,
			"customer": customer,
			"transaction_date": today(),
			"delivery_date": add_days(today(), 3),
			"set_warehouse": warehouse,
			"shipping_address_name": address.name,
			"items": [
				{"item_code": item_code, "qty": qty, "rate": 100, "warehouse": warehouse}
				for item_code, qty in items
			],
		}
	)
	sales_order.insert(ignore_permissions=True)
	if submit:
		sales_order.submit()
	return sales_order


def add_user(email: str, roles: list[str]) -> None:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user.add_roles(*roles)
