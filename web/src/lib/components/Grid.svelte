<script lang="ts">
	import { thumbHashToDataURL } from 'thumbhash';
	import { SvelteSet } from 'svelte/reactivity';
	import type { AssetCard } from '#lib/types.ts';

	let { items, canLoadMore, onmore }: { items: AssetCard[]; canLoadMore: boolean; onmore: () => void } = $props();
	let sentinel: HTMLElement | undefined = $state();
	const loaded = new SvelteSet<string>();

	// Re-observing after each batch re-fires the callback if the sentinel is still on screen.
	$effect(() => {
		items.length;
		if (!sentinel || !canLoadMore) return;
		const io = new IntersectionObserver((e) => e[0].isIntersecting && onmore(), { rootMargin: '800px' });
		io.observe(sentinel);
		return () => io.disconnect();
	});

	function hash(h: string | null) {
		try { return h ? `url(${thumbHashToDataURL(Uint8Array.from(atob(h), (c) => c.charCodeAt(0)))})` : ''; } catch { return ''; }
	}
	const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
</script>

<ul>
	{#each items as a (a.id)}
		<li style:background-image={hash(a.thumbhash)}>
			<a href="/item/{a.id}" aria-label={a.alt || (a.type === 'video' ? 'Video' : 'Photo') + ' from ' + a.taken_at.slice(0, 10)}>
				<img src="/api/assets/{a.id}/thumb" alt={a.alt ?? ''} loading="lazy" class:in={loaded.has(a.id)} onload={() => loaded.add(a.id)} />
				{#if a.type === 'video' && a.duration_s != null}<span class="badge t-small">{mmss(a.duration_s)}</span>{/if}
			</a>
		</li>
	{/each}
</ul>
<div bind:this={sentinel} aria-hidden="true"></div>

<style>
	ul { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; margin: 0; padding: 0; list-style: none; }
	@media (min-width: 600px) { ul { grid-template-columns: repeat(5, 1fr); } }
	@media (min-width: 900px) { ul { grid-template-columns: repeat(6, 1fr); } }
	@media (min-width: 1200px) { ul { grid-template-columns: repeat(8, 1fr); } }
	li { aspect-ratio: 1; background: var(--surface) center / cover; position: relative; overflow: hidden; }
	a, img { display: block; width: 100%; height: 100%; }
	img { object-fit: cover; opacity: 0; transition: opacity 200ms; }
	img.in { opacity: 1; }
	.badge { position: absolute; right: 4px; bottom: 4px; padding: 1px 6px; border-radius: 10px; background: rgb(0 0 0 / 0.65); color: #fff; font-variant-numeric: tabular-nums; }
</style>
