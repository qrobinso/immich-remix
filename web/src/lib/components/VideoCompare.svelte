<script lang="ts">
	let { before, after, poster }: { before: string; after: string; poster: string } = $props();
	let mode = $state<'remix' | 'original' | 'split'>('remix');
	let orig: HTMLVideoElement | undefined = $state();
	let remix: HTMLVideoElement | undefined = $state();
	let playing = $state(false);
	let time = $state(0);
	let length = $state(0);

	// The remix is the time master; the original follows once it drifts more than 0.1 s.
	function sync() {
		time = remix!.currentTime;
		if (Math.abs(orig!.currentTime - remix!.currentTime) > 0.1) orig!.currentTime = remix!.currentTime;
	}
	function toggle() {
		if (remix!.paused) { remix!.play(); orig!.play().catch(() => {}); } else { remix!.pause(); orig!.pause(); }
	}
	function seek(e: Event) {
		remix!.currentTime = orig!.currentTime = Number((e.currentTarget as HTMLInputElement).value);
	}
	const modes = [['remix', 'Remix'], ['original', 'Original'], ['split', 'Split']] as const;
</script>

<div class="vc" class:split={mode === 'split'}>
	<div class="pane" class:off={mode === 'remix'}>
		<video bind:this={orig} src={before} {poster} muted loop playsinline preload="auto"></video>
	</div>
	<div class="pane" class:off={mode === 'original'}>
		<video bind:this={remix} src={after} muted loop playsinline preload="auto" ontimeupdate={sync}
			onloadedmetadata={() => (length = remix!.duration)} onplay={() => (playing = true)} onpause={() => (playing = false)}></video>
	</div>
</div>
<div class="ctl">
	<button class="btn" onclick={toggle} aria-label={playing ? 'Pause' : 'Play'}>{playing ? 'Pause' : 'Play'}</button>
	<input type="range" min="0" max={length || 1} step="0.05" value={time} oninput={seek} aria-label="Seek" />
	<div class="seg" role="group" aria-label="View">
		{#each modes as [m, label]}<button aria-pressed={mode === m} onclick={() => (mode = m)}>{label}</button>{/each}
	</div>
</div>

<style>
	.vc { position: relative; flex: 1; min-height: 0; display: grid; }
	.pane { grid-area: 1 / 1; min-height: 0; display: flex; }
	/* Both stay mounted so the hidden one keeps decoding in sync. */
	.pane.off { visibility: hidden; }
	video { width: 100%; height: 100%; object-fit: contain; min-height: 0; }
	.vc:not(.split) .pane:last-child { z-index: 1; }
	.vc:not(.split) .pane:first-child:not(.off) { z-index: 2; }
	.vc.split { grid-template-rows: 1fr 1fr; gap: 2px; }
	.vc.split .pane { grid-area: auto; visibility: visible; }
	.ctl { display: flex; align-items: center; gap: 8px; padding: 6px 12px; flex-wrap: wrap; }
	input[type='range'] { flex: 1; min-width: 100px; min-height: 44px; accent-color: var(--accent); }
	.seg { display: flex; border: 1px solid var(--line); border-radius: 22px; overflow: hidden; }
	.seg button { min-height: 44px; padding: 0 12px; border: 0; background: none; }
	.seg button[aria-pressed='true'] { background: var(--accent); color: var(--on-accent); font-weight: 600; }
</style>
