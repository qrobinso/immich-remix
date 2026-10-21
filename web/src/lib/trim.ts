export interface Trim { start: number; end: number }

const MIN_LEN = 0.1;

/** Default clip: from 0 up to the backend's limit (or the whole video). */
export const defaultTrim = (duration: number, max: number | null): Trim =>
	({ start: 0, end: max == null ? duration : Math.min(duration, max) });

/** Keeps 0 <= start < end <= duration and end - start <= max (when max is set). */
export function clampTrim(start: number, end: number, duration: number, max: number | null): Trim {
	const gap = Math.min(MIN_LEN, duration);
	const s = Math.min(Math.max(start, 0), duration - gap);
	let e = Math.min(Math.max(end, s + gap), duration);
	if (max != null && e - s > max) e = s + max;
	return { start: s, end: e };
}
