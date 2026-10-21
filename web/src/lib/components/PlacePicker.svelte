<script lang="ts">
	import { get } from '#lib/api.ts';
	import type { Place } from '#lib/types.ts';

	let { onpick }: { onpick: (p: Place | null) => void } = $props();
	let dlg: HTMLDialogElement;
	let q = $state('');
	let results = $state<Place[]>([]);
	let failed = $state(false);
	let timer: ReturnType<typeof setTimeout>;
	let seq = 0;

	export const open = () => { dlg.showModal(); search(); };
	function search(text = q) {
		clearTimeout(timer);
		timer = setTimeout(async () => {
			const my = ++seq;
			try {
				const r = await get<Place[]>(`/api/places?q=${encodeURIComponent(text)}`);
				if (my === seq) { results = r; failed = false; }
			} catch { if (my === seq) failed = true; }
		}, 250);
	}
	const pick = (p: Place) => { onpick(p); dlg.close(); };
</script>

<dialog bind:this={dlg} aria-label="Choose a place" onclick={(e) => e.target === dlg && dlg.close()}>
	<div class="sheet">
		<input class="field" type="search" placeholder="Search cities, states, countries" aria-label="Search places" bind:value={q} oninput={(e) => search(e.currentTarget.value)} />
		{#if failed}<p class="muted">Couldn't load places. Try again.</p>{/if}
		<ul>
			{#each results as p (p.kind + p.value)}
				<li><button onclick={() => pick(p)}>{p.value} <span class="muted t-small">{p.kind}</span></button></li>
			{:else}
				{#if !failed}<li class="muted pad">No places found.</li>{/if}
			{/each}
		</ul>
	</div>
</dialog>

<style>
	ul { margin: 8px 0 0; padding: 0; list-style: none; overflow-y: auto; max-height: 50dvh; }
	li button { width: 100%; min-height: 44px; text-align: left; background: none; border: 0; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); }
	.pad { padding: 12px 0; }
</style>
