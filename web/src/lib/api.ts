import type { JobEvent } from './types';

export class ApiError extends Error {
	constructor(public status: number, public body: unknown) {
		super(`HTTP ${status}`);
	}
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const res = await fetch(path, {
		method,
		credentials: 'same-origin',
		headers: body === undefined ? undefined : { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	const text = await res.text();
	let data: unknown = text;
	try {
		data = text ? JSON.parse(text) : null;
	} catch {
		/* keep raw text */
	}
	if (!res.ok) {
		if (res.status === 401 && location.pathname !== '/login') {
			location.assign('/login?next=' + encodeURIComponent(location.pathname + location.search));
		}
		throw new ApiError(res.status, data);
	}
	return data as T;
}

export const get = <T>(path: string) => request<T>('GET', path);
export const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {});
export const put = <T>(path: string, body: unknown) => request<T>('PUT', path, body);

const TERMINAL = ['done', 'failed'];

/** Streams job progress over SSE; on error falls back to polling every 2 s. Returns close(). */
export function events(jobId: string, onMsg: (m: JobEvent) => void): () => void {
	let closed = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	const es = new EventSource(`/api/jobs/${jobId}/events`);
	const close = () => {
		closed = true;
		es.close();
		clearTimeout(timer);
	};
	const poll = async () => {
		if (closed) return;
		try {
			const job = await get<JobEvent>(`/api/jobs/${jobId}`);
			if (closed) return;
			onMsg(job);
			if (TERMINAL.includes(job.status)) return;
		} catch {
			/* transient: keep polling */
		}
		timer = setTimeout(poll, 2000);
	};
	es.onmessage = (e) => {
		const m = JSON.parse(e.data) as JobEvent;
		onMsg(m);
		if (TERMINAL.includes(m.status)) close();
	};
	es.onerror = () => {
		es.close();
		timer = setTimeout(poll, 2000);
	};
	return close;
}
