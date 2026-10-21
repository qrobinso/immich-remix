import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ApiError, events, get } from './api';

const json = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

beforeEach(() => {
	vi.useFakeTimers();
	vi.stubGlobal('location', { pathname: '/history', search: '?p=2', assign: vi.fn() });
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

test('401 redirects to /login', async () => {
	vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'no' }, 401)));
	get('/api/status').catch(() => {});
	await vi.advanceTimersByTimeAsync(0);
	expect(location.assign).toHaveBeenCalledWith('/login?next=' + encodeURIComponent('/history?p=2'));
});

test('401 on /login does not redirect', async () => {
	vi.stubGlobal('location', { pathname: '/login', search: '', assign: vi.fn() });
	vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Wrong password' }, 401)));
	await expect(get('/api/x')).rejects.toBeInstanceOf(ApiError);
	expect(location.assign).not.toHaveBeenCalled();
});

test('non-2xx throws ApiError with status and body', async () => {
	vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'bad' }, 422)));
	await expect(get('/api/x')).rejects.toMatchObject({ status: 422, body: { detail: 'bad' } });
});

test('events falls back to polling', async () => {
	let es: { onerror?: () => void; onmessage?: (e: { data: string }) => void; close: () => void };
	class FakeES {
		onerror?: () => void;
		onmessage?: (e: { data: string }) => void;
		close = vi.fn();
		constructor() {
			es = this;
		}
	}
	vi.stubGlobal('EventSource', FakeES);
	const states = ['running', 'running', 'done'];
	const fetchMock = vi.fn(async () => json({ id: 'j1', status: states.shift() }));
	vi.stubGlobal('fetch', fetchMock);
	const msgs: any[] = [];
	events('j1', (m) => msgs.push(m));
	es!.onerror!();
	expect(es!.close).toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(2000);
	await vi.advanceTimersByTimeAsync(2000);
	await vi.advanceTimersByTimeAsync(2000);
	await vi.advanceTimersByTimeAsync(10000);
	expect(fetchMock).toHaveBeenCalledTimes(3);
	expect(msgs.map((m) => m.status)).toEqual(['running', 'running', 'done']);
});
