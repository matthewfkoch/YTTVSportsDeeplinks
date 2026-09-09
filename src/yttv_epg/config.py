from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = Field(default=8095, validation_alias="YTTV_EPG_PORT")
    data_dir: Path = Field(default=Path("data"), validation_alias="YTTV_EPG_DATA_DIR")
    secret: str = Field(default="", validation_alias="YTTV_EPG_SECRET")
    public_base_url: str = Field(default="http://127.0.0.1:8095", validation_alias="PUBLIC_BASE_URL")
    lane_count: int = Field(default=128, validation_alias="LANE_COUNT")
    start_channel: int = Field(default=9100, validation_alias="START_CHANNEL")
    refresh_seconds: int = Field(default=120, validation_alias="REFRESH_SECONDS")
    fallback_duration_min: int = Field(default=180, validation_alias="FALLBACK_DURATION_MIN")
    max_hubs: int = Field(default=16, validation_alias="MAX_HUBS")
    epg_pages: int = Field(default=24, validation_alias="EPG_PAGES")
    hub_pages: int = Field(default=20, validation_alias="HUB_PAGES")
    hidden_sports: str = Field(default="", validation_alias="HIDDEN_SPORTS")
    hidden_channels: str = Field(default="", validation_alias="HIDDEN_CHANNELS")
    admin_user: str = Field(default="", validation_alias="ADMIN_USER")
    admin_password: str = Field(default="", validation_alias="ADMIN_PASSWORD")
    allow_debug: bool = Field(default=False, validation_alias="ALLOW_DEBUG")
    package_name: str = Field(
        default="com.google.android.youtube.tvunplugged",
        validation_alias="YTTV_PACKAGE",
    )
    alternate_package_name: str = Field(
        default="com.amazon.firetv.youtube.tv",
        validation_alias="YTTV_ALT_PACKAGE",
    )
    enable_chrome: bool = Field(default=True, validation_alias="ENABLE_CHROME")
    chrome_profile: Optional[str] = Field(default=None, validation_alias="CHROME_PROFILE")
    espn_schedule: bool = Field(default=True, validation_alias="ESPN_SCHEDULE")
    cdp_url: str = Field(default="http://127.0.0.1:9222", validation_alias="CDP_URL")
    novnc_port: int = Field(default=7900, validation_alias="NOVNC_PORT")
    novnc_public_url: str = Field(default="", validation_alias="NOVNC_PUBLIC_URL")

    @property
    def admin_locked(self) -> bool:
        return bool(self.admin_user and self.admin_password)

    @property
    def chrome_profile_dir(self) -> Path:
        if self.chrome_profile and self.chrome_profile.strip():
            return Path(self.chrome_profile)
        return self.data_dir / "chrome-profile"

    @property
    def hidden_sports_list(self) -> list[str]:
        from yttv_epg.sports import parse_sport_list

        return parse_sport_list(self.hidden_sports)

    @property
    def hidden_channels_list(self) -> list[str]:
        from yttv_epg.sports import parse_sport_list

        return parse_sport_list(self.hidden_channels)


settings = Settings()
