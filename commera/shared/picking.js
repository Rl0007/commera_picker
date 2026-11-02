import { useMethodAction } from '@commera/admin'

export const STATES = {
	open: 'Open',
	onHold: 'On Hold',
	inProgress: 'In Progress',
	readyToShip: 'Ready to Ship',
}

export function useLogOut() {
	const logOutRequest = useMethodAction('logout')
	return async function logOut() {
		await logOutRequest.submit()
		window.location.assign(`/login?redirect-to=${encodeURIComponent(window.location.pathname)}`)
	}
}

export function textFromHtml(html) {
	return new DOMParser().parseFromString(html || '', 'text/html').body.textContent.trim()
}

export function errorText(error) {
	const message = error?.messages?.[0] || error?.message || ''
	return textFromHtml(message.replace(/^\w+Error: /, ''))
}

export async function submitRequest(request, params) {
	try {
		await request.submit(params)
	} catch {
		return false
	}
	return !request.error
}
