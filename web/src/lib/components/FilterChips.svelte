<script lang="ts">
	import type { Filters } from '#lib/filters.ts';

	let { filters, onremove }: { filters: Filters; onremove: (k: 'query' | 'place' | 'date' | 'type' | string) => void } = $props();
	const chips = $derived([
		...(filters.query.trim() ? [{ k: 'query', label: `“${filters.query.trim()}”` }] : []),
		...filters.people.map((p) => ({ k: p.id, label: p.name || 'Unnamed' })),
		...(filters.place ? [{ k: 'place', label: filters.place.value }] : []),
		...(filters.dateFrom || filters.dateTo ? [{ k: 'date', label: `${filters.dateFrom || '…'} to ${filters.dateTo || '…'}` }] : []),
		...(filters.type !== 'all' ? [{ k: 'type', label: filters.type === 'photo' ? 'Photos' : 'Videos' }] : [])
	]);
</script>

{#if chips.length}
	<ul aria-label="Active filters">
		{#each chips as c (c.k)}
			<li><button class="t-small" onclick={() => onremove(c.k)} aria-label="Remove filter {c.label}">{c.label}<span aria-hidden="true">✕</span></button></li>
		{/each}
	</ul>
{/if}

<style>
	ul { display: flex; gap: 8px; margin: 0; padding: 0 16px; list-style: none; overflow-x: auto; scrollbar-width: none; }
	li { flex: none; }
	button { min-height: 44px; padding: 0 14px; border-radius: 22px; border: 1px solid var(--accent); background: none; color: var(--accent); display: flex; align-items: center; gap: 8px; white-space: nowrap; }
</style>
