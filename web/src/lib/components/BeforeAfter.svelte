<script lang="ts">
	let { before, after }: { before: string; after: string } = $props();
	let pos = $state(50); // % of the width showing the original
	let box: HTMLElement | undefined = $state();
	let dragging = false;
	// Show the remix only once it has loaded. A just-saved asset's preview 404s until Immich makes it,
	// so a changed src is preloaded with backoff while the current image stays on screen.
	let shown = $state('');
	$effect(() => {
		const url = after;
		let n = 0, timer: ReturnType<typeof setTimeout>, dead = false;
		const attempt = () => {
			const im = new Image();
			im.onload = () => { if (!dead) shown = url; };
			im.onerror = () => { if (!dead && n < 12) timer = setTimeout(attempt, Math.min(1000 * 1.5 ** n++, 8000)); };
			im.src = n ? `${url}${url.includes('?') ? '&' : '?'}r=${n}` : url;
		};
		attempt();
		return () => { dead = true; clearTimeout(timer); };
	});

	const set = (x: number) => {
		const r = box!.getBoundingClientRect();
		pos = Math.min(100, Math.max(0, ((x - r.left) / r.width) * 100));
	};
	// Only a grab near the divider drags it, so a swipe elsewhere reaches the parent (variation swipe).
	function down(e: PointerEvent) {
		const r = box!.getBoundingClientRect();
		if (Math.abs(e.clientX - (r.left + (pos / 100) * r.width)) > 32) return;
		dragging = true;
		box!.setPointerCapture(e.pointerId);
		e.stopPropagation();
	}
	const move = (e: PointerEvent) => dragging && set(e.clientX);
	const up = () => (dragging = false);
	function key(e: KeyboardEvent) {
		const d = e.key === 'ArrowLeft' ? -5 : e.key === 'ArrowRight' ? 5 : 0;
		if (!d) return;
		e.preventDefault();
		pos = Math.min(100, Math.max(0, pos + d));
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ba" bind:this={box} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
	{#if shown}<img src={shown} alt="Remix" draggable="false" />{/if}
	<img class="orig" src={before} alt="Original" draggable="false" style:clip-path="inset(0 {100 - pos}% 0 0)" />
	<div class="line" style:left="{pos}%">
		<button class="knob" role="slider" aria-label="Compare original and remix" aria-valuemin="0" aria-valuemax="100"
			aria-valuenow={Math.round(pos)} aria-valuetext="{Math.round(pos)}% original" onkeydown={key}>
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 7l-5 5 5 5M15 7l5 5-5 5" /></svg>
		</button>
	</div>
</div>

<style>
	.ba { position: relative; width: 100%; height: 100%; touch-action: pan-y; user-select: none; }
	img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; pointer-events: none; }
	.line { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #fff; box-shadow: 0 0 0 1px rgb(0 0 0 / 0.4); }
	.knob { position: absolute; top: 50%; left: 50%; width: 44px; height: 44px; margin: -22px; border-radius: 50%; display: grid; place-items: center; border: 2px solid #fff; background: rgb(0 0 0 / 0.55); color: #fff; touch-action: none; }
</style>
