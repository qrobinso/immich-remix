import { describe, expect, it } from 'vitest';
import { emptyFilters, fromParams, toParams, toSearchBody, type Filters } from './filters.ts';

const full: Filters = {
	query: 'beach',
	people: [{ id: 'a1', name: 'Ann | Lee' }, { id: 'b2', name: 'Bo' }],
	place: { kind: 'city', value: 'Lisbon: Alfama' },
	dateFrom: '2020-01-01',
	dateTo: '2020-12-31',
	type: 'video'
};

describe('toSearchBody', () => {
	it('maps all fields', () => {
		expect(toSearchBody(full, 3)).toEqual({
			query: 'beach', person_ids: ['a1', 'b2'], place: { kind: 'city', value: 'Lisbon: Alfama' },
			date_from: '2020-01-01', date_to: '2020-12-31', type: 'video', page: 3
		});
	});
	it('omits an empty query', () => {
		expect(toSearchBody({ ...full, query: '  ' }, 1)).not.toHaveProperty('query');
	});
	it('passes type all through', () => {
		expect(toSearchBody(emptyFilters(), 1).type).toBe('all');
	});
});

describe('url round trip', () => {
	it('preserves filters', () => {
		expect(fromParams(new URLSearchParams(toParams(full).toString()))).toEqual(full);
	});
	it('empty filters give an empty query string', () => {
		expect(toParams(emptyFilters()).toString()).toBe('');
		expect(fromParams(new URLSearchParams(''))).toEqual(emptyFilters());
	});
});
