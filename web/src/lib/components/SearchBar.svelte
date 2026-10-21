<script lang="ts">
	import { untrack } from 'svelte';
	let { value, onchange }: { value: string; onchange: (v: string) => void } = $props();
	let text = $state(untrack(() => value));
	let timer: ReturnType<typeof setTimeout>;
	// follow external changes (chip removal, Back) without echoing our own typing
	$effect(() => { const v = value; if (v !== untrack(() => text).trim()) text = v; });
	function input() {
		clearTimeout(timer);
		timer = setTimeout(() => onchange(text), 400);
	}
</script>

<form role="search" onsubmit={(e) => { e.preventDefault(); clearTimeout(timer); onchange(text); }}>
	<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4" /></svg>
	<input type="search" class="field" placeholder="Search your photos: beach sunset, birthday cake" aria-label="Search photos" bind:value={text} oninput={input} enterkeyhint="search" />
</form>

<style>
	form { position: relative; }
	svg { position: absolute; left: 14px; top: 12px; color: var(--muted); pointer-events: none; }
	input { padding-left: 42px; border-radius: 22px; }
</style>
