<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from '#lib/api.ts';
	import { fieldState, saveSetting } from '#lib/settings.svelte.ts';
	import ProviderCard from '#lib/components/ProviderCard.svelte';
	import StyleManager from '#lib/components/StyleManager.svelte';
	import type { ProviderId, ProviderMedia, Settings, Status } from '#lib/types.ts';

	const ORDER: ProviderId[] = ['gemini', 'openai', 'stability', 'runway', 'luma', 'comfyui'];
	let settings = $state<Settings | null>(null);
	let status = $state<Status | null>(null);
	let albums = $state<{ id: string; name: string }[]>([]);
	let failed = $state(false);

	async function reload() {
		try {
			[settings, status] = await Promise.all([get<Settings>('/api/settings'), get<Status>('/api/status')]);
		} catch { failed = true; }
	}
	onMount(() => {
		reload();
		get<{ id: string; name: string }[]>('/api/albums').then((a) => (albums = a)).catch(() => {});
	});

	const v = (k: string) => settings?.values[k];
	const cards = $derived(settings ? ORDER.map((id) => settings!.providers.find((p) => p.id === id)).filter((p) => !!p) : []);
	const supports = (media: ProviderMedia) => (settings?.providers ?? []).filter((p) => p.enabled && p.media_types.includes(media));
	// A change from an input: remember locally, save (debounced for typing).
	function set(k: string, val: unknown, delay = 0) {
		if (settings) settings.values[k] = val;
		saveSetting(k, val, delay);
	}
	const num = (e: Event) => { const n = (e.currentTarget as HTMLInputElement).valueAsNumber; return Number.isNaN(n) ? null : n; };
	const st = (k: string) => fieldState[k] ?? '';
	const album = $derived((v('save.album') as string | null) ?? '');
	const albumNames = $derived(albums.some((a) => a.name === album) || !album ? albums : [...albums, { id: '_', name: album }]);
</script>

{#snippet fs(k: string)}<span class="fs" class:err={st(k) && st(k) !== 'Saved' && st(k) !== 'Saving…'} role="status">{st(k)}</span>{/snippet}

<div class="page">
	<h1 class="t-title">Settings</h1>
	{#if failed}<p class="err" role="alert">Could not load settings. Reload to try again.</p>{/if}

	<h2 class="sec">Immich</h2>
	<section class="box">
		{#if !status}<span class="muted">Checking…</span>
		{:else if status.immich.ok}<span>Connected to Immich {status.immich.version}</span><span class="muted"> as {status.immich.user}</span>
		{:else}<span class="err">{status.immich.error}</span>{/if}
	</section>

	{#if settings}
		<h2 class="sec">Backends</h2>
		{#each cards as p (p.id)}
			<ProviderCard {p} urlEnv={settings.sources['providers.comfyui.url'] === 'env'} onchange={reload} />
		{/each}

		<h2 class="sec">Default backend</h2>
		<section class="box">
			{#each [['image', 'Photos'], ['video', 'Videos']] as [key, label]}
				<div class="set-row">
					<label for="dp-{key}"><span>{label}</span>{@render fs(`default_provider.${key}`)}</label>
					<select id="dp-{key}" class="field" value={v(`default_provider.${key}`) ?? ''} onchange={(e) => set(`default_provider.${key}`, e.currentTarget.value || null)}>
						<option value="">None</option>
						{#each supports(key as ProviderMedia) as p}<option value={p.id}>{p.name}</option>{/each}
					</select>
				</div>
			{/each}
		</section>

		<h2 class="sec">Styles</h2>
		<StyleManager providers={status?.providers ?? []} />

		<h2 class="sec">Save behavior</h2>
		<section class="box">
			<div class="set-row">
				<label for="stack"><span>Stack primary</span>{@render fs('save.stack_primary')}</label>
				<select id="stack" class="field" value={v('save.stack_primary')} onchange={(e) => set('save.stack_primary', e.currentTarget.value)}>
					<option value="original">Original</option><option value="remix">Remix</option>
				</select>
			</div>
			<div class="set-row">
				<label for="album"><span>Add to album</span>{@render fs('save.album')}</label>
				<select id="album" class="field" value={album} onchange={(e) => set('save.album', e.currentTarget.value || null)}>
					<option value="">None</option>
					{#each albumNames as a (a.id)}<option value={a.name}>{a.name}</option>{/each}
				</select>
			</div>
			<div class="set-row">
				<label for="tag"><span>Tag</span>{@render fs('save.tag')}</label>
				<input id="tag" class="field" maxlength="50" placeholder="No tag" value={v('save.tag') ?? ''} oninput={(e) => set('save.tag', e.currentTarget.value || null, 500)} />
			</div>
		</section>

		<h2 class="sec">Photo output</h2>
		<section class="box">
			<div class="set-row">
				<label for="px"><span>Longest side, in pixels</span>{@render fs('photo.max_px')}</label>
				<input id="px" class="field" type="number" min="256" max="8192" step="64" value={v('photo.max_px')} oninput={(e) => { const n = num(e); if (n !== null) set('photo.max_px', n, 500); }} />
			</div>
			<div class="set-row">
				<label for="q"><span>JPEG quality (50 to 100)</span>{@render fs('photo.jpeg_quality')}</label>
				<input id="q" class="field" type="number" min="50" max="100" value={v('photo.jpeg_quality')} oninput={(e) => { const n = num(e); if (n !== null) set('photo.jpeg_quality', n, 500); }} />
			</div>
			<div class="set-row">
				<label for="src"><span>Send to the backend</span>{@render fs('photo.source')}</label>
				<select id="src" class="field" value={v('photo.source')} onchange={(e) => set('photo.source', e.currentTarget.value)}>
					<option value="original">The original</option><option value="preview">Immich's preview</option>
				</select>
			</div>
		</section>

		<h2 class="sec">Video output</h2>
		<section class="box">
			<div class="set-row">
				<label for="vh"><span>Maximum resolution</span>{@render fs('video.max_height')}</label>
				<select id="vh" class="field" value={String(v('video.max_height'))} onchange={(e) => set('video.max_height', Number(e.currentTarget.value))}>
					{#each [480, 720, 1080, 1440, 2160] as h}<option value={String(h)}>{h}p</option>{/each}
				</select>
			</div>
			<div class="set-row">
				<label class="toggle"><input type="checkbox" role="switch" checked={v('video.keep_audio') === true} onchange={(e) => set('video.keep_audio', e.currentTarget.checked)} />Keep the original audio</label>
				{@render fs('video.keep_audio')}
			</div>
		</section>

		<h2 class="sec">Cleanup</h2>
		<section class="box">
			<div class="set-row">
				<label for="days"><span>Keep unsaved results for (days)</span>{@render fs('cleanup.days')}</label>
				<input id="days" class="field" type="number" min="1" max="365" value={v('cleanup.days')} oninput={(e) => { const n = num(e); if (n !== null) set('cleanup.days', n, 500); }} />
			</div>
		</section>
	{/if}
</div>

<style>
	.page { max-width: 640px; margin: 0 auto; padding: 16px; }
	h1 { margin: 0 0 4px; }
	.sec { font-size: 15px; font-weight: 600; margin: 28px 0 6px; }
	.box { background: var(--surface); border-radius: 16px; padding: 4px 16px; }
	.err { color: var(--danger); }
	.box > span { display: inline-block; padding: 12px 0; }
</style>
