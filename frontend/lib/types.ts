export type Platform = "vinted" | "leboncoin" | "2ememain" | "discogs";

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
}

export interface AlbumListings {
  spotify_id: string;
  artist: string;
  title: string;
  discogs_reference: number | null;
  discogs_by_condition?: Record<string, number>;
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
  best: Listing;
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
