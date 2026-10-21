<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { post } from '#lib/api.ts';
	import { emptyFilters, fromParams, toParams, toSearchBody, type Filters } from '#lib/filters.ts';
	import type { AssetCard, Person, SearchPage } from '#lib/types.ts';
	import Grid from '#lib/components/Grid.svelte';
	import SearchBar from '#lib/components/SearchBar.svelte';
	import PeopleRow from '#lib/components/PeopleRow.svelte';
	import PlacePicker from '#lib/components/PlacePicker.svelte';
	import DateChip from '#lib/components/DateChip.svelte';
	import TypeToggle from '#lib/components/TypeToggle.svelte';
	import FilterChips from '#lib/components/FilterChips.svelte';

	let filters = $state<Filters>(untrack(() => fromParams(new URLSearchParams(page.url.search))));
	let items = $state<AssetCard[]>([]);
	let next = $state<number | null>(1);
	let inflight = false;
	let failed = $state(false);
	let loading = $state(true);
	let gen = 0;
	let placePicker: { open: () => void };
	let dateChip: { open: () => void };
	let mounted = false;
	let lastQs: string | null = null;

	async function load() {
		if (inflight || next === null) return;
		const my = gen;
		inflight = true;
		loading = true;
		failed = false;
		try {
			const r = await post<SearchPage>('/api/search', toSearchBody(filters, next));
			if (my !== gen) return; // outdated query
			items.push(...r.items);
			next = r.next_page;
		} catch {
			if (my === gen) failed = true;
		} finally {
			if (my === gen) { inflight = false; loading = false; }
		}
	}

	// Any filter change: reset the list, mirror filters into the URL, fetch page 1.
	$effect(() => {
		const qs = toParams(filters).toString();
		untrack(() => {
			if (qs === lastQs) return; // same filters re-applied: keep grid and scroll
			lastQs = qs;
			gen++;
			inflight = false;
			items = [];
			next = 1;
			if (mounted) goto('?' + qs, { replace: true, reset: false }) // SvelteKit 3: reset:false keeps focus and scroll;
			load();
		});
	});
	onMount(() => { mounted = true; });

	const set = (patch: Partial<Filters>) => (filters = { ...filters, ...patch });
	const togglePerson = (p: Person) =>
		set({ people: filters.people.some((x) => x.id === p.id) ? filters.people.filter((x) => x.id !== p.id) : [...filters.people, p] });
	function remove(k: string) {
		if (k === 'query') set({ query: '' });
		else if (k === 'place') set({ place: null });
		else if (k === 'date') set({ dateFrom: '', dateTo: '' });
		else if (k === 'type') set({ type: 'all' });
		else set({ people: filters.people.filter((p) => p.id !== k) });
	}
	const hasFilters = $derived(JSON.stringify(filters) !== JSON.stringify(emptyFilters()));
</script>

<svelte:head><title>Library</title></svelte:head>

<header>
	<div class="row pad"><SearchBar value={filters.query} onchange={(query) => set({ query })} /></div>
	<PeopleRow selected={filters.people} ontoggle={togglePerson} />
	<div class="row pad tools">
		<button class="btn t-small" onclick={() => placePicker.open()}>Place</button>
		<button class="btn t-small" onclick={() => dateChip.open()}>Date</button>
		<TypeToggle value={filters.type} onchange={(type) => set({ type })} />
	</div>
	<FilterChips {filters} onremove={remove} />
</header>

<Grid {items} canLoadMore={next !== null && !failed} onmore={load} />

<div class="status" aria-live="polite">
	{#if failed}
		<p class="muted">Couldn't load photos.</p>
		<button class="btn" onclick={load}>Retry</button>
	{:else if loading}
		<p class="muted t-small">Loading…</p>
	{:else if !items.length}
		<p class="t-title">No photos match</p>
		{#if hasFilters}<button class="btn btn-primary" onclick={() => (filters = emptyFilters())}>Clear filters</button>{/if}
	{/if}
</div>

<PlacePicker bind:this={placePicker} onpick={(place) => set({ place })} />
<DateChip bind:this={dateChip} from={filters.dateFrom} to={filters.dateTo} onpick={(dateFrom, dateTo) => set({ dateFrom, dateTo })} />

<style>
	header { display: flex; flex-direction: column; gap: 8px; padding: 8px 0; }
	.pad { padding: 0 16px; }
	.tools { display: grid; grid-template-columns: auto auto 1fr; gap: 8px; align-items: center; }
	.status { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 24px 16px; text-align: center; }
	.status p { margin: 0; }
</style>
