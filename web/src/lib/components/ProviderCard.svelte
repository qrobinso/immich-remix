<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { get, post } from '#lib/api.ts';
	import { fieldState, saveSetting } from '#lib/settings.svelte.ts';
	import type { HealthResult, ModelsResponse, SettingsProvider } from '#lib/types.ts';

	let { p, urlEnv = false, onchange }: { p: SettingsProvider; urlEnv?: boolean; onchange: () => void } = $props();
	const k = (f: string) => `providers.${p.id}.${f}`;
	let key = $state('');
	let url = $state(untrack(() => p.url) ?? "");
	let models = $state<{ id: string; label: string }[] | null>(null); // null = free-text fallback
	let model = $state(untrack(() => p.model) ?? "");
	let result = $state<HealthResult | null>(null);
	let testing = $state(false);

	async function loadModels() {
		try {
			const r = await get<ModelsResponse>(`/api/providers/${p.id}/models`);
			models = Array.isArray(r) ? r : null;
		} catch {
			models = null;
		}
	}
	onMount(() => { if (p.enabled && (p.key_set || p.id === 'comfyui')) loadModels(); });

	async function test() {
		testing = true;
		try {
			result = await post<HealthResult>(`/api/providers/${p.id}/test`);
		} catch {
			result = { ok: false, message: 'Test failed' };
		}
		testing = false;
		onchange();
	}
	function saveKey() {
		if (!key) return;
		saveSetting(k('api_key'), key, 0, () => { key = ''; onchange(); loadModels(); });
	}
	const st = (f: string) => fieldState[k(f)] ?? '';
</script>

<section class="card" class:off={!p.enabled}>
	<header>
		<h3 class="t-title">{p.name}</h3>
		<span class="dot" class:ok={p.enabled && p.healthy} title={p.enabled ? (p.healthy ? 'Working' : (p.message ?? 'Not working')) : 'Off'}></span>
		<span class="muted t-small grow">{p.media_types.map((m) => (m === 'photo' ? 'photos' : 'videos')).join(' and ')}</span>
		<label class="toggle">
			<input type="checkbox" role="switch" aria-label="Enable {p.name}" checked={p.enabled}
				onchange={(e) => saveSetting(k('enabled'), e.currentTarget.checked, 0, () => { onchange(); if (e.currentTarget.checked) loadModels(); })} />
		</label>
	</header>
	{#if p.enabled}
		{#if p.id === 'comfyui'}
			<div class="set-row">
				<label for="{p.id}-url"><span>Server URL</span><span class="fs" class:err={st('url') !== 'Saved' && st('url') !== 'Saving…'}>{st('url')}</span></label>
				<input id="{p.id}-url" class="field" type="url" placeholder="http://192.168.1.20:8188" readonly={urlEnv}
					value={urlEnv ? 'Set by environment' : url} oninput={(e) => saveSetting(k('url'), e.currentTarget.value || null, 500, onchange)} />
			</div>
		{:else}
			<div class="set-row">
				<label for="{p.id}-key"><span>API key</span><span class="fs" class:err={st('api_key') !== 'Saved' && st('api_key') !== 'Saving…'}>{st('api_key')}</span></label>
				{#if p.key_source === 'env'}
					<input id="{p.id}-key" class="field" readonly value="Set by environment" />
				{:else}
					<input id="{p.id}-key" class="field" type="password" autocomplete="off" bind:value={key}
						placeholder={p.key_set ? 'Saved' : 'Paste a key'} onchange={saveKey} onblur={saveKey} />
				{/if}
			</div>
		{/if}
		<div class="set-row">
			<label for="{p.id}-model"><span>Model</span><span class="fs" class:err={st('model') !== 'Saved' && st('model') !== 'Saving…'}>{st('model')}</span></label>
			{#if models}
				<select id="{p.id}-model" class="field" bind:value={model} onchange={() => saveSetting(k('model'), model, 0, onchange)}>
					{#if model && !models.some((m) => m.id === model)}<option value={model}>{model}</option>{/if}
					{#each models as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
				</select>
			{:else}
				<input id="{p.id}-model" class="field" bind:value={model} placeholder="Model id" oninput={() => model && saveSetting(k('model'), model, 500, onchange)} />
			{/if}
		</div>
		<div class="test">
			<button class="btn" onclick={test} disabled={testing}>{testing ? 'Testing…' : 'Test'}</button>
			{#if result}<span class="t-small" class:err={!result.ok} role="status">{result.ok ? 'Working' : (result.message ?? 'Not working')}</span>{/if}
		</div>
		{#if !p.healthy && p.message && !result}<p class="t-small err">{p.message}</p>{/if}
	{/if}
</section>

<style>
	.card { background: var(--surface); border-radius: 16px; padding: 4px 16px 12px; margin: 8px 0; }
	.card.off { padding-bottom: 4px; }
	header { display: flex; align-items: center; gap: 8px; min-height: 52px; }
	h3 { margin: 0; }
	.grow { flex: 1; }
	.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
	.dot.ok { background: #34c759; }
	.test { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
	.err { color: var(--danger); }
	p { margin: 8px 0 0; }
</style>
