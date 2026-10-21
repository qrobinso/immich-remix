<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, post } from '#lib/api.ts';

	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		error = '';
		try {
			await post('/api/login', { password });
			const next = page.url.searchParams.get('next') ?? '/';
			await goto(next.startsWith('/') && !next.startsWith('//') ? next : '/', { replace: true });
		} catch (err) {
			error = err instanceof ApiError && err.status === 429 ? 'Too many attempts. Wait a few minutes.' : err instanceof ApiError && err.status === 401 ? 'Wrong passcode.' : 'Cannot reach the server.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Sign in · Remix</title></svelte:head>
<form onsubmit={submit}>
	<h1 class="t-title">Remix</h1>
	<label class="t-small muted" for="pw">Passcode</label>
	<input id="pw" class="field" type="password" autocomplete="current-password" bind:value={password} required />
	{#if error}<p class="err t-small" role="alert">{error}</p>{/if}
	<button class="btn btn-primary" disabled={busy || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
</form>

<style>
	form {
		min-height: 100dvh; box-sizing: border-box; max-width: 320px; margin: 0 auto; padding: 24px 24px calc(48px + env(safe-area-inset-bottom));
		display: flex; flex-direction: column; justify-content: flex-end; gap: 10px;
	}
	h1 { margin: 0 0 12px; }
	.err { margin: 0; color: var(--danger); }
</style>
