<script lang="ts">
	import { ApiError, errText, get, post, put } from '#lib/api.ts';
	import type { ProviderMedia, ProviderStatus, StyleCategory, StyleForm } from '#lib/types.ts';

	let { id = null, categories, providers, existingIds, onsaved }: {
		id?: string | null; categories: StyleCategory[]; providers: ProviderStatus[]; existingIds: string[]; onsaved: () => void;
	} = $props();

	let dlg: HTMLDialogElement;
	let editId = $state<string | null>(null); // fixed once the style exists on the server
	let f = $state<StyleForm>(blank());
	let error = $state('');
	let busy = $state(false);
	let previewKey = $state(0);
	let hasPreview = $state(false);
	let estimate = $state<{ cost: number; provider: string } | null>(null);
	let note = $state('');

	function blank(): StyleForm {
		return { id: '', name: '', category: 'scenes', media_types: ['image'], prompt: '', negative_prompt: null, strength: null, default_provider: {} };
	}
	/** "Test Neon" -> test_neon; adds _2, _3 … so a new style never overwrites an existing one. */
	function slug(name: string) {
		const base = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'style';
		let s = base, n = 2;
		while (existingIds.includes(s)) s = `${base}_${n++}`;
		return s;
	}
	export async function open() {
		error = note = ''; estimate = null; hasPreview = false;
		editId = id;
		f = blank();
		dlg.showModal();
		if (id) {
			try {
				f = await get<StyleForm>(`/api/styles/${id}`);
				hasPreview = categories.some((c) => c.styles.some((s) => s.id === id && s.preview_url));
			} catch (e) { error = errText(e, 'Could not load this style'); }
		}
	}
	const toggleMedia = (m: ProviderMedia) => {
		f.media_types = f.media_types.includes(m) ? f.media_types.filter((x) => x !== m) : [...f.media_types, m];
	};
	const choices = (m: ProviderMedia) => providers.filter((p) => p.media_types.includes(m));
	const generators = $derived(providers.filter((p) => p.healthy && p.can_generate));

	async function save() {
		if (!f.name.trim() || !f.prompt.trim() || !f.media_types.length) { error = 'Add a name, a prompt and at least one media type.'; return; }
		busy = true; error = '';
		const sid = editId ?? slug(f.name);
		const dp = Object.fromEntries(Object.entries(f.default_provider).filter(([m, v]) => v && f.media_types.includes(m as ProviderMedia)));
		try {
			await put(`/api/styles/${sid}`, { ...f, id: sid, name: f.name.trim(), negative_prompt: f.negative_prompt || null, default_provider: dp });
			editId = sid; // stays open so a preview can be added
			note = 'Saved';
			onsaved();
		} catch (e) {
			error = e instanceof ApiError && Array.isArray((e.body as { detail?: unknown })?.detail) ? 'Check the fields and try again.' : errText(e, 'Could not save');
		}
		busy = false;
	}
	async function upload(e: Event) {
		const file = (e.currentTarget as HTMLInputElement).files?.[0];
		if (!file || !editId) return;
		busy = true; error = '';
		const fd = new FormData();
		fd.append('file', file);
		try {
			const r = await fetch(`/api/styles/${editId}/preview`, { method: 'POST', body: fd, credentials: 'same-origin' });
			if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => null));
			hasPreview = true; previewKey++; note = 'Preview saved'; onsaved();
		} catch (err) { error = errText(err, 'Could not use that image'); }
		busy = false;
	}
	async function askEstimate() {
		busy = true; error = '';
		const p = generators.find((g) => g.id === (f.default_provider.image ?? '')) ?? generators[0];
		try {
			const r = await post<{ cost_usd: number | null }>(`/api/styles/${editId}/preview`, { estimate: true, provider_id: p.id });
			estimate = { cost: r.cost_usd ?? 0, provider: p.id };
		} catch (e) { error = errText(e, 'Could not estimate the cost'); }
		busy = false;
	}
	async function generate() {
		if (!estimate) return;
		busy = true; error = '';
		try {
			await post(`/api/styles/${editId}/preview`, { generate: true, provider_id: estimate.provider });
			hasPreview = true; previewKey++; note = 'Preview saved'; onsaved();
		} catch (e) {
			const d = (e as ApiError).body as { detail?: { message?: string } | string };
			error = typeof d?.detail === 'object' && d.detail?.message ? d.detail.message : errText(e, 'Could not generate a preview');
		}
		estimate = null; busy = false;
	}
	const name = (pid: string) => providers.find((p) => p.id === pid)?.name ?? pid;
</script>

<dialog bind:this={dlg} aria-label={id ? 'Edit style' : 'New style'} onclick={(e) => e.target === dlg && dlg.close()}>
	<form class="sheet" onsubmit={(e) => { e.preventDefault(); save(); }}>
		<h2 class="t-title">{editId ? 'Edit style' : 'New style'}</h2>
		<div class="scroll">
			<div class="set-row"><label for="se-name">Name</label><input id="se-name" class="field" bind:value={f.name} maxlength="60" required /></div>
			<div class="set-row"><label for="se-cat">Category</label>
				<select id="se-cat" class="field" bind:value={f.category}>{#each categories as c}<option value={c.id}>{c.name}</option>{/each}</select></div>
			<fieldset>
				<legend class="t-small muted">Works on</legend>
				{#each [['image', 'Photos'], ['video', 'Videos']] as [m, label]}
					<label class="chk"><input type="checkbox" checked={f.media_types.includes(m as ProviderMedia)} onchange={() => toggleMedia(m as ProviderMedia)} />{label}</label>
				{/each}
			</fieldset>
			<div class="set-row"><label for="se-prompt">Prompt</label><textarea id="se-prompt" class="field" rows="4" bind:value={f.prompt} required></textarea></div>
			<div class="set-row"><label for="se-neg">Negative prompt (optional)</label><textarea id="se-neg" class="field" rows="2" value={f.negative_prompt ?? ''} oninput={(e) => (f.negative_prompt = e.currentTarget.value)}></textarea></div>
			<div class="set-row"><label for="se-str">Strength, 0 to 1 (optional)</label>
				<input id="se-str" class="field" type="number" min="0" max="1" step="0.05" value={f.strength ?? ''} oninput={(e) => (f.strength = e.currentTarget.value === '' ? null : Number(e.currentTarget.value))} /></div>
			{#each f.media_types as m (m)}
				<div class="set-row"><label for="se-dp-{m}">Default backend for {m === 'image' ? 'photos' : 'videos'}</label>
					<select id="se-dp-{m}" class="field" value={f.default_provider[m] ?? ''} onchange={(e) => (f.default_provider = { ...f.default_provider, [m]: e.currentTarget.value || undefined })}>
						<option value="">Use the default</option>
						{#each choices(m) as p}<option value={p.id}>{p.name}</option>{/each}
					</select></div>
			{/each}

			<div class="preview">
				<span class="t-small muted">Preview</span>
				{#if !editId}
					<p class="t-small muted">Save the style first, then add a preview.</p>
				{:else}
					<div class="pv-row">
						{#if hasPreview}<img src="/api/styles/{editId}/preview?kind=card&v={previewKey}" alt="Preview of {f.name}" width="96" height="96" />{/if}
						<div class="pv-actions">
							<label class="btn up">Upload image<input type="file" accept="image/*" onchange={upload} class="sr" /></label>
							{#if generators.length && !estimate}<button type="button" class="btn" onclick={askEstimate} disabled={busy}>Generate preview</button>{/if}
						</div>
					</div>
					{#if estimate}
						<p class="t-small" role="status">This will cost about ${estimate.cost.toFixed(2)} with {name(estimate.provider)}.</p>
						<div class="pv-actions">
							<button type="button" class="btn btn-primary" onclick={generate} disabled={busy}>{busy ? 'Generating…' : 'Confirm'}</button>
							<button type="button" class="btn" onclick={() => (estimate = null)} disabled={busy}>Cancel</button>
						</div>
					{/if}
				{/if}
			</div>
		</div>
		{#if error}<p class="t-small err" role="alert">{error}</p>{:else if note}<p class="t-small muted" role="status">{note}</p>{/if}
		<div class="actions">
			<button type="button" class="btn" onclick={() => dlg.close()}>{editId ? 'Done' : 'Cancel'}</button>
			<button class="btn btn-primary" disabled={busy}>Save style</button>
		</div>
	</form>
</dialog>

<style>
	.scroll { max-height: 62dvh; overflow-y: auto; overscroll-behavior: contain; padding-right: 2px; }
	h2 { margin: 0 0 4px; }
	textarea.field { padding: 10px 14px; resize: vertical; }
	fieldset { border: 0; padding: 0; margin: 10px 0; display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
	legend { float: left; margin-right: 12px; padding: 0; line-height: 44px; }
	.chk { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; }
	.chk input { width: 20px; height: 20px; accent-color: var(--accent); }
	.preview { margin: 14px 0 4px; }
	.pv-row { display: flex; gap: 12px; align-items: center; margin-top: 6px; }
	.pv-row img { border-radius: 16px; object-fit: cover; }
	.pv-actions { display: flex; gap: 8px; flex-wrap: wrap; }
	.sr { position: absolute; opacity: 0; width: 1px; height: 1px; }
	.up { position: relative; display: inline-flex; align-items: center; background: var(--line); cursor: pointer; }
	.up:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
	.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
	.err { color: var(--danger); margin: 8px 0 0; }
	p { margin: 6px 0 0; }
</style>
