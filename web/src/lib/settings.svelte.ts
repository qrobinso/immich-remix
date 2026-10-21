import { put, errText } from './api';

/** Per-key save state shown next to each field: '' | 'Saving…' | 'Saved' | an error message. */
export const fieldState = $state<Record<string, string>>({});
const timers = new Map<string, ReturnType<typeof setTimeout>>();

/** Saves one setting; delay > 0 debounces typing. Resolves true on success. */
export function saveSetting(key: string, value: unknown, delay = 0, done?: () => void): void {
	clearTimeout(timers.get(key));
	fieldState[key] = '';
	const run = async () => {
		fieldState[key] = 'Saving…';
		try {
			await put('/api/settings', { [key]: value });
			fieldState[key] = 'Saved';
			done?.();
		} catch (e) {
			fieldState[key] = errText(e, 'Could not save');
		}
		setTimeout(() => fieldState[key] === 'Saved' && (fieldState[key] = ''), 2500);
	};
	if (delay) timers.set(key, setTimeout(run, delay));
	else run();
}
