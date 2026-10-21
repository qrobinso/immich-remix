<script lang="ts">
	import { page } from '$app/state';
	const items = [
		{ href: '/', label: 'Library', d: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z' },
		{ href: '/history', label: 'History', d: 'M12 7v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4' },
		{ href: '/settings', label: 'Settings', d: 'M4 7h10M18 7h2M4 17h2M10 17h10M16 4v6M8 14v6' }
	];
	const current = (href: string) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href));
</script>

<nav aria-label="Main">
	{#each items as it}
		<a href={it.href} aria-current={current(it.href) ? 'page' : undefined}>
			<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={it.d} /></svg>
			<span class="t-small">{it.label}</span>
		</a>
	{/each}
</nav>

<style>
	nav {
		position: fixed; inset: auto 0 0 0; display: flex; justify-content: space-around;
		padding: 4px 8px calc(4px + env(safe-area-inset-bottom)); background: color-mix(in srgb, var(--bg) 88%, transparent);
		backdrop-filter: blur(16px); border-top: 1px solid var(--line); z-index: 10;
	}
	a {
		flex: 1; max-width: 160px; min-height: 48px; display: flex; flex-direction: column; align-items: center;
		justify-content: center; gap: 2px; color: var(--muted); text-decoration: none; transition: color 150ms;
	}
	a[aria-current='page'] { color: var(--accent); font-weight: 600; }
</style>
