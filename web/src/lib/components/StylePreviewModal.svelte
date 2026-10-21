<script lang="ts">
	let { name = '', src = null }: { name?: string; src?: string | null } = $props();
	let dlg: HTMLDialogElement;
	export const open = () => dlg.showModal();
</script>

<dialog bind:this={dlg} class="full" aria-label="{name} preview" onclick={() => dlg.close()}>
	<div class="frame">
		{#if src}<img src={src} alt="Example of the {name} style" />{:else}<p class="muted">No preview for this style yet.</p>{/if}
		<p class="t-title">{name}</p>
		<button class="btn" onclick={() => dlg.close()}>Close</button>
	</div>
</dialog>

<style>
	dialog.full { margin: 0; width: 100%; height: 100%; max-height: none; background: rgb(0 0 0 / 0.92); animation: none; }
	.frame { height: 100%; box-sizing: border-box; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 16px; color: #fff; }
	img { max-width: 100%; max-height: 72dvh; border-radius: 16px; object-fit: contain; }
	p { margin: 0; }
</style>
