<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MediaType, StyleCard as Style, StyleCategory } from '#lib/types.ts';
	import StyleCard from './StyleCard.svelte';
	import StylePreviewModal from './StylePreviewModal.svelte';

	let { categories, media, selected = $bindable(), prompt = $bindable(), children }: {
		categories: StyleCategory[]; media: MediaType; selected: string | null; prompt: string; children: Snippet;
	} = $props();

	const rows = $derived(
		categories.map((c) => ({ ...c, styles: c.styles.filter((s) => !s.hidden && s.media_types.includes(media === 'photo' ? 'image' : 'video')) })).filter((c) => c.styles.length)
	);
	let preview = $state<Style | null>(null);
	let modal: { open: () => void };
	const showPreview = (s: Style) => { preview = s; modal.open(); };
</script>

<section class="sheet-pane" aria-label="Choose a style">
	<div class="grab" aria-hidden="true"></div>
	<div class="scroll">
		{#each rows as c (c.id)}
			<h2 class="t-small muted">{c.name}</h2>
			<div class="row">
				{#each c.styles as s (s.id)}
					<StyleCard style={s} selected={selected === s.id} onselect={() => (selected = s.id)} oninfo={() => showPreview(s)} />
				{/each}
			</div>
		{/each}
		<h2 class="t-small muted">Your own</h2>
		<div class="row">
			<button class="custom" class:selected={selected === 'custom'} aria-pressed={selected === 'custom'} onclick={() => (selected = 'custom')}>
				<span class="plus" aria-hidden="true">+</span><span class="t-small">Custom</span>
			</button>
		</div>
		{#if selected === 'custom'}
			<textarea class="field" rows="3" placeholder="Describe the look, e.g. a 1970s travel poster" aria-label="Custom prompt" bind:value={prompt}></textarea>
		{/if}
		{@render children()}
	</div>
</section>
<StylePreviewModal bind:this={modal} name={preview?.name} src={preview?.preview_url?.replace('kind=card', 'kind=full')} />

<style>
	.sheet-pane { position: fixed; inset: auto 0 0; z-index: 60; max-height: 62dvh; display: flex; flex-direction: column; background: var(--surface); border-radius: 16px 16px 0 0; box-shadow: 0 -8px 32px rgb(0 0 0 / 0.4); animation: spring 250ms cubic-bezier(0.2, 1.1, 0.3, 1); }
	@keyframes spring { from { transform: translateY(100%); } }
	.grab { width: 36px; height: 4px; border-radius: 2px; background: var(--line); margin: 8px auto 0; flex: none; }
	.scroll { overflow-y: auto; padding: 0 16px calc(12px + env(safe-area-inset-bottom)); overscroll-behavior: contain; max-width: 640px; width: 100%; box-sizing: border-box; margin: 0 auto; }
	h2 { margin: 12px 0 6px; font-weight: 600; }
	.row { display: flex; gap: 8px; overflow-x: auto; padding: 4px 4px 6px; margin: 0 -4px; scroll-snap-type: x proximity; scrollbar-width: none; }
	.row > :global(*) { scroll-snap-align: start; }
	.custom { flex: none; width: 120px; aspect-ratio: 1; border-radius: 16px; border: 1px dashed var(--muted); background: var(--line); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; outline: 2px solid transparent; outline-offset: 2px; transition: outline-color 150ms; }
	.custom.selected { outline-color: var(--accent); border-style: solid; }
	.plus { font-size: 28px; line-height: 1; }
	textarea { padding: 10px 14px; margin-top: 8px; resize: vertical; }
</style>
