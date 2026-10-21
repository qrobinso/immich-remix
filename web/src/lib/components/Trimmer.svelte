<script lang="ts">
	import { clampTrim } from '#lib/trim.ts';

	let { duration, max, start = $bindable(), end = $bindable() }: { duration: number; max: number | null; start: number; end: number } = $props();
	const set = (s: number, e: number) => ({ start, end } = clampTrim(s, e, duration, max));
	const fmt = (s: number) => s.toFixed(1) + ' s';
</script>

<fieldset>
	<legend class="t-small muted">Clip: {fmt(start)} to {fmt(end)} ({fmt(end - start)}{max != null ? `, max ${max} s` : ''})</legend>
	<label class="t-small">Start
		<input type="range" min="0" max={duration} step="0.1" value={start} oninput={(e) => set(+e.currentTarget.value, end)} />
	</label>
	<label class="t-small">End
		<input type="range" min="0" max={duration} step="0.1" value={end} oninput={(e) => set(start, +e.currentTarget.value)} />
	</label>
</fieldset>

<style>
	fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 4px; }
	label { display: grid; grid-template-columns: 44px 1fr; align-items: center; min-height: 44px; }
	input { accent-color: var(--accent); width: 100%; }
</style>
