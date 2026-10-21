<script lang="ts">
	let { value, onchange }: { value: 'all' | 'photo' | 'video'; onchange: (v: 'all' | 'photo' | 'video') => void } = $props();
	const opts = [['all', 'All'], ['photo', 'Photos'], ['video', 'Videos']] as const;
</script>

<div role="radiogroup" aria-label="Media type">
	{#each opts as [v, label]}
		<button role="radio" aria-checked={value === v} class="t-small" onclick={() => onchange(v)}>{label}</button>
	{/each}
</div>

<style>
	div { display: flex; background: var(--surface); border-radius: 22px; padding: 2px; }
	button { flex: 1; min-height: 44px; border: 0; border-radius: 20px; background: none; color: var(--muted); transition: background 150ms, color 150ms; }
	button[aria-checked='true'] { background: var(--accent); color: var(--on-accent); font-weight: 600; }
</style>
