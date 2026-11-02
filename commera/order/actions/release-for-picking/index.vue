<script>
export const plugin = {
	label: 'Release for picking',
	icon: 'package',
	condition: 'commera_picker.conditions.can_release_for_picking',
	method: 'commera_picker.api.release_order_for_picking',
}
</script>
