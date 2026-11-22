"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Favorite, Listing } from "./types";

const key = (platform: string, id: string) => `${platform}:${id}`;

/** Favoris de l'utilisateur, avec ajout/retrait optimiste (l'étoile réagit tout de suite). */
export function useFavorites() {
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [ids, setIds] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    try {
      const list = await api<Favorite[]>("/favorites");
      setFavorites(list);
      setIds(new Set(list.map((f) => key(f.listing.platform, f.listing.external_id))));
    } catch {
      /* non connecté ou API éteinte : pas d'étoiles */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const isFavorite = useCallback((l: Pick<Listing, "platform" | "external_id">) => ids.has(key(l.platform, l.external_id)), [ids]);

  const toggle = useCallback(
    async (spotifyId: string, listing: Listing) => {
      const k = key(listing.platform, listing.external_id);
      const adding = !ids.has(k);
      setIds((prev) => {
        const next = new Set(prev);
        if (adding) next.add(k);
        else next.delete(k);
        return next;
      });
      try {
        if (adding) {
          await api("/favorites", { method: "POST", body: JSON.stringify({ spotify_id: spotifyId, listing }) });
        } else {
          await api(`/favorites/${encodeURIComponent(listing.platform)}/${encodeURIComponent(listing.external_id)}`, {
            method: "DELETE",
          });
        }
        reload();
      } catch {
        reload(); // annule l'affichage optimiste en relisant l'état réel
      }
    },
    [ids, reload],
  );

  return { favorites, loaded, isFavorite, toggle, reload };
}
