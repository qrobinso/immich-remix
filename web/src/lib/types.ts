// Mirrors the JSON of server/app/api/*.py. Keep in sync with the routes.

export type MediaType = 'photo' | 'video'; // asset cards (Immich vocabulary)
export type ProviderMedia = 'image' | 'video'; // styles, providers, jobs (backend vocabulary)
export type ProviderId = 'gemini' | 'openai' | 'stability' | 'runway' | 'luma' | 'comfyui';

export interface ImmichStatus { ok: boolean; version: string | null; user: string | null; error: string | null }
export interface ProviderStatus {
	id: ProviderId; name: string; media_types: ProviderMedia[]; leaves_network: boolean;
	healthy: boolean; message: string | null; price_per_output: { image?: number; video?: number } | null;
	max_variations: { image?: number; video?: number }; max_video_seconds: number | null; typical_seconds: number | null;
}
export interface Status { immich: ImmichStatus; providers: ProviderStatus[] }

export interface Person { id: string; name: string }
export interface Place { kind: 'city' | 'state' | 'country'; value: string }
export interface AssetCard {
	id: string; type: MediaType; taken_at: string; ratio: number;
	duration_s: number | null; thumbhash: string | null; alt: string | null;
}
export interface SearchPage { items: AssetCard[]; next_page: number | null }
export interface SearchQuery {
	query?: string | null; person_ids?: string[]; place?: Place | null;
	date_from?: string | null; date_to?: string | null; type?: 'all' | MediaType; page?: number; size?: number;
}

export interface StyleCard {
	id: string; name: string; media_types: ProviderMedia[]; preview_url: string | null; builtin: boolean; hidden: boolean; default_provider: { image?: ProviderId; video?: ProviderId };
}
export interface StyleCategory { id: string; name: string; styles: StyleCard[] }
export interface StylesResponse { categories: StyleCategory[] }

export type JobStatus = 'queued' | 'running' | 'done' | 'failed';
export interface JobEvent { status: JobStatus; message?: string; error_code?: string; [k: string]: unknown }
export interface JobCreate {
	asset_id: string; style_id?: string | null; custom_prompt?: string | null; provider_id?: string | null;
	variations?: number; clip_start?: number | null; clip_end?: number | null;
}
export interface JobResult {
	id: string; index: number; url: string; mime: string | null; width: number | null; height: number | null;
	duration_s: number | null; saved_asset_id: string | null; discarded: boolean;
	saved: boolean; save_error: string | null;
	failed_step: string | null; // the save step to resume from when save_error is set
}
export interface Job {
	id: string; source_asset_id: string; media_type: MediaType; style_id: string | null; custom_prompt: string | null;
	provider_id: string | null; provider_model: string | null; variations: number;
	clip_start_s: number | null; clip_end_s: number | null; segmented: number; status: JobStatus;
	error_code: string | null; error_message: string | null; cost_estimate_usd: number | null;
	created_at: string; finished_at: string | null; style_name: string | null; results: JobResult[];
}
export interface History { items: Job[]; next_page: number | null }
export type SaveOutcome = { asset_id: string; link: string };
export type PartialSave = { asset_id: string | null; failed_step: string; error: string }; // 207 (asset kept) or 502

export type SecretSetting = { set: boolean; source: 'env' | 'db' };
export interface SettingsProvider {
	id: ProviderId; name: string; media_types: MediaType[]; enabled: boolean; healthy: boolean; message: string | null;
	key_set: boolean; key_source: 'env' | 'db' | null; model: string | null; url: string | null;
}
export interface Settings {
	values: Record<string, unknown>; // secret keys appear as SecretSetting
	sources: Record<string, 'env' | 'db' | 'default'>;
	providers: SettingsProvider[];
}
export interface ModelInfo { id: string; label: string; media_types: MediaType[] }
export type ModelsResponse = ModelInfo[] | { error: string; fallback: true };
