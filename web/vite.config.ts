import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			adapter: adapter({ pages: '../server/app/static', assets: '../server/app/static', fallback: 'index.html', precompress: false, strict: false })
		})
	],
	server: { proxy: { '/api': 'http://localhost:8080' } },
	test: { environment: 'jsdom', include: ['src/**/*.test.ts'] }
});
