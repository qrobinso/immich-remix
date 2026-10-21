import type { Job, JobResult } from './types';

/** Saving deletes the cached file, so a saved result is served from its new Immich asset. */
export function resultSrc(job: Job, r: JobResult, kind: 'image' | 'video' = job.media_type === 'video' ? 'video' : 'image'): string {
	if (r.saved && r.saved_asset_id) return kind === 'video' ? `/api/assets/${r.saved_asset_id}/video` : `/api/assets/${r.saved_asset_id}/thumb?size=preview`;
	return r.url;
}
export const sourceThumb = (job: Job) => `/api/assets/${job.source_asset_id}/thumb?size=preview`;
