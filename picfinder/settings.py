"""Impostazioni dell'app, salvate in settings.json (valgono per finestra e riga di comando)."""
from __future__ import annotations

import json
import re
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .plugins import user_templates_dir


PAUSE_SCALE = {"full": 1.0, "half": 0.5, "min": 0.0}


@dataclass
class ProxyEntry:
    url: str
    enabled: bool = True
    name: str = ""
    latency_ms: float | None = None   # ultimo test
    ok: bool | None = None            # ultimo test riuscito?
    last_error: str = ""


@dataclass
class Settings:
    # --- Generale
    dest_dir: str = str(Path.home() / "Downloads" / "AllDownload")
    theme: str = "system"                 # system | light | dark
    language: str = "system"              # system | it | en
    notify_when_done: bool = True
    open_folder_when_done: bool = False
    reduce_motion: bool = False
    show_menubar: bool = True
    fan_tip_shown: bool = False           # consigli per OnlyFans/Fansly già mostrati             # icona nella barra dei menu con avanzamento e pausa
    # --- Aggiornamenti
    check_updates: bool = True            # controlla da solo, al massimo una volta al giorno
    github_token: str = ""                # solo per repo privato: token di sola lettura (mai nei log)
    skip_version: str = ""                # «Salta questa versione»
    last_update_check: float = 0.0           # niente animazioni di movimento (vale anche l'opzione di sistema)
    # --- Download
    parallel: int = 4                     # file insieme in totale
    per_host: int = 2                     # per server, se il template non dice niente
    skip_downloaded: bool = True
    name_pattern: str = ""                # 9: es. «{profilo}_{data}_{n}» (vuoto = nome originale)
    file_dates: bool = True               # 10: data del post (o del server) sul file
    save_captions: bool = False           # 10: didascalia in «foto.jpg.txt»
    verify_files: bool = True             # 12: foto e video interi, se no si riscaricano
    reserve_gb: int = 1                   # 11: spazio da lasciare sempre libero          # non riscaricare i file già scaricati (se ci sono ancora sul disco)
    pauses: str = "full"                 # full | half | min  (pause del template tra un file e l'altro)
    retries: int = 3
    timeout: int = 30                     # secondi
    speed_limit_kbps: int = 0             # 0 = nessun limite
    default_conflicts: str = "same_size"  # same_size | do_not_save | rename | overwrite
    folder_per_link: bool = True          # una cartella per ogni link (nome del profilo / album)
    split_by_type: bool = True            # dentro: Foto, Video, Altri
    adaptive: bool = True                 # 3: connessioni per server che crescono piano e scendono ai 429
    segments: int = 4                     # 1: pezzi insieme per i file grandi (1 = mai)
    http2: bool = True                    # 2: più file su una connessione, se il server lo permette
    dup_images: str = "mark"              # 15: off | mark | move  (foto uguali con nome diverso)
    # --- Orari e limiti
    schedule_enabled: bool = False        # 9: scarica solo in questa fascia oraria
    schedule_start: str = "01:00"
    schedule_end: str = "07:00"
    pause_on_battery: bool = False        # 9: pausa se il computer va a batteria
    bandwidth_share: int = 0              # 10: usa solo questa % della linea (0 = tutta)
    warn_requests: int = 3000             # 12: avviso dopo N richieste al giorno allo stesso sito (0 = mai)
    watch_check_minutes: int = 10         # 16: ogni quanto controllare i progetti osservati
    # --- Rete
    proxy_mode: str = "off"               # off | fastest | first
    proxies: list[ProxyEntry] = field(default_factory=list)
    proxy_list_url: str = ""              # link di una lista (es. Webshare): si scarica a ogni avvio
    proxy_test_url: str = "https://www.gstatic.com/generate_204"
    custom_user_agent: str = ""
    # --- Anteprime
    auto_thumbs: bool = False
    preview_max_mb: int = 15
    ffmpeg_path: str = ""                 # vuoto = cerca da solo
    # --- Browser interno
    browser_auto_continue: int = 10       # secondi, solo nella coda dei progetti
    # --- Registro
    verbose_log: bool = False
    keep_logs: int = 20

    # ------------------------------------------------------------------
    @staticmethod
    def path() -> Path:
        custom = os.environ.get("PICFINDER_SETTINGS")
        return Path(custom) if custom else user_templates_dir().parent / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        data["proxies"] = [ProxyEntry(**{k: v for k, v in p.items() if k in ProxyEntry.__dataclass_fields__})
                           for p in raw.get("proxies", []) if isinstance(p, dict) and p.get("url")]
        s = cls(**data)
        s.clamp()
        return s

    def save(self) -> None:
        self.clamp()
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def clamp(self) -> None:
        self.parallel = min(max(int(self.parallel), 1), 16)
        self.per_host = min(max(int(self.per_host), 1), 8)
        if self.pauses not in PAUSE_SCALE:
            self.pauses = "full"
        self.retries = min(max(int(self.retries), 1), 10)
        self.segments = min(max(int(self.segments), 1), 8)
        self.bandwidth_share = min(max(int(self.bandwidth_share), 0), 99)
        self.warn_requests = max(int(self.warn_requests), 0)
        if self.dup_images not in ("off", "mark", "move"):
            self.dup_images = "mark"
        for k in ("schedule_start", "schedule_end"):
            if not re.match(r"^\d{1,2}:\d{2}$", str(getattr(self, k) or "")):
                setattr(self, k, "01:00" if k == "schedule_start" else "07:00")
        self.timeout = min(max(int(self.timeout), 5), 300)
        self.speed_limit_kbps = max(int(self.speed_limit_kbps), 0)
        self.preview_max_mb = min(max(int(self.preview_max_mb), 1), 200)
        self.browser_auto_continue = min(max(int(self.browser_auto_continue), 2), 120)
        self.keep_logs = min(max(int(self.keep_logs), 1), 200)
        self.reserve_gb = min(max(int(self.reserve_gb), 0), 500)
        self.name_pattern = (self.name_pattern or "").strip()[:120]
        if self.theme not in ("system", "light", "dark"):
            self.theme = "system"
        if not re.match(r"https?://[^\s\"']+$", (self.proxy_test_url or "").strip()):
            self.proxy_test_url = "https://www.gstatic.com/generate_204"
        if self.proxy_list_url and not re.match(r"https?://\S+$", self.proxy_list_url.strip()):
            self.proxy_list_url = ""
        if self.proxy_mode not in ("off", "fastest", "first"):
            self.proxy_mode = "off"
        if self.default_conflicts not in ("same_size", "do_not_save", "rename", "overwrite"):
            self.default_conflicts = "same_size"

    def enabled_proxies(self) -> list[ProxyEntry]:
        return [p for p in self.proxies if p.enabled and p.url.strip()]
