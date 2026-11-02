import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission, update_permission_property

MODULE = "Commera Picker"
PICKER_ROLE = "Picker"
COMMERA_USER_ROLE = "Commera User"
WORKFLOW_NAME = "Pick List Picking"
STATE_FIELD = "picking_state"

OPEN = "Open"
IN_PROGRESS = "In Progress"
ON_HOLD = "On Hold"
READY_TO_SHIP = "Ready to Ship"

START_PICKING = "Start Picking"
PUT_ON_HOLD = "Put on Hold"
RETURN_TO_OPEN = "Return to Open"
RESUME_PICKING = "Resume Picking"
FINISH_PICKING = "Finish Picking"
MARK_READY_TO_SHIP = "Mark Ready to Ship"

STATES = [
	{"state": OPEN, "doc_status": "0", "allow_edit": "Stock User", "style": "Warning"},
	{"state": IN_PROGRESS, "doc_status": "0", "allow_edit": PICKER_ROLE, "style": "Primary"},
	{"state": ON_HOLD, "doc_status": "0", "allow_edit": "Stock User", "style": "Danger"},
	{"state": READY_TO_SHIP, "doc_status": "1", "allow_edit": "Stock Manager", "style": "Success"},
]

TRANSITIONS = [
	(OPEN, START_PICKING, IN_PROGRESS, PICKER_ROLE),
	(IN_PROGRESS, PUT_ON_HOLD, ON_HOLD, PICKER_ROLE),
	(IN_PROGRESS, RETURN_TO_OPEN, OPEN, PICKER_ROLE),
	(ON_HOLD, RESUME_PICKING, IN_PROGRESS, PICKER_ROLE),
	(IN_PROGRESS, FINISH_PICKING, READY_TO_SHIP, PICKER_ROLE),
	(OPEN, MARK_READY_TO_SHIP, READY_TO_SHIP, "Stock Manager"),
	(OPEN, MARK_READY_TO_SHIP, READY_TO_SHIP, "System Manager"),
]


def after_install():
	add_roles()
	add_custom_fields()
	add_picker_permissions()
	add_workflow()


def add_roles():
	for role_name in (PICKER_ROLE, COMMERA_USER_ROLE):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)

	if not frappe.db.exists("Role Profile", PICKER_ROLE):
		role_profile = frappe.new_doc("Role Profile")
		role_profile.role_profile = PICKER_ROLE
		for role_name in (COMMERA_USER_ROLE, PICKER_ROLE):
			role_profile.append("roles", {"role": role_name})
		role_profile.insert(ignore_permissions=True)


def add_custom_fields():
	create_custom_fields(
		{
			"Pick List": [
				{
					"fieldname": STATE_FIELD,
					"label": "Picking State",
					"fieldtype": "Link",
					"options": "Workflow State",
					"insert_after": "status",
					"hidden": 1,
					"allow_on_submit": 1,
					"no_copy": 1,
					"module": MODULE,
				}
			],
			"Pick List Item": [
				{
					"fieldname": "picking_done",
					"label": "Picking Done",
					"fieldtype": "Check",
					"insert_after": "picked_qty",
					"hidden": 1,
					"allow_on_submit": 1,
					"no_copy": 1,
					"module": MODULE,
				}
			],
		},
		update=False,
	)


def add_picker_permissions():
	if frappe.db.exists("Custom DocPerm", {"parent": "Pick List", "role": PICKER_ROLE, "permlevel": 0}):
		return

	add_permission("Pick List", PICKER_ROLE)
	for permission_type in ("write", "submit"):
		update_permission_property("Pick List", PICKER_ROLE, 0, permission_type, 1)


def add_workflow():
	for state in STATES:
		if not frappe.db.exists("Workflow State", state["state"]):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state["state"], "style": state["style"]}
			).insert(ignore_permissions=True)

	for action in dict.fromkeys(transition[1] for transition in TRANSITIONS):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = WORKFLOW_NAME
	workflow.document_type = "Pick List"
	workflow.workflow_state_field = STATE_FIELD
	workflow.is_active = 1
	workflow.override_status = 1
	workflow.send_email_alert = 0
	for state in STATES:
		workflow.append(
			"states",
			{
				"state": state["state"],
				"doc_status": state["doc_status"],
				"allow_edit": state["allow_edit"],
				"send_email": 0,
			},
		)
	for state, action, next_state, role in TRANSITIONS:
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": role,
				"allow_self_approval": 1,
			},
		)
	workflow.insert(ignore_permissions=True)
