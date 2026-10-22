<script lang="ts">
	// Shows the image and reports where it was tapped, as fractions of the image (not the box: object-fit leaves bars).
	let { src, spot, onmark }: { src: string; spot: { x: number; y: number } | null; onmark: (x: number, y: number) => void } = $props();
	let img: HTMLImageElement | undefined = $state();
	let box = $state<{ left: number; top: number; width: number; height: number } | null>(null);

	function measure() {
		if (!img?.naturalWidth) return;
		const s = Math.min(img.clientWidth / img.naturalWidth, img.clientHeight / img.naturalHeight);
		const width = img.naturalWidth * s, height = img.naturalHeight * s;
		box = { left: (img.clientWidth - width) / 2, top: (img.clientHeight - height) / 2, width, height };
	}
	function tap(e: MouseEvent) {
		measure();
		if (!box || !img) return;
		const r = img.getBoundingClientRect();
		const x = (e.clientX - r.left - box.left) / box.width, y = (e.clientY - r.top - box.top) / box.height;
		if (x >= 0 && x <= 1 && y >= 0 && y <= 1) onmark(x, y);
	}
</script>

<svelte:window onresize={measure} />
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<div class="mark">
	<img bind:this={img} {src} alt="Tap the spot to change" onload={measure} onclick={tap} draggable="false" />
	{#if spot && box}
		<span class="ring" style:left="{box.left + spot.x * box.width}px" style:top="{box.top + spot.y * box.height}px" aria-hidden="true"></span>
	{/if}
</div>

<style>
	.mark { position: relative; width: 100%; height: 100%; }
	img { width: 100%; height: 100%; object-fit: contain; cursor: crosshair; display: block; }
	.ring { position: absolute; width: 36px; height: 36px; margin: -18px; border: 3px solid #ff3b30; border-radius: 50%; box-shadow: 0 0 0 2px rgb(0 0 0 / 0.4); pointer-events: none; }
</style>
