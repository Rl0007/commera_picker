<script setup>
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { ErrorMessage } from 'frappe-ui'
import { __ } from '@commera/admin'
import { Html5Qrcode, Html5QrcodeSupportedFormats } from 'html5-qrcode'

const emit = defineEmits(['scan'])
const readerId = `barcode-reader-${useId()}`
const cameraError = ref('')
let scanner = null

const SUPPORTED_FORMATS = [
	Html5QrcodeSupportedFormats.EAN_13,
	Html5QrcodeSupportedFormats.EAN_8,
	Html5QrcodeSupportedFormats.UPC_A,
	Html5QrcodeSupportedFormats.UPC_E,
	Html5QrcodeSupportedFormats.CODE_128,
	Html5QrcodeSupportedFormats.CODE_39,
	Html5QrcodeSupportedFormats.QR_CODE,
]
const VIDEO_CONSTRAINTS = {
	facingMode: 'environment',
	width: { ideal: 1280 },
	height: { ideal: 720 },
	advanced: [{ focusMode: 'continuous' }],
}

onMounted(async () => {
	scanner = new Html5Qrcode(readerId, {
		formatsToSupport: SUPPORTED_FORMATS,
		useBarCodeDetectorIfSupported: true,
		verbose: false,
	})
	try {
		await scanner.start(
			{ facingMode: 'environment' },
			{
				fps: 10,
				qrbox: (width, height) => ({
					width: Math.floor(width * 0.9),
					height: Math.floor(height * 0.4),
				}),
				videoConstraints: VIDEO_CONSTRAINTS,
			},
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
