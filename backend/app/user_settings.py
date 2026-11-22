"""Réglages utilisateur : localisation, rayon de main propre, priorité du score, plateformes."""

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["price", "balanced_price", "balanced", "pickup"]
PlatformName = Literal["vinted", "leboncoin", "2ememain", "discogs", "ebay"]
APIFY_PLATFORMS = {"vinted", "leboncoin", "2ememain"}  # interrogées via Apify (Discogs, eBay : API officielles)

# Pondérations du score (total 100) selon la priorité choisie.
PRESETS: dict[str, dict[str, float]] = {
    "price": {"price": 65, "deal": 15, "proximity": 5, "trust": 12, "freshness": 3},
    "balanced_price": {"price": 50, "deal": 15, "proximity": 15, "trust": 15, "freshness": 5},
    "balanced": {"price": 40, "deal": 15, "proximity": 25, "trust": 15, "freshness": 5},
    "pickup": {"price": 30, "deal": 10, "proximity": 45, "trust": 12, "freshness": 3},
}


class SettingsInput(BaseModel):
    city: str | None = Field(None, description="Ville, ex. « Namur »")
    country: str = Field("BE", description="Code pays : BE, FR, LU, NL…")
    pickup_radius_km: int = Field(30, ge=0, le=300)
    priority: Priority = Field(
        "balanced_price",
        description="price = prix avant tout ; balanced_price = équilibre tendance prix ; "
        "balanced = équilibre ; pickup = main propre avant tout",
    )
    platforms: list[PlatformName] = Field(default_factory=lambda: ["vinted", "2ememain", "discogs"])


class UserSettings(SettingsInput):
    latitude: float | None = None
    longitude: float | None = None
    location_label: str | None = None  # nom complet trouvé par le géocodage, pour vérification

    @property
    def weights(self) -> dict[str, float]:
        return PRESETS[self.priority]

    @property
    def apify_platforms(self) -> list[str]:
        return [p for p in self.platforms if p in APIFY_PLATFORMS]


class SettingsStore:
    def __init__(self, pool=None):
        self.pool = pool
        self.memory: dict[str, UserSettings] = {}

    async def get(self, user_id: str) -> UserSettings:
        if user_id in self.memory:
            return self.memory[user_id]
        if self.pool is not None:
            data = await self.pool.fetchval("select data from user_settings where spotify_user_id = $1", user_id)
            if data:
                self.memory[user_id] = UserSettings.model_validate(data)
                return self.memory[user_id]
        return UserSettings()

    async def put(self, user_id: str, settings: UserSettings) -> None:
        self.memory[user_id] = settings
        if self.pool is not None:
            await self.pool.execute(
                """
                insert into user_settings (spotify_user_id, data) values ($1, $2)
                on conflict (spotify_user_id) do update set data = excluded.data, updated_at = now()
                """,
                user_id,
                settings.model_dump(mode="json"),
            )
