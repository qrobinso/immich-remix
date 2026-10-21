import { describe, expect, it } from 'vitest';
import { clampTrim, defaultTrim } from './trim.ts';

describe('trim', () => {
	it('default range caps at max', () => expect(defaultTrim(30, 10)).toEqual({ start: 0, end: 10 }));
	it('default range is the full clip when shorter than max', () => expect(defaultTrim(6, 10)).toEqual({ start: 0, end: 6 }));
	it('no limit gives the full duration', () => expect(defaultTrim(42, null)).toEqual({ start: 0, end: 42 }));
	it('clamps a range dragged past the end', () => expect(clampTrim(25, 40, 30, null)).toEqual({ start: 25, end: 30 }));
	it('clamps a negative start', () => expect(clampTrim(-3, 5, 30, null)).toEqual({ start: 0, end: 5 }));
	it('limits the length to max', () => expect(clampTrim(2, 20, 30, 10)).toEqual({ start: 2, end: 12 }));
	it('enforces start < end', () => {
		const r = clampTrim(10, 10, 30, null);
		expect(r.start).toBeLessThan(r.end);
		const r2 = clampTrim(30, 30, 30, null);
		expect(r2.start).toBeLessThan(r2.end);
		expect(r2.end).toBe(30);
	});
});
