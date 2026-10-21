<script lang="ts">
	let { bottom = 'calc(68px + env(safe-area-inset-bottom))', message, href, actionLabel, onaction, ondismiss }: {
		bottom?: string;
		message: string; href?: string; actionLabel?: string; onaction?: () => void; ondismiss: () => void;
	} = $props();

	$effect(() => {
		message;
		const t = setTimeout(ondismiss, 5000);
		return () => clearTimeout(t);
	});
</script>

<div class="toast" style:bottom role="status" aria-live="polite">
	<span>{message}</span>
	{#if href}<a href={href} target="_blank" rel="noopener">Open in Immich</a>{/if}
	{#if onaction}<button onclick={onaction}>{actionLabel ?? 'Retry'}</button>{/if}
</div>

<style>
	.toast {
		position: fixed; z-index: 70; left: 12px; right: 12px;
		max-width: 480px; margin: 0 auto; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
		padding: 6px 8px 6px 16px; border-radius: 16px; background: var(--fg); color: var(--bg);
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.35); animation: toast-in 200ms ease-out;
	}
	span { flex: 1; font-weight: 600; }
	a, button { min-height: 44px; min-width: 44px; display: inline-grid; place-items: center; padding: 0 12px; border: 0; background: none; font-weight: 700; color: inherit; text-decoration: underline; }
	@keyframes toast-in { from { transform: translateY(12px); opacity: 0; } }
</style>
