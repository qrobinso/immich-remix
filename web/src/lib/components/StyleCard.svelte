<script lang="ts">
	import type { StyleCard } from '#lib/types.ts';

	let { style, selected, onselect, oninfo }: { style: StyleCard; selected: boolean; onselect: () => void; oninfo: () => void } = $props();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let longPressed = false;

	function down() {
		longPressed = false;
		timer = setTimeout(() => { longPressed = true; oninfo(); }, 500);
	}
	const cancel = () => clearTimeout(timer);
	const click = () => { if (!longPressed) onselect(); longPressed = false; };
</script>

<div class="card" class:selected>
	<button class="pick" aria-pressed={selected} onpointerdown={down} onpointerup={cancel} onpointerleave={cancel} onpointercancel={cancel} onclick={click} oncontextmenu={(e) => e.preventDefault()}>
		{#if style.preview_url}<img src={style.preview_url} alt="" loading="lazy" draggable="false" />{/if}
		<span class="name t-small">{style.name}</span>
	</button>
	<button class="info" aria-label="Preview {style.name}" onclick={oninfo}>i</button>
</div>

<style>
	.card { position: relative; flex: none; width: 120px; aspect-ratio: 1; border-radius: 16px; background: var(--line); overflow: hidden; outline: 2px solid transparent; outline-offset: 2px; transition: outline-color 150ms; }
	.card.selected { outline-color: var(--accent); }
	.pick { position: absolute; inset: 0; width: 100%; height: 100%; padding: 0; border: 0; background: none; touch-action: manipulation; -webkit-touch-callout: none; user-select: none; }
	img { width: 100%; height: 100%; object-fit: cover; display: block; }
	.name { position: absolute; inset: auto 0 0; padding: 18px 8px 7px; text-align: left; font-weight: 600; color: #fff; background: linear-gradient(transparent, rgb(0 0 0 / 0.75)); }
	.info { position: absolute; top: 0; right: 0; width: 44px; height: 44px; border: 0; background: none; color: #fff; font: italic 600 13px/1 Georgia, serif; text-shadow: 0 0 4px #000; }
	.info::before { content: ''; position: absolute; inset: 10px; border-radius: 50%; background: rgb(0 0 0 / 0.45); z-index: -1; }
</style>
