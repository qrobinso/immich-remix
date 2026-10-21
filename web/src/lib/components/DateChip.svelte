<script lang="ts">
	let { from, to, onpick }: { from: string; to: string; onpick: (from: string, to: string) => void } = $props();
	let dlg: HTMLDialogElement;
	let f = $state('');
	let t = $state('');
	const now = new Date().getFullYear();
	const years = Array.from({ length: 30 }, (_, i) => now - i);

	export const open = () => { f = from; t = to; dlg.showModal(); };
	const year = $derived(f.endsWith('-01-01') && t === f.slice(0, 4) + '-12-31' ? f.slice(0, 4) : '');
	function setYear(e: Event) {
		const y = (e.currentTarget as HTMLSelectElement).value;
		[f, t] = y ? [`${y}-01-01`, `${y}-12-31`] : ['', ''];
	}
	const apply = () => { onpick(f, t); dlg.close(); };
</script>

<dialog bind:this={dlg} aria-label="Choose dates" onclick={(e) => e.target === dlg && dlg.close()}>
	<div class="sheet">
		<label>Year
			<select class="field" value={year} onchange={setYear}>
				<option value="">Any</option>
				{#each years as y}<option value={String(y)}>{y}</option>{/each}
			</select>
		</label>
		<div class="range">
			<label>From <input class="field" type="date" bind:value={f} max={t || undefined} /></label>
			<label>To <input class="field" type="date" bind:value={t} min={f || undefined} /></label>
		</div>
		<div class="actions">
			<button class="btn" onclick={() => { f = t = ''; apply(); }}>Clear</button>
			<button class="btn btn-primary" onclick={apply}>Apply</button>
		</div>
	</div>
</dialog>

<style>
	label { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; color: var(--muted); }
	.range { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
	.actions { display: flex; gap: 12px; justify-content: flex-end; }
</style>
