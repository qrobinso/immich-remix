<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import BottomNav from '#lib/components/BottomNav.svelte';
	import { app, loadStatus } from '#lib/status.svelte.ts';

	let { children } = $props();
	const onLogin = $derived(page.url.pathname === '/login');
	const immichDown = $derived(app.status !== null && !app.status.immich.ok);

	onMount(() => {
		if (!onLogin) loadStatus();
		if ('serviceWorker' in navigator && isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
	});
</script>

<main class:with-nav={!onLogin}>
	{#if page.url.pathname === '/' && immichDown}
		<section class="banner" role="alert">
			<h1 class="t-title">Immich is unreachable</h1>
			<p class="muted">{app.status?.immich.error}</p>
			<button class="btn btn-primary" onclick={loadStatus} disabled={app.loading}>{app.loading ? 'Checking…' : 'Retry'}</button>
			<p class="t-small muted">History and Settings still work.</p>
		</section>
	{:else}
		{@render children()}
	{/if}
</main>
{#if !onLogin}<BottomNav />{/if}

<style>
	main { min-height: 100dvh; padding-top: env(safe-area-inset-top); }
	main.with-nav { padding-bottom: calc(56px + env(safe-area-inset-bottom)); }
	.banner {
		min-height: calc(100dvh - 56px - env(safe-area-inset-bottom)); display: flex; flex-direction: column;
		align-items: center; justify-content: center; gap: 12px; padding: 24px; text-align: center;
	}
	.banner h1 { margin: 0; }
	.banner p { margin: 0; max-width: 32ch; }
</style>
