<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Alert, Badge, Button, Dialog, TextInput } from 'frappe-ui'
import {
	EmptyState,
	ListSkeleton,
	__,
	shortDate,
	useMethodAction,
	useMethodRead,
	usePage,
	usePlugin,
} from '@commera/admin'
import BarcodeScanner from '../../components/BarcodeScanner.vue'
import { STATES, errorText, submitRequest, textFromHtml } from '../../shared/picking'

const props = defineProps({ id: String })
const { navigate, toast } = usePlugin()

const pickListRequest = useMethodRead('commera_picker.api.get_pick_list', {
	params: () => ({ name: props.id }),
})
const openRequest = useMethodAction('commera_picker.api.open_pick_list')
const pickRequest = useMethodAction('commera_picker.api.set_picked_qty')
const unavailableRequest = useMethodAction('commera_picker.api.mark_unavailable')
const holdRequest = useMethodAction('commera_picker.api.hold')
const scanRequest = useMethodAction('commera_picker.api.scan', { quiet: true })

const pickList = ref(null)
watch(
	() => pickListRequest.data,
	(data) => data && (pickList.value = data),
	{ immediate: true }
)
const canPick = computed(() => pickList.value?.is_mine && pickList.value.state === STATES.inProgress)
const canStart = computed(() => [STATES.open, STATES.onHold].includes(pickList.value?.state))
const pickedByOther = computed(() => pickList.value?.assignee && !pickList.value.is_mine)
const isReadyToShip = computed(() => pickList.value?.state === STATES.readyToShip)
const allRows = computed(() => [...(pickList.value?.open_rows ?? []), ...(pickList.value?.picked_rows ?? [])])
const totalWeight = computed(() =>
	allRows.value.reduce(
		(weight, row) => weight + row.weight * (row.picking_done ? row.picked_qty : row.qty),
		0
	)
)
const weightUom = computed(() => allRows.value.find((row) => row.weight_uom)?.weight_uom ?? '')
const comments = computed(() =>
	(pickList.value?.comments ?? []).map((comment) => ({ ...comment, text: textFromHtml(comment.content) }))
)

const selectedRow = ref(null)
const pickedQty = ref(1)
const commentsOpen = ref(false)
const cameraOpen = ref(false)
const scanError = ref('')

const pageHeader = usePage()
pageHeader.setTitle(() => (pickList.value?.sales_order ? `#${pickList.value.sales_order}` : props.id))
pageHeader.setBreadcrumbs([{ label: __('Picking'), to: 'picking' }])

async function submitAndAdopt(request, params) {
	if (!(await submitRequest(request, params))) return false
	pickList.value = request.data
	return true
}

function startPicking() {
	return submitAndAdopt(openRequest, { name: props.id })
}

function selectRow(row) {
	if (!canPick.value) return
	scanError.value = ''
	selectedRow.value = row
	pickedQty.value = row.qty
}

async function confirmPicked() {
	const params = { name: props.id, row_name: selectedRow.value.name, qty: pickedQty.value }
	if (await submitAndAdopt(pickRequest, params)) finishSelection()
}

async function markUnavailable() {
	const params = { name: props.id, row_name: selectedRow.value.name }
	if (await submitAndAdopt(unavailableRequest, params)) finishSelection()
}

function finishSelection() {
	selectedRow.value = null
	if (isReadyToShip.value) toast.success(__('Order is ready to ship'))
}

async function holdOrder() {
	if (!(await submitRequest(holdRequest, { name: props.id }))) return
	toast.success(__('Order put on hold'))
	navigate('picking')
}

async function scanBarcode(barcode) {
	cameraOpen.value = false
	scanError.value = ''
	if (!(await submitRequest(scanRequest, { name: props.id, barcode }))) {
		scanError.value = errorText(scanRequest.error) || __('No article found for barcode {0}', [barcode])
		return
	}
	selectRow(scanRequest.data)
}

let scannerBuffer = ''
let scannerTimer = null

function readHardwareScanner(event) {
	if (!canPick.value || selectedRow.value || cameraOpen.value) return
	if (event.target.closest?.('input, textarea, [contenteditable]')) return
	if (event.key === 'Enter') {
		const barcode = scannerBuffer.trim()
		scannerBuffer = ''
		if (barcode.length >= 3) scanBarcode(barcode)
		return
	}
	if (event.key.length !== 1) return
	scannerBuffer += event.key
	clearTimeout(scannerTimer)
	scannerTimer = setTimeout(() => (scannerBuffer = ''), 300)
}

onMounted(() => window.addEventListener('keydown', readHardwareScanner))
onBeforeUnmount(() => {
	window.removeEventListener('keydown', readHardwareScanner)
	clearTimeout(scannerTimer)
})

function formatQty(qty) {
	return Number(qty).toLocaleString(undefined, { maximumFractionDigits: 3 })
}
</script>

<template>
	<ListSkeleton v-if="pickListRequest.loading && !pickList" :columns="2" />

	<EmptyState v-else-if="!pickList" icon="lucide-package" :title="__('Order not found')" />

	<div v-else class="mx-auto flex w-full max-w-2xl flex-col gap-4 pb-4">
		<section class="rounded-5 border border-outline-gray-1 bg-surface-base p-3">
			<div class="flex items-start gap-3">
				<div class="min-w-0 flex-1">
					<p class="text-xs font-medium uppercase text-ink-gray-5">{{ __('Shipping') }}</p>
					<p class="mt-1 truncate text-base font-semibold text-ink-gray-9">
						{{ pickList.shipping_address?.address_title || pickList.customer }}
					</p>
					<p v-if="pickList.shipping_address" class="text-sm text-ink-gray-6">
						{{ pickList.shipping_address.address_line1 }}
						<template v-if="pickList.shipping_address.address_line2">
							, {{ pickList.shipping_address.address_line2 }}
						</template>
					</p>
					<p v-if="pickList.shipping_address" class="text-sm text-ink-gray-6">
						{{ pickList.shipping_address.pincode }} {{ pickList.shipping_address.city }},
						{{ pickList.shipping_address.country }}
					</p>
				</div>
				<Button
					v-if="comments.length"
					variant="subtle"
					:label="__('Info')"
					:aria-label="__('{0} comments on this order', [comments.length])"
					@click="commentsOpen = true"
				>
					<template #suffix>
						<span class="size-2 rounded-full bg-surface-red-6" aria-hidden="true" />
					</template>
				</Button>
			</div>
			<div
				class="mt-3 flex items-center justify-between border-t border-outline-gray-1 pt-2 text-sm text-ink-gray-6"
			>
				<span class="flex items-center gap-2">
					<Badge :label="__(pickList.state)" variant="subtle" />
					<span v-if="pickList.assignee_name && !pickList.is_mine">{{
						pickList.assignee_name
					}}</span>
				</span>
				<span class="tabular-nums">{{ formatQty(totalWeight) }} {{ weightUom }}</span>
			</div>
		</section>

		<Alert v-if="scanError" theme="red" :title="__('Wrong article')" :description="scanError" />

		<Alert
			v-if="pickedByOther && !isReadyToShip"
			theme="amber"
			:title="__('This order is already being picked by {0}', [pickList.assignee_name])"
		/>

		<Alert
			v-if="isReadyToShip"
			theme="green"
			:title="__('Ready to ship')"
			:description="
				__('Picked articles are booked on the order. Anything not picked stays open on it.')
			"
		/>

		<section v-if="pickList.open_rows.length">
			<h2 class="mb-2 px-1 text-xs font-medium uppercase text-ink-gray-5">
				{{ __('Open articles ({0})', [pickList.open_rows.length]) }}
			</h2>
			<ul class="divide-y divide-outline-gray-1 rounded-5 border border-outline-gray-1 bg-surface-base">
				<li v-for="row in pickList.open_rows" :key="row.name">
					<button
						type="button"
						class="flex w-full items-center gap-3 px-3 py-3 text-left enabled:hover:bg-surface-gray-1"
						:disabled="!canPick"
						@click="selectRow(row)"
					>
						<div class="flex min-w-0 flex-1 flex-col gap-1">
							<div class="flex items-center gap-2">
								<span
									class="flex items-center gap-1 rounded-4 bg-surface-blue-2 px-1.5 py-0.5 text-sm font-medium text-ink-blue-7"
								>
									<span class="lucide-map-pin size-3.5" aria-hidden="true" />
									{{ row.bin }}
								</span>
								<span
									class="flex items-center gap-1 rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-sm text-ink-gray-6 tabular-nums"
									:title="__('Stock in this bin')"
								>
									<span class="lucide-boxes size-3.5" aria-hidden="true" />
									{{ formatQty(row.stock_in_bin) }}
								</span>
							</div>
							<p class="truncate text-base font-medium text-ink-gray-9">{{ row.item_name }}</p>
							<p class="truncate text-sm text-ink-gray-5">
								{{ row.item_code }}
								<template v-if="row.weight">
									· {{ formatQty(row.weight) }} {{ row.weight_uom }}</template
								>
							</p>
						</div>
						<Badge
							size="lg"
							variant="solid"
							theme="blue"
							class="tabular-nums"
							:label="formatQty(row.qty)"
						/>
						<img
							v-if="row.image"
							:src="row.image"
							:alt="row.item_name"
							class="size-12 shrink-0 rounded-4 object-cover"
						/>
						<span
							v-else
							class="flex size-12 shrink-0 items-center justify-center rounded-4 bg-surface-gray-2 text-ink-gray-4"
						>
							<span class="lucide-package size-5" aria-hidden="true" />
						</span>
					</button>
				</li>
			</ul>
		</section>

		<section v-if="pickList.picked_rows.length">
			<h2 class="mb-2 px-1 text-xs font-medium uppercase text-ink-gray-5">
				{{ __('Picked articles ({0})', [pickList.picked_rows.length]) }}
			</h2>
			<ul class="divide-y divide-outline-gray-1 rounded-5 border border-outline-gray-1 bg-surface-base">
				<li
					v-for="row in pickList.picked_rows"
					:key="row.name"
					class="flex items-center gap-3 px-3 py-3"
				>
					<div class="flex min-w-0 flex-1 flex-col gap-1">
						<p class="truncate text-base font-medium text-ink-gray-9">{{ row.item_name }}</p>
						<p class="truncate text-sm text-ink-gray-5">{{ row.bin }} · {{ row.item_code }}</p>
					</div>
					<Badge v-if="!row.picked_qty" theme="red" variant="subtle" :label="__('Not available')" />
					<span v-else class="text-sm font-semibold text-ink-gray-8 tabular-nums">
						{{ formatQty(row.picked_qty) }} / {{ formatQty(row.qty) }}
					</span>
				</li>
			</ul>
		</section>

		<div
			v-if="canPick || canStart"
			class="sticky bottom-0 flex gap-2 rounded-5 border border-outline-gray-1 bg-surface-base p-3"
		>
			<template v-if="canPick">
				<Button
					class="flex-1"
					size="lg"
					:label="__('Put on hold')"
					:loading="holdRequest.loading"
					@click="holdOrder"
				/>
				<Button
					class="flex-1"
					size="lg"
					variant="solid"
					icon-left="lucide-camera"
					:label="__('Scan')"
					:loading="scanRequest.loading"
					@click="cameraOpen = true"
				/>
			</template>
			<Button
				v-else
				class="flex-1"
				size="lg"
				variant="solid"
				:label="__('Start picking')"
				:loading="openRequest.loading"
				@click="startPicking"
			/>
		</div>

		<Button v-if="isReadyToShip" size="lg" :label="__('Back to picking')" @click="navigate('picking')" />
	</div>

	<Dialog
		:open="Boolean(selectedRow)"
		:title="selectedRow?.item_name"
		size="sm"
		@update:open="(open) => !open && (selectedRow = null)"
	>
		<template v-if="selectedRow" #default>
			<div class="flex flex-col gap-3">
				<p class="text-sm text-ink-gray-6">{{ selectedRow.bin }} · {{ selectedRow.item_code }}</p>
				<p v-if="selectedRow.qty === 1" class="text-base text-ink-gray-8">
					{{ __('Pick 1 {0}?', [selectedRow.uom]) }}
				</p>
				<TextInput
					v-else
					v-model="pickedQty"
					type="number"
					inputmode="decimal"
					:min="0"
					:max="selectedRow.qty"
					:label="__('Picked quantity of {0} {1}', [formatQty(selectedRow.qty), selectedRow.uom])"
				/>
			</div>
		</template>
		<template v-if="selectedRow" #actions>
			<div class="flex flex-col gap-2">
				<Button
					size="lg"
					variant="solid"
					:label="selectedRow.qty === 1 ? __('Confirm picked') : __('Save picked quantity')"
					:loading="pickRequest.loading"
					@click="confirmPicked"
				/>
				<Button
					size="lg"
					theme="red"
					variant="subtle"
					:label="__('Not available')"
					:loading="unavailableRequest.loading"
					@click="markUnavailable"
				/>
			</div>
		</template>
	</Dialog>

	<Dialog v-model:open="commentsOpen" :title="__('Info')" size="sm">
		<template #default>
			<ul class="flex flex-col gap-3">
				<li v-for="comment in comments" :key="comment.creation" class="text-base text-ink-gray-8">
					<p class="whitespace-pre-line">{{ comment.text }}</p>
					<p class="mt-1 text-sm text-ink-gray-5">
						{{ comment.comment_by }} · {{ shortDate(comment.creation) }}
					</p>
				</li>
			</ul>
		</template>
	</Dialog>

	<Dialog v-model:open="cameraOpen" :title="__('Scan article')" size="sm">
		<template #default>
			<BarcodeScanner v-if="cameraOpen" @scan="scanBarcode" />
		</template>
	</Dialog>
</template>
