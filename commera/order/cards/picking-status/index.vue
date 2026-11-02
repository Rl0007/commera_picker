<script>
export const plugin = { label: 'Picking' }
</script>

<script setup>
import { computed, watch } from 'vue'
import { Badge } from 'frappe-ui'
import { useCard, usePlugin, useMethodRead } from '@commera/admin'

const { record } = usePlugin()
const card = useCard()

const statusRequest = useMethodRead('commera_picker.api.get_order_picking_status', {
	params: () => ({ sales_order: record.value.name }),
})

const status = computed(() => statusRequest.data)
watch(status, (data) => card.setHidden(!data), { immediate: true })
</script>

<template>
	<div v-if="status" class="divide-y divide-outline-gray-1">
		<div class="flex items-start justify-between gap-3 pb-2">
			<div class="min-w-0">
				<p class="text-sm text-ink-gray-5">Pick List</p>
				<p class="truncate text-base text-ink-gray-8 tabular-nums">{{ status.name }}</p>
			</div>
			<Badge :label="status.state" variant="subtle" theme="gray" class="shrink-0" />
		</div>
		<div class="flex items-start justify-between gap-3 pt-2">
			<div class="min-w-0">
				<p class="text-sm text-ink-gray-5">Picker</p>
				<p class="truncate text-base text-ink-gray-8">{{ status.picker || 'Not assigned' }}</p>
			</div>
			<div class="shrink-0 text-right">
				<p class="text-sm text-ink-gray-5">Picked</p>
				<p class="text-base font-semibold text-ink-gray-9 tabular-nums">
					{{ status.picked_qty }} / {{ status.total_qty }}
				</p>
			</div>
		</div>
	</div>
</template>
