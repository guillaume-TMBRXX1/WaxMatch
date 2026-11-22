export type Platform = "vinted" | "leboncoin" | "2ememain" | "discogs" | "ebay";

export interface DiscogsMatch {
  found: boolean;
  id?: number | null;
  title?: string | null;
  url?: string | null;
  marketplace_url?: string | null;
  genres: string[];
  styles: string[];
}

export interface Album {
  spotify_id: string;
  title: string;
  title_clean: string;
  artists: string[];
  primary_artist: string;
  album_type: string;
  release_year: number | null;
  label: string | null;
  cover_url: string | null;
  spotify_url: string | null;
  added_at: string | null;
  genres: string[];
  styles: string[];
  discogs: DiscogsMatch | null;
}

export interface Listing {
  platform: Platform;
  external_id: string;
  title: string;
  url: string;
  price: number | null;
  price_type: string | null;
  total_known: number | null;
  condition: string | null;
  photo_url: string | null;
  format_hint: string | null;
  city: string | null;
  seller_name: string | null;
  seller_is_pro: boolean | null;
  stock?: number | null;
  shipping_cost?: number | null;
  score: number;
  delivered_total: number | null;
  delivery_mode: "main propre" | "envoi" | null;
  shipping_estimate: number | null;
  distance_km: number | null;
  pickup_possible: boolean;
  components: Record<string, number>;
  grade?: string | null;
  reference?: number | null;
  notes: string[];
  also_on: string[];
  under_target?: boolean;
}

export interface AlbumListings {
  spotify_id: string;
  artist: string;
  title: string;
  discogs_reference: number | null;
  discogs_by_condition?: Record<string, number>;
  target_price?: number | null;
  listings: Listing[];
  unreachable: Listing[];
  discogs_market?: DiscogsMarketItem[];
  searches: { platform: Platform; raw_count: number; error: string | null; from_cache: boolean }[];
}

export interface DiscogsMarketItem {
  external_id: string;
  title: string;
  url: string;
  price: number | null;
  format_hint: string | null;
  stock?: number | null;
}

export interface BestRow {
  spotify_id: string;
  artist: string;
  title: string;
  cover_url: string | null;
  offers_count: number;
  discogs_reference: number | null;
  vs_discogs: number | null;
  target_price?: number | null;
  under_target?: boolean;
  best: Listing;
}

export interface Favorite {
  spotify_id: string;
  artist: string;
  album_title: string;
  cover_url: string | null;
  listing: Listing;
  saved_at: number;
  status: "en ligne" | "disparue" | "à vérifier";
  current_price: number | null;
  price_change: number | null;
  last_checked: number | null;
}

export interface Opportunity {
  key: string;
  watch_key: string;
  artist: string;
  title: string;
  cover_url: string | null;
  listing: Listing;
  grade: string;
  buy_total: number;
  resale_estimate: number;
  resale_basis: string;
  margin: number;
  roi: number;
  demand: number;
  risks: string[];
  status: "active" | "disparue";
  first_seen: number;
  last_seen: number;
  decision: "gardee" | "ecartee" | null;
  decision_reason: string | null;
  source: "disque" | "balayage";
  buy_price: number | null;
  buy_fee: number | null;
  buy_shipping: number | null;
  delivery_mode: string | null;
  packaging: number;
  comparables: { platform: string; title: string; url: string; price: number; condition: string | null }[];
  vinted_median: number | null;
  discogs_by_condition: Record<string, number>;
  discogs_lowest: number | null;
  discogs_for_sale: number | null;
  discogs_url: string | null;
}

export interface WatchItem {
  key: string;
  artist: string;
  title: string;
  discogs_id: number;
  year: number | null;
  styles: string[];
  want: number;
  have: number;
  demand: number;
  last_scanned: number | null;
}

export interface ResaleSettings {
  genre: string;
  styles: string[];
  extra_genres: string[];
  watchlist_size: number;
  min_margin: number;
  min_roi: number;
  max_buy: number;
  packaging: number;
  vinted_discount: number;
  discogs_to_vinted: number;
  platforms: ("vinted" | "2ememain" | "ebay" | "leboncoin")[];
  daily_apify_runs: number;
  min_grade: "G+" | "VG" | "VG+" | "NM";
  require_confirmed_vinyl: boolean;
  allow_no_sleeve: boolean;
  exclude_lots: boolean;
  exclude_reissues: boolean;
  exclude_mixed: boolean;
  sweep_queries: string[];
  sweep_max_items: number;
  verify_top: number;
}

export interface ResaleStats {
  watched: number;
  to_review: number;
  kept: number;
  dismissed: number;
  dismissed_reasons: Record<string, number>;
  scanned: number;
  active: number;
  active_margin_total: number;
  best_margin: number;
  seen_total: number;
  seen_last_7_days: number;
  margin_seen_last_7_days: number;
  gone: number;
  observing_since: number | null;
  apify_runs_today: number;
  apify_daily_cap: number;
  ebay_configured: boolean;
}

export interface ResaleStatus {
  running: boolean;
  phase: string;
  total: number;
  done: number;
  opportunities: number;
  new_opportunities: number;
  gone: number;
  apify_runs: number;
  errors: number;
  last_error: string | null;
  filtered?: Record<string, number>;
  filtered_total?: number;
}

export interface UserSettings {
  city: string | null;
  country: string;
  pickup_radius_km: number;
  priority: "price" | "balanced_price" | "balanced" | "pickup";
  platforms: Platform[];
  location_label?: string | null;
}

export interface Me {
  spotify_user_id: string;
  display_name: string | null;
}

export interface ScanStatus {
  running: boolean;
  phase: string;
  total: number;
  done: number;
  albums_with_offers: number;
  listings_found: number;
  errors: number;
  last_error: string | null;
}
