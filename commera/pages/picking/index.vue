<script>
export const plugin = { label: 'Picking', icon: 'package', order: 1 }
</script>

<script setup>
import { computed, ref, watch } from 'vue'
import { Badge, Button, TabButtons } from 'frappe-ui'
import {
	EmptyState,
	ListPagination,
	ListSkeleton,
	__,
	shortDate,
	useMethodAction,
	useMethodRead,
	usePage,
	usePlugin,
	usePolling,
} from '@commera/admin'
import { STATES, submitRequest, useLogOut } from '../../shared/picking'

const { navigate } = usePlugin()
const logOut = useLogOut()
const state = ref(STATES.open)
const page = ref(1)
const pageSize = ref(20)

const listRequest = useMethodRead('commera_picker.api.get_pick_lists', {
	params: () => ({
		state: state.value,
		start: (page.value - 1) * pageSize.value,
		page_length: pageSize.value,
	}),
	refetch: true,
})
const openRequest = useMethodAction('commera_picker.api.open_pick_list')
const pickNextRequest = useMethodAction('commera_picker.api.pick_next')
usePolling(listRequest, { every: 30000 })

watch(state, () => (page.value = 1))

const counts = computed(() => listRequest.data?.counts ?? {})
const pickLists = computed(() => listRequest.data?.pick_lists ?? [])
const total = computed(() => counts.value[state.value] ?? 0)
const tabs = computed(() =>
	Object.values(STATES).map((value) => ({ label: `${__(value)} ${counts.value[value] ?? 0}`, value }))
)

async function openPickList(pickList) {
	if (state.value !== STATES.readyToShip && !(await submitRequest(openRequest, { name: pickList.name }))) {
		return listRequest.reload()
	}
	navigate(`picking/${pickList.name}`)
}

async function pickNext() {
	if (!(await submitRequest(pickNextRequest))) return listRequest.reload()
	navigate(`picking/${pickNextRequest.data.name}`)
}

const pageHeader = usePage()
pageHeader.setTitle(__('Picking'))
pageHeader.setActions([
	{
		label: __('Pick next order'),
		icon: 'package',
		variant: 'solid',
		loading: () => pickNextRequest.loading,
		onClick: pickNext,
	},
	{ label: __('Refresh'), icon: 'refresh-cw', onClick: () => listRequest.reload() },
	{ label: __('Switch picker'), icon: 'user', onClick: logOut },
])
</script>

<template>
	<div class="flex flex-col gap-3">
		<div class="overflow-x-auto">
			<TabButtons v-model="state" size="sm" :options="tabs" />
		</div>

		<ListSkeleton v-if="listRequest.loading && !listRequest.data" :columns="2" />

		<ul
			v-else-if="pickLists.length"
			class="divide-y divide-outline-gray-1 rounded-5 border border-outline-gray-1 bg-surface-base"
		>
			<li v-for="pickList in pickLists" :key="pickList.name">
				<button
					type="button"
					class="flex w-full items-center gap-3 px-3 py-3 text-left hover:bg-surface-gray-1 disabled:opacity-60"
					:disabled="openRequest.loading"
					@click="openPickList(pickList)"
				>
					<div class="flex min-w-0 flex-1 flex-col gap-1">
						<div class="flex items-center gap-2">
							<span
								class="rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-sm font-medium text-ink-gray-8 tabular-nums"
							>
								#{{ pickList.sales_order || pickList.name }}
							</span>
							<span class="truncate text-base font-medium text-ink-gray-9">{{
								pickList.customer
							}}</span>
						</div>
						<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-gray-5">
							<span class="tabular-nums">{{ shortDate(pickList.transaction_date) }}</span>
							<span v-if="pickList.pincode" class="flex items-center gap-1 tabular-nums">
								<span class="lucide-map-pin size-3.5" aria-hidden="true" />
								{{ pickList.pincode }}
							</span>
							<span v-if="pickList.assignee_name" class="flex items-center gap-1">
								<span class="lucide-user size-3.5" aria-hidden="true" />
								{{ pickList.assignee_name }}
							</span>
						</div>
					</div>
					<Badge
						size="lg"
						variant="solid"
						class="tabular-nums"
						:label="String(pickList.article_count)"
						:aria-label="__('Articles: {0}', [pickList.article_count])"
					/>
				</button>
			</li>
		</ul>

		<EmptyState
			v-else
			icon="lucide-package"
			:title="__('No orders in {0}', [__(state)])"
			:description="__('Orders show here once the office releases them for picking.')"
		/>

		<ListPagination
			v-if="total > pageSize"
			v-model:page="page"
			v-model:page-size="pageSize"
			:total="total"
		/>

		<div
			v-if="state === STATES.open && pickLists.length"
			class="sticky bottom-0 bg-surface-base py-3 sm:hidden"
		>
			<Button
				class="w-full"
				size="lg"
				variant="solid"
				:label="__('Pick next order')"
				:loading="pickNextRequest.loading"
				@click="pickNext"
			/>
		</div>
	</div>
</template>
