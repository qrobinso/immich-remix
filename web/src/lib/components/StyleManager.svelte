<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { del, errText, get, put } from '#lib/api.ts';
	import type { ProviderStatus, StyleCard, StyleCategory, StylesResponse } from '#lib/types.ts';
	import StyleEditor from './StyleEditor.svelte';

	let { providers }: { providers: ProviderStatus[] } = $props();
	let cats = $state<StyleCategory[]>([]);
	let error = $state('');
	let editing = $state<string | null>(null);
	let editor = $state<StyleEditor>();
	let dragId: string | null = null;
	let live = $state(''); // screen-reader announcement after a move
	const allIds = $derived(cats.flatMap((c) => c.styles.map((s) => s.id)));

	async function load() {
		try { cats = (await get<StylesResponse>('/api/styles')).categories; } catch (e) { error = errText(e, 'Could not load styles'); }
	}
	onMount(load);

	async function run(p: Promise<unknown>) {
		error = '';
		try { await p; } catch (e) { error = errText(e); }
		await load();
	}
	/** Moves a style within its category and saves the category's full order. */
	function move(c: StyleCategory, from: number, to: number) {
		if (to < 0 || to >= c.styles.length || from === to) return;
		const list = [...c.styles];
		const [s] = list.splice(from, 1);
		list.splice(to, 0, s);
		c.styles = list;
		live = `${s.name} moved to position ${to + 1} of ${list.length}`;
		run(put(`/api/styles/${s.id}`, { order: list.map((x) => x.id) }));
	}
	const toggleHidden = (s: StyleCard) => run(put(`/api/styles/${s.id}`, { hidden: !s.hidden }));
	const remove = (s: StyleCard) => confirm(s.custom ? `Delete ${s.name}?` : `Reset ${s.name} to the built-in version?`) && run(del(`/api/styles/${s.id}`));
	async function edit(id: string | null) {
		editing = id;
		await tick();
		editor?.open();
	}
</script>

<div class="head"><span class="muted t-small">Hidden styles stay out of the picker.</span><button class="btn" onclick={() => edit(null)}>New style</button></div>
{#if error}<p class="t-small err" role="alert">{error}</p>{/if}
<p class="sr" aria-live="polite">{live}</p>
{#each cats as c (c.id)}
	<details class="cat">
		<summary>{c.name}<span class="muted t-small"> {c.styles.length}</span></summary>
		<ul>
			{#each c.styles as s, i (s.id)}
				<li class:hid={s.hidden} draggable="true"
					ondragstart={() => (dragId = s.id)}
					ondragover={(e) => dragId && c.styles.some((x) => x.id === dragId) && e.preventDefault()}
					ondrop={(e) => { e.preventDefault(); const from = c.styles.findIndex((x) => x.id === dragId); dragId = null; move(c, from, i); }}>
					<span class="grip" aria-hidden="true">⠿</span>
					<span class="nm">{s.name}{#if s.custom}<small class="muted tag">yours</small>{:else if s.override}<small class="muted tag">edited</small>{/if}</span>
					<button class="ic" aria-label="Move {s.name} up" disabled={i === 0} onclick={() => move(c, i, i - 1)}>↑</button>
					<button class="ic" aria-label="Move {s.name} down" disabled={i === c.styles.length - 1} onclick={() => move(c, i, i + 1)}>↓</button>
					<span class="acts"><button class="tx" aria-pressed={s.hidden} onclick={() => toggleHidden(s)}>{s.hidden ? 'Show' : 'Hide'}</button>
					<button class="tx" onclick={() => edit(s.id)}>Edit</button>
					{#if s.custom}<button class="tx err" onclick={() => remove(s)}>Delete</button>
					{:else if s.override}<button class="tx" onclick={() => remove(s)}>Reset to built-in</button>{/if}</span>
				</li>
			{/each}
		</ul>
	</details>
{/each}
	<StyleEditor bind:this={editor} id={editing} categories={cats} {providers} existingIds={allIds} onsaved={load} />

<style>
	.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 4px 0 8px; }
	.cat { background: var(--surface); border-radius: 16px; margin: 6px 0; padding: 0 8px; }
	summary { min-height: 48px; display: flex; align-items: center; gap: 6px; padding: 0 8px; font-weight: 600; cursor: pointer; }
	ul { list-style: none; margin: 0; padding: 0 0 6px; }
	li { display: flex; flex-wrap: wrap; align-items: center; gap: 0 2px; border-top: 1px solid var(--line); padding: 2px 0; }
	li.hid .nm { opacity: 0.5; text-decoration: line-through; }
	.grip { width: 28px; text-align: center; color: var(--muted); cursor: grab; }
	.nm { flex: 1 1 120px; min-width: 0; overflow-wrap: anywhere; }
	.ic, .tx { min-width: 44px; min-height: 44px; border: 0; background: none; border-radius: 12px; }
	.ic:disabled { opacity: 0.3; cursor: default; }
	.tx { font-size: 13px; padding: 0 8px; color: var(--accent); font-weight: 600; }
	.tx.err, .err { color: var(--danger); }
	.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
	small { font-size: 12px; }
	.tag { margin-left: 6px; }
	.acts { flex: 1 0 100%; display: flex; padding-left: 30px; margin-top: -8px; }
</style>
