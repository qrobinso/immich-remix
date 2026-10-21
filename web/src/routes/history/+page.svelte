<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { events, get, post } from '#lib/api.ts';
	import { resultSrc, sourceThumb } from '#lib/results.ts';
	import type { History, Job } from '#lib/types.ts';

	let items = $state<Job[]>([]);
	let next = $state<number | null>(1);
	let loading = $state(false);
	let failed = $state(false);
	let sentinel: HTMLElement | undefined = $state();
	let retrying = $state<string | null>(null);
	const watching = new Map<string, () => void>();

	async function more() {
		if (loading || next === null) return;
		loading = true;
		try {
			const h = await get<History>(`/api/history?page=${next}`);
			items = [...items, ...h.items.filter((j) => !items.some((i) => i.id === j.id))];
			next = h.next_page;
			failed = false;
			h.items.forEach(watch);
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}
	// Running jobs refresh themselves when they finish.
	function watch(j: Job) {
		if ((j.status !== 'queued' && j.status !== 'running') || watching.has(j.id)) return;
		watching.set(j.id, events(j.id, async (m) => {
			if (m.status !== 'done' && m.status !== 'failed') return;
			watching.get(j.id)?.();
			watching.delete(j.id);
			try { const fresh = await get<Job>(`/api/jobs/${j.id}`); items = items.map((i) => (i.id === j.id ? fresh : i)); } catch { /* next visit reloads */ }
		}));
	}
	onDestroy(() => watching.forEach((close) => close()));

	$effect(() => {
		items.length;
		if (!sentinel || next === null || failed) return;
		const io = new IntersectionObserver((e) => e[0].isIntersecting && more(), { rootMargin: '600px' });
		io.observe(sentinel);
		return () => io.disconnect();
	});
	onMount(more);

	const first = (j: Job) => j.results.find((r) => !r.discarded);
	const badge = (j: Job) => (j.status === 'queued' ? 'running' : j.status === 'failed' ? 'failed' : j.results.some((r) => r.saved) ? 'saved' : 'unsaved');
	const dim = (j: Job) => j.status !== 'done' || !first(j);
	function thumb(j: Job) {
		const r = first(j);
		return dim(j) || !r || j.media_type === 'video' ? sourceThumb(j) : resultSrc(j, r);
	}
	async function retry(j: Job) {
		retrying = j.id;
		try {
			const { id } = await post<{ id: string }>(`/api/jobs/${j.id}/retry`);
			await goto(`/review/${id}`);
		} catch {
			retrying = null;
		}
	}
</script>

<svelte:head><title>History</title></svelte:head>

<h1 class="t-title">History</h1>

{#if !items.length && !loading && next === null && !failed}
	<p class="empty muted">No remixes yet. Pick a photo or video in the Library to make one.</p>
{/if}

<ul>
	{#each items as j (j.id)}
		<li>
			{#if j.status === 'failed'}
				<div class="tile"><img src={thumb(j)} alt="" class="dim" loading="lazy" /></div>
				<span class="badge failed t-small">failed</span>
				<button class="retry btn" onclick={() => retry(j)} disabled={retrying === j.id} title={j.error_message ?? undefined}>Retry</button>
			{:else}
				<a class="tile" href="/review/{j.id}" aria-label="{j.style_name ?? 'Custom'}, {badge(j)}">
					<img src={thumb(j)} alt="" class:dim={dim(j)} loading="lazy" />
					{#if j.media_type === 'video'}<span class="play" aria-hidden="true">▶</span>{/if}
					<span class="badge {badge(j)} t-small">{badge(j)}</span>
				</a>
			{/if}
			<p class="name t-small">{j.style_name ?? 'Custom'}</p>
			{#if j.status === 'failed' && j.error_message}<p class="err t-small muted">{j.error_message}</p>{/if}
		</li>
	{/each}
</ul>
{#if failed}<div class="more"><p class="muted">Couldn't load History.</p><button class="btn" onclick={more}>Retry</button></div>{/if}
<div bind:this={sentinel} aria-hidden="true"></div>

<style>
	h1 { margin: 0; padding: 16px 12px 8px; }
	.empty { padding: 24px 16px; }
	ul { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; margin: 0; padding: 0; list-style: none; }
	@media (min-width: 600px) { ul { grid-template-columns: repeat(5, 1fr); } }
	@media (min-width: 900px) { ul { grid-template-columns: repeat(6, 1fr); } }
	li { position: relative; min-width: 0; }
	.tile { display: block; position: relative; aspect-ratio: 1; background: var(--surface); overflow: hidden; }
	img { width: 100%; height: 100%; object-fit: cover; display: block; }
	img.dim { opacity: 0.4; }
	.name { margin: 2px 4px 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.err { margin: -4px 4px 6px; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
	.badge { position: absolute; left: 4px; top: 4px; padding: 1px 8px; border-radius: 10px; background: rgb(0 0 0 / 0.7); color: #fff; }
	.badge.saved { background: var(--accent); color: var(--on-accent); font-weight: 600; }
	.badge.failed { background: var(--danger); color: #fff; }
	.play { position: absolute; right: 6px; bottom: 6px; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: rgb(0 0 0 / 0.65); color: #fff; font-size: 10px; }
	.retry { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); }
	.retry:active { transform: translate(-50%, -50%) scale(0.97); }
	.more { display: grid; justify-items: center; gap: 8px; padding: 16px; }
</style>
