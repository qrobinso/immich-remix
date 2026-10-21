import { get } from './api';
import type { Status } from './types';

export const app = $state<{ status: Status | null; failed: boolean; loading: boolean }>({ status: null, failed: false, loading: false });

export async function loadStatus() {
	app.loading = true;
	try {
		app.status = await get<Status>('/api/status');
		app.failed = false;
	} catch {
		app.failed = true; // 401 already redirected; anything else is the app server itself being down
	} finally {
		app.loading = false;
	}
}
