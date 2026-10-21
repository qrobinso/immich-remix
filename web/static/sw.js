// App shell only. Never caches /api/* (photos, status, jobs all go to the network).
const CACHE = 'shell-v1';
self.addEventListener('install', (e) => {
	e.waitUntil(caches.open(CACHE).then((c) => c.add('/')));
	self.skipWaiting();
});
self.addEventListener('activate', (e) => {
	e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
	const url = new URL(e.request.url);
	if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
	if (url.pathname.startsWith('/_app/immutable/')) {
		e.respondWith(caches.open(CACHE).then(async (c) => (await c.match(e.request)) ?? fetch(e.request).then((r) => (r.ok && c.put(e.request, r.clone()), r))));
	} else if (e.request.mode === 'navigate') {
		e.respondWith(fetch(e.request).catch(() => caches.match('/')));
	}
});
