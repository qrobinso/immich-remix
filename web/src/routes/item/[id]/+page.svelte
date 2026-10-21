<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, events, get, post } from '#lib/api.ts';
	import { defaultTrim } from '#lib/trim.ts';
	import { app, loadStatus } from '#lib/status.svelte.ts';
	import type { JobEvent, MediaType, StylesResponse } from '#lib/types.ts';
	import StyleSheet from '#lib/components/StyleSheet.svelte';
	import RemixOptions from '#lib/components/RemixOptions.svelte';
	import Shimmer from '#lib/components/Shimmer.svelte';

	const id = page.params.id;
	const media: MediaType = page.url.searchParams.get('type') === 'video' ? 'video' : 'photo';
	const duration = Math.max(Number(page.url.searchParams.get('d')) || 0, media === 'video' ? 1 : 0);

	let styles = $state<StylesResponse | null>(null);
	let loadFailed = $state(false);
	let selected = $state<string | null>(null);
	let prompt = $state('');
	let providerId = $state('');
	let variations = $state(1);
	let clipStart = $state(0);
	let clipEnd = $state(duration);
	let optionsOpen = $state(false);

	let phase = $state<'idle' | 'running' | 'failed'>('idle');
	let statusLine = $state('');
	let failure = $state<{ code: string | null; text: string } | null>(null);
	let stop: (() => void) | undefined;

	const providers = $derived((app.status?.providers ?? []).filter((p) => p.media_types.includes(media === 'photo' ? 'image' : 'video')));
	const canRemix = $derived(phase === 'idle' && providerId !== '' && (selected === 'custom' ? prompt.trim() !== '' : selected !== null));

	onMount(async () => {
		if (!app.status) loadStatus();
		try { styles = await get<StylesResponse>('/api/styles'); } catch { loadFailed = true; }
	});
	// Preselect the selected style's default backend when it is healthy for this media, else keep/pick the first healthy one.
	const styleDefault = $derived(
		styles?.categories.flatMap((c) => c.styles).find((s) => s.id === selected)?.default_provider[media === 'photo' ? 'image' : 'video']
	);
	$effect(() => {
		const healthy = providers.filter((p) => p.healthy);
		if (styleDefault && healthy.some((p) => p.id === styleDefault)) providerId = styleDefault;
		else if (!providerId && providers.length) providerId = (healthy[0] ?? providers[0]).id;
	});
	const minutes = $derived.by(() => {
		const s = providers.find((p) => p.id === providerId)?.typical_seconds;
		return s == null ? null : Math.max(1, Math.ceil(s / 60));
	});
	$effect(() => { if (media === 'video' && duration) ({ start: clipStart, end: clipEnd } = defaultTrim(duration, null)); });
	onDestroy(() => stop?.());

	const DEFAULT_LINE: Record<string, string> = { queued: 'Waiting for a free slot…', running: 'Working on your remix…' };

	function fail(e: JobEvent) {
		const text = (e.error_message as string | undefined) ?? e.message ?? '';
		const code = (e.error_code as string | undefined) ?? null;
		failure = { code, text };
		phase = 'failed';
	}

	const FAILURE_COPY: Record<string, string> = {
		rate_limited: 'The backend is busy or out of quota. Try again later.',
		timeout: 'This took too long. Try again.',
		auth: 'The backend rejected its API key. Check Settings.'
	};

	async function remix() {
		if (!canRemix) return;
		phase = 'running';
		failure = null;
		statusLine = 'Sending to the backend…';
		try {
			const { id: jobId } = await post<{ id: string }>('/api/jobs', {
				asset_id: id,
				style_id: selected === 'custom' ? null : selected,
				custom_prompt: selected === 'custom' ? prompt.trim() : null,
				provider_id: providerId,
				variations,
				clip_start: media === 'video' ? clipStart : null,
				clip_end: media === 'video' ? clipEnd : null
			});
			stop = events(jobId, (e) => {
				if (e.status === 'done') { stop?.(); goto(`/review/${jobId}`); }
				else if (e.status === 'failed') fail(e);
				else statusLine = e.message ?? DEFAULT_LINE[e.status] ?? 'Working…';
			});
		} catch (err) {
			const d = err instanceof ApiError && typeof (err.body as { detail?: unknown })?.detail === 'string' ? (err.body as { detail: string }).detail : null;
			failure = { code: null, text: d ?? "Couldn't start the remix. Check your connection and try again." };
			phase = 'failed';
		}
	}
	const retry = () => { stop?.(); phase = 'idle'; remix(); };
	const anotherBackend = () => { stop?.(); phase = 'idle'; optionsOpen = true; };
</script>

<svelte:head><title>Remix</title></svelte:head>

<div class="viewer">
	<a class="back btn" href="/" aria-label="Back to library">‹</a>
	<div class="stage">
		{#if media === 'video'}
			<video src="/api/assets/{id}/video" poster="/api/assets/{id}/thumb?size=preview" muted loop autoplay playsinline></video>
		{:else}
			<img src="/api/assets/{id}/thumb?size=preview" alt="The item you are remixing" />
		{/if}
		{#if phase === 'running'}<Shimmer />{/if}
	</div>
</div>

{#if loadFailed}
	<div class="sheet-fallback" role="alert"><p>Couldn't load styles.</p><button class="btn" onclick={() => location.reload()}>Retry</button></div>
{:else if styles}
	<StyleSheet categories={styles.categories} {media} bind:selected bind:prompt>
		<RemixOptions {media} {providers} bind:providerId bind:variations bind:clipStart bind:clipEnd {duration} bind:open={optionsOpen} />
		<div class="action" aria-live="polite">
			{#if phase === 'running'}
				<p class="status">{statusLine}</p>
				{#if media === 'video'}<p class="t-small muted">{minutes != null ? `This takes about ${minutes} min` : 'This usually takes a few minutes'}. You can leave; it will show up in History.</p>
				{:else}<p class="t-small muted">You can leave; it will show up in History.</p>{/if}
			{:else if phase === 'failed' && failure}
				{#if failure.code === 'content_refused'}
					<p class="status" role="alert">This style couldn't be applied</p>
					{#if failure.text}<p class="t-small muted">{failure.text}</p>{/if}
					<button class="btn" onclick={anotherBackend}>Try another backend</button>
				{:else}
					<p class="status" role="alert">{(failure.code && FAILURE_COPY[failure.code]) || failure.text || 'The remix failed.'}</p>
					<button class="btn btn-primary" onclick={retry}>Try again</button>
				{/if}
			{:else}
				<button class="btn btn-primary remix" disabled={!canRemix} onclick={remix}>Remix</button>
			{/if}
		</div>
	</StyleSheet>
{/if}

<style>
	.viewer { position: fixed; inset: 0; z-index: 50; background: #000; display: flex; padding-bottom: 62dvh; box-sizing: border-box; }
	.stage { position: relative; flex: 1; min-width: 0; display: flex; }
	.stage img, .stage video { width: 100%; height: 100%; object-fit: contain; }
	.back { position: absolute; z-index: 2; top: calc(8px + env(safe-area-inset-top)); left: 8px; display: grid; place-items: center; padding: 0; font-size: 26px; line-height: 1; text-decoration: none; background: rgb(0 0 0 / 0.55); color: #fff; border-color: transparent; }
	.action { position: sticky; bottom: 0; display: grid; gap: 6px; justify-items: stretch; padding: 8px 0; background: var(--surface); text-align: center; }
	.action p { margin: 0; }
	.status { font-weight: 600; }
	.remix { width: 100%; min-height: 52px; }
	.remix:disabled { opacity: 0.4; }
	.sheet-fallback { position: fixed; inset: auto 0 0; z-index: 60; padding: 24px; background: var(--surface); text-align: center; }
</style>
