<script setup>
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { ErrorMessage } from 'frappe-ui'
import { __ } from '@commera/admin'
import { Html5Qrcode } from 'html5-qrcode'

const emit = defineEmits(['scan'])
const readerId = `barcode-reader-${useId()}`
const cameraError = ref('')
let scanner = null

onMounted(async () => {
	scanner = new Html5Qrcode(readerId)
	try {
		await scanner.start(
			{ facingMode: 'environment' },
			{ fps: 10, qrbox: { width: 250, height: 150 } },
			async (barcode) => {
				await stopScanner()
				emit('scan', barcode)
			}
		)
	} catch {
		cameraError.value = window.isSecureContext
			? __('The camera could not be started. Allow camera access and try again.')
			: __('The camera needs an HTTPS address. Use the hardware scanner instead.')
	}
})

async function stopScanner() {
	if (scanner?.isScanning) await scanner.stop()
}

onBeforeUnmount(stopScanner)
</script>

<template>
	<div class="flex flex-col gap-3">
		<div :id="readerId" class="overflow-hidden rounded-5 bg-surface-gray-2" />
		<ErrorMessage v-if="cameraError" :message="cameraError" />
	</div>
</template>
