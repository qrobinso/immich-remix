<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, events, get, post } from '#lib/api.ts';
	import { resultSrc, sourceThumb } from '#lib/results.ts';
	import type { Job, JobResult, PartialSave, SaveOutcome } from '#lib/types.ts';
	import BeforeAfter from '#lib/components/BeforeAfter.svelte';
	import VideoCompare from '#lib/components/VideoCompare.svelte';
	import Shimmer from '#lib/components/Shimmer.svelte';
	import Toast from '#lib/components/Toast.svelte';

	const jobId = $derived(page.params.jobId ?? '');
	let job = $state<Job | null>(null);
	let error = $state<string | null>(null);
	let index = $state(0);
	let busy = $state(false);
	let toast = $state<{ message: string; href?: string; retry?: boolean } | null>(null);
	const links: Record<string, string> = $state({}); // result id -> Immich deep link
	let stop: (() => void) | undefined;
	let startX = 0;

	const shown = $derived(job?.results.filter((r) => !r.discarded) ?? []);
	const cur = $derived<JobResult | undefined>(shown[Math.min(index, shown.length - 1)]);
	const isVideo = $derived(job?.media_type === 'video');
	const partial = $derived(!!cur && !cur.saved && !!cur.saved_asset_id);

	async function load(id: string) {
		stop?.();
		job = null; error = null; index = 0; toast = null;
		try {
			job = await get<Job>(`/api/jobs/${id}`);
		} catch (e) {
			error = e instanceof ApiError && e.status === 404 ? 'This remix no longer exists.' : "Couldn't load this remix.";
			return;
		}
		if (job.status === 'queued' || job.status === 'running') {
			stop = events(id, (m) => { if (m.status === 'done' || m.status === 'failed') load(id); });
		}
	}
	$effect(() => { load(jobId); });
	onDestroy(() => stop?.());

	// Saving again is idempotent and returns the deep link for a result saved earlier.
	$effect(() => {
		const r = cur;
		if (r?.saved && !links[r.id]) post<SaveOutcome>(`/api/results/${r.id}/save`).then((o) => (links[r.id] = o.link)).catch(() => {});
	});

	async function save() {
		if (!cur || busy) return;
		const r = cur;
		busy = true;
		toast = null;
		try {
			const o = await post<SaveOutcome | PartialSave>(`/api/results/${r.id}/save`);
			if ('failed_step' in o) {
				r.saved_asset_id = o.asset_id; r.save_error = o.error; r.failed_step = o.failed_step;
				toast = { message: `Saved, but ${o.failed_step} failed`, retry: true };
			} else {
				r.saved = true; r.saved_asset_id = o.asset_id; r.save_error = null; links[r.id] = o.link;
				toast = { message: 'Saved to Immich', href: o.link };
			}
		} catch (e) {
			if (e instanceof ApiError && e.status === 409) { await load(jobId); return; }
			const step = e instanceof ApiError ? (e.body as Partial<PartialSave> | null)?.failed_step : null;
			toast = { message: step ? `Couldn't save: ${step} failed` : "Couldn't reach the server", retry: true };
		} finally {
			busy = false;
		}
	}
	async function discard() {
		if (!cur || busy) return;
		busy = true;
		try {
			await post(`/api/results/${cur.id}/discard`);
			cur.discarded = true;
		} catch {
			toast = { message: "Couldn't discard. Try again." };
		} finally {
			busy = false;
		}
	}
	async function again() {
		if (busy) return;
		busy = true;
		try {
			const { id } = await post<{ id: string }>(`/api/jobs/${jobId}/retry`);
			await goto(`/review/${id}`, { replace: true });
		} catch {
			toast = { message: "Couldn't start another remix." };
		} finally {
			busy = false;
		}
	}
	const changeStyle = () => {
		if (!job) return;
		const v = isVideo ? `&type=video&d=${Math.max(job.clip_end_s ?? 0, 1)}` : '';
		goto(`/item/${job.source_asset_id}?sheet=1${v}`);
	};
	const go = (d: number) => (index = Math.min(shown.length - 1, Math.max(0, index + d)));
	const swipe = (e: PointerEvent) => { const dx = e.clientX - startX; if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1); };
</script>

<svelte:head><title>Review</title></svelte:head>

<div class="review">
	<a class="back btn" href="/history" aria-label="Back to History">‹</a>
	{#if error}
		<div class="msg" role="alert"><p>{error}</p><a class="btn" href="/history">Back to History</a></div>
	{:else if !job}
		<div class="msg"><p class="muted">Loading…</p></div>
	{:else if job.status === 'queued' || job.status === 'running'}
		<div class="stage"><img src={sourceThumb(job)} alt="Original" /><Shimmer /></div>
		<p class="msg-line" aria-live="polite">Still working on this remix. It will appear here when it's done.</p>
	{:else if job.status === 'failed'}
		<div class="msg" role="alert">
			<p class="status">The remix failed</p>
			{#if job.error_message}<p class="t-small muted">{job.error_message}</p>{/if}
			<button class="btn btn-primary" onclick={again} disabled={busy}>Try again</button>
		</div>
	{:else if !cur}
		<div class="msg"><p class="status">All variations discarded</p><button class="btn btn-primary" onclick={changeStyle}>Change style</button></div>
	{:else}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="stage" onpointerdown={(e) => (startX = e.clientX)} onpointerup={swipe}>
			{#key cur.id}
				{#if isVideo}
					<VideoCompare before="/api/assets/{job.source_asset_id}/video" after={resultSrc(job, cur)} poster={sourceThumb(job)} />
				{:else}
					<BeforeAfter before={sourceThumb(job)} after={resultSrc(job, cur)} />
				{/if}
			{/key}
		</div>
		{#if shown.length > 1}
			<div class="dots" role="group" aria-label="Variations">
				<button class="step" onclick={() => go(-1)} disabled={index === 0} aria-label="Previous variation">‹</button>
				{#each shown as r, i (r.id)}
					<button class="dot" aria-label="Variation {i + 1}" aria-current={shown[index] === r} onclick={() => (index = i)}></button>
				{/each}
				<button class="step" onclick={() => go(1)} disabled={index === shown.length - 1} aria-label="Next variation">›</button>
			</div>
		{/if}
		<div class="actions">
			{#if cur.saved}
				<p class="saved">Saved{#if links[cur.id]}&nbsp;·&nbsp;<a href={links[cur.id]} target="_blank" rel="noopener">Open in Immich</a>{/if}</p>
			{:else if partial}
				<p class="saved warn">Saved, but {cur.failed_step} failed</p>
				<button class="btn btn-primary" onclick={save} disabled={busy}>Finish saving</button>
			{:else}
				<button class="btn btn-primary" onclick={save} disabled={busy}>Save to Immich</button>
			{/if}
			<div class="row">
				<button class="btn" onclick={again} disabled={busy}>Try again</button>
				<button class="btn" onclick={changeStyle}>Change style</button>
				{#if !cur.saved}<button class="btn" onclick={discard} disabled={busy}>Discard</button>{/if}
			</div>
		</div>
	{/if}
</div>

{#if toast}
	<Toast message={toast.message} href={toast.href} onaction={toast.retry ? save : undefined} ondismiss={() => (toast = null)} />
{/if}

<style>
	.review { position: fixed; inset: 0 0 calc(56px + env(safe-area-inset-bottom)); padding-top: env(safe-area-inset-top); display: flex; flex-direction: column; background: #000; color: #fff; z-index: 5; }
	.back { position: absolute; z-index: 3; top: calc(8px + env(safe-area-inset-top)); left: 8px; display: grid; place-items: center; padding: 0; font-size: 26px; line-height: 1; text-decoration: none; background: rgb(0 0 0 / 0.55); color: #fff; border-color: transparent; }
	.stage { position: relative; flex: 1; min-height: 0; display: flex; touch-action: pan-y; }
	.stage :global(img) { width: 100%; height: 100%; object-fit: contain; }
	.msg { flex: 1; display: grid; place-content: center; justify-items: center; gap: 12px; padding: 24px; text-align: center; }
	.msg p, .msg-line { margin: 0; }
	.msg-line { padding: 12px 16px; text-align: center; }
	.status { font-weight: 600; font-size: 20px; }
	.dots { display: flex; justify-content: center; align-items: center; }
	.dot, .step { min-width: 44px; min-height: 44px; border: 0; background: none; color: #fff; font-size: 22px; display: grid; place-items: center; }
	.step:disabled { opacity: 0.3; }
	.dot::after { content: ''; width: 8px; height: 8px; border-radius: 50%; background: rgb(255 255 255 / 0.4); transition: background 150ms, transform 150ms; }
	.dot[aria-current='true']::after { background: var(--accent); transform: scale(1.4); }
	.actions { display: grid; gap: 8px; padding: 8px 12px 12px; background: var(--bg); color: var(--fg); }
	.actions .btn-primary { width: 100%; min-height: 48px; }
	.actions .btn:disabled { opacity: 0.5; }
	.row { display: flex; gap: 8px; }
	.row .btn { flex: 1; padding: 0 8px; }
	.saved { margin: 0; min-height: 48px; display: flex; align-items: center; justify-content: center; font-weight: 600; }
	.saved a { color: var(--accent); }
	.warn { color: var(--danger); }
</style>
