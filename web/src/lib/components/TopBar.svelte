<header>
	<a href="/" aria-label="immich-remix, go to Library">
		<!-- the original (outline) with its remix stacked on top (accent) -->
		<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
			<rect x="2.75" y="6.75" width="12.5" height="14.5" rx="3" fill="none" stroke="var(--muted)" stroke-width="1.5" />
			<rect x="8" y="2" width="14" height="16" rx="3.5" fill="var(--accent)" />
		</svg>
		<span>immich-remix</span>
	</a>
</header>

<style>
	header {
		position: sticky; top: 0; z-index: 10; display: flex; align-items: center;
		height: 52px; padding: env(safe-area-inset-top) 16px 0; box-sizing: content-box;
		background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(16px);
		border-bottom: 1px solid var(--line);
	}
	a { display: inline-flex; align-items: center; gap: 10px; min-height: 44px; color: var(--fg); text-decoration: none; border-radius: 8px; }
	span { font-size: 17px; font-weight: 650; letter-spacing: -0.02em; }
</style>
