<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from '#lib/api.ts';
	import type { Person } from '#lib/types.ts';

	let { selected, ontoggle }: { selected: Person[]; ontoggle: (p: Person) => void } = $props();
	let people = $state<Person[]>([]);
	let page = 0;
	let busy = false;
	let done = false;

	async function more() {
		if (busy || done) return;
		busy = true;
		try {
			const batch = await get<Person[]>(`/api/people?page=${page + 1}`);
			const seen = new Set(people.map((p) => p.id));
			const fresh = batch.filter((p) => !seen.has(p.id));
			if (!fresh.length) done = true;
			people.push(...fresh);
			page++;
		} catch {
			done = true; // the row is optional; search still works without it
		} finally {
			busy = false;
		}
	}
	onMount(more);
	const onscroll = (e: Event) => {
		const el = e.currentTarget as HTMLElement;
		if (el.scrollLeft + el.clientWidth > el.scrollWidth - 200) more();
	};
	const isSel = (id: string) => selected.some((s) => s.id === id);
</script>

{#if people.length}
	<ul aria-label="People" {onscroll}>
		{#each people as p (p.id)}
			<li>
				<button aria-pressed={isSel(p.id)} onclick={() => ontoggle(p)}>
					<img src="/api/people/{p.id}/thumb" alt="" width="56" height="56" loading="lazy" />
					<span class="t-small">{p.name || 'Unnamed'}</span>
				</button>
			</li>
		{/each}
	</ul>
{/if}

<style>
	ul { display: flex; gap: 12px; margin: 0; padding: 4px 16px; list-style: none; overflow-x: auto; scrollbar-width: none; }
	li { flex: none; width: 64px; }
	button { width: 100%; min-height: 44px; padding: 0; border: 0; background: none; display: flex; flex-direction: column; align-items: center; gap: 4px; }
	img { width: 56px; height: 56px; border-radius: 50%; object-fit: cover; background: var(--surface); box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px transparent; transition: box-shadow 150ms; }
	button[aria-pressed='true'] img { box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
	button[aria-pressed='true'] span { color: var(--accent); font-weight: 600; }
	span { max-width: 64px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); }
</style>
