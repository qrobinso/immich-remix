<!-- Slow diagonal sweep laid over the image while a job runs. -->
<div class="shimmer" aria-hidden="true"></div>

<style>
	.shimmer { position: absolute; inset: 0; overflow: hidden; pointer-events: none; background: rgb(0 0 0 / 0.25); }
	.shimmer::after {
		content: ''; position: absolute; inset: -50%; transform: translateX(-60%) rotate(25deg);
		background: linear-gradient(90deg, transparent 35%, rgb(255 255 255 / 0.28) 50%, transparent 65%);
		animation: sweep 2.6s ease-in-out infinite;
	}
	@keyframes sweep { to { transform: translateX(60%) rotate(25deg); } }
</style>
