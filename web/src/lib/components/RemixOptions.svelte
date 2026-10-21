<script lang="ts">
	import type { MediaType, ProviderStatus } from '#lib/types.ts';
	import Trimmer from './Trimmer.svelte';

	let { media, providers, providerId = $bindable(), variations = $bindable(), clipStart = $bindable(), clipEnd = $bindable(), duration, open = $bindable(false) }: {
		media: MediaType; providers: ProviderStatus[]; providerId: string; variations: number;
		clipStart: number; clipEnd: number; duration: number; open?: boolean;
	} = $props();

	const provider = $derived(providers.find((p) => p.id === providerId));
	const maxVariations = $derived(Math.min(media === 'photo' ? 4 : 2, provider?.max_variations[media === 'photo' ? 'image' : 'video'] ?? 1));
	const maxClip = $derived(media === 'video' ? (provider?.max_video_seconds ?? null) : null);
	const price = $derived(provider?.price_per_output?.[media === 'photo' ? 'image' : 'video']);
	const cost = $derived(price == null ? null : price * variations * (media === 'video' ? clipEnd - clipStart : 1));

	// Switching backend can lower the caps: pull the values back inside.
	$effect(() => {
		if (variations > maxVariations) variations = maxVariations;
		if (maxClip != null && clipEnd - clipStart > maxClip) clipEnd = clipStart + maxClip;
	});
</script>

<details bind:open>
	<summary>Options</summary>
	<div class="body">
		{#if !providers.length}<p class="t-small note">No backend for {media === 'video' ? 'videos' : 'photos'} is set up. Add one in Settings.</p>{/if}
		<label class="row">
			<span>Backend</span>
			<select class="field" bind:value={providerId}>
				{#each providers as p (p.id)}<option value={p.id}>{p.name}{p.healthy ? '' : ' (unavailable)'}</option>{/each}
			</select>
		</label>
		<div class="row">
			<span id="var-label">Variations</span>
			<div class="steps" role="group" aria-labelledby="var-label">
				{#each Array.from({ length: maxVariations }, (_, i) => i + 1) as n (n)}
					<button class="step" class:on={variations === n} aria-pressed={variations === n} onclick={() => (variations = n)}>{n}</button>
				{/each}
			</div>
		</div>
		{#if media === 'video'}<Trimmer {duration} max={maxClip} bind:start={clipStart} bind:end={clipEnd} />{/if}
		{#if provider}
			<p class="t-small muted note">{provider.leaves_network ? `Sent to ${provider.name}` : 'Runs locally'}</p>
			{#if cost != null}<p class="t-small note">≈ ${cost.toFixed(2)}</p>{/if}
		{/if}
	</div>
</details>

<style>
	summary { min-height: 44px; display: flex; align-items: center; font-weight: 600; cursor: pointer; }
	.body { display: grid; gap: 8px; padding-bottom: 8px; }
	.row { display: grid; grid-template-columns: 90px 1fr; align-items: center; gap: 8px; }
	select.field { appearance: auto; }
	.steps { display: flex; gap: 8px; }
	.step { width: 44px; height: 44px; border-radius: 12px; border: 1px solid var(--line); background: var(--bg); font-weight: 600; }
	.step.on { background: var(--accent); color: var(--on-accent); border-color: transparent; }
	.note { margin: 0; }
</style>
