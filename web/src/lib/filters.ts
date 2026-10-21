import type { Place, SearchQuery } from './types';

export interface Filters {
	query: string;
	people: { id: string; name: string }[];
	place: Place | null;
	dateFrom: string;
	dateTo: string;
	type: 'all' | 'photo' | 'video';
}

export const emptyFilters = (): Filters => ({ query: '', people: [], place: null, dateFrom: '', dateTo: '', type: 'all' });

export function toSearchBody(f: Filters, page: number): SearchQuery {
	const q = f.query.trim();
	return {
		...(q ? { query: q } : {}),
		person_ids: f.people.map((p) => p.id),
		place: f.place,
		date_from: f.dateFrom || null,
		date_to: f.dateTo || null,
		type: f.type,
		page
	};
}

// People are "id|name" and the place is "kind:value"; only the first separator splits, so names may contain either.
export function toParams(f: Filters): URLSearchParams {
	const u = new URLSearchParams();
	if (f.query.trim()) u.set('q', f.query.trim());
	for (const p of f.people) u.append('p', `${p.id}|${p.name}`);
	if (f.place) u.set('place', `${f.place.kind}:${f.place.value}`);
	if (f.dateFrom) u.set('from', f.dateFrom);
	if (f.dateTo) u.set('to', f.dateTo);
	if (f.type !== 'all') u.set('type', f.type);
	return u;
}

export function fromParams(u: URLSearchParams): Filters {
	const place = u.get('place');
	const i = place ? place.indexOf(':') : -1;
	const kind = place?.slice(0, i);
	const type = u.get('type');
	return {
		query: u.get('q') ?? '',
		people: u.getAll('p').flatMap((s) => {
			const j = s.indexOf('|');
			return j > 0 ? [{ id: s.slice(0, j), name: s.slice(j + 1) }] : [];
		}),
		place: place && (kind === 'city' || kind === 'state' || kind === 'country') ? { kind, value: place.slice(i + 1) } : null,
		dateFrom: u.get('from') ?? '',
		dateTo: u.get('to') ?? '',
		type: type === 'photo' || type === 'video' ? type : 'all'
	};
}
