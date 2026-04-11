#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Center, Middle
from textual.screen import Screen
from textual.widgets import (
    Footer, Header, Label, ListItem, ListView,
    Static, TabbedContent, TabPane, LoadingIndicator,
)

MEDIA_EXTS = {
    ".mp3", ".flac", ".wav", ".ogg", ".m4a",
    ".mp4", ".mkv", ".webm", ".avi", ".mov"
}

SPOTIFY_SCOPES = " ".join([
    "user-library-read",
    "user-read-playback-state",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
])


def _build_spotify_client():
    """Blocking: authenticate and return (spotipy.Spotify, None) or (None, error_str)."""
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        return None, "spotipy not installed — run: pip install spotipy"

    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback")

    if not client_id or not client_secret:
        return None, "Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET env vars"

    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            open_browser=True,
        ))
        sp.current_user()  # verify credentials
        return sp, None
    except Exception as e:
        return None, str(e)


class SplashScreen(Screen):
    CSS = """
    SplashScreen {
        align: center middle;
    }
    #splash-box {
        width: 50;
        height: 12;
        border: double $accent;
        padding: 1 2;
        align: center middle;
        layout: vertical;
    }
    #splash-title {
        text-style: bold;
        text-align: center;
        color: $accent;
        margin-bottom: 1;
    }
    #splash-sub {
        text-align: center;
        margin-bottom: 1;
    }
    LoadingIndicator {
        height: 3;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="splash-box"):
            yield Static("Terminal Media Player", id="splash-title")
            yield Static("Loading...", id="splash-sub")
            yield LoadingIndicator()


class MediaPlayerApp(App):
    CSS = """
    Screen { layout: vertical; }

    #main { height: 1fr; }

    #left-pane {
        width: 1fr;
        border: round $accent;
    }

    #right-pane {
        width: 40;
        border: round $accent;
        padding: 1;
    }

    #status, #now-playing, #help { margin-bottom: 1; }

    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    ListView { height: 1fr; }

    #local-info, #spotify-info {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "pause", "Pause"),
        Binding("n", "next_track", "Next"),
        Binding("p", "prev_track", "Prev"),
        Binding("h", "seek_back", "-5s"),
        Binding("l", "seek_forward", "+5s"),
        Binding("-", "vol_down", "Vol-"),
        Binding("=", "vol_up", "Vol+"),
        Binding("escape", "go_back", "Back", show=False),
    ]

    def __init__(self, media_dir: str) -> None:
        super().__init__()
        self.media_dir = Path(media_dir).expanduser().resolve()
        self.media_files: list[Path] = []
        self.current_index: int | None = None
        self.mpv: subprocess.Popen | None = None
        self.paused = False

        # Spotify state
        self.sp = None
        self.spotify_playlists: list[dict] = []
        self.spotify_tracks: list[dict] = []
        self.spotify_view: str = "playlists"  # "playlists" or "tracks"
        self.current_playlist: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left-pane"):
                with TabbedContent(id="tabs"):
                    with TabPane("Local", id="tab-local"):
                        yield Label(f"Library: {self.media_dir}", id="local-info")
                        yield ListView(id="media-list")
                    with TabPane("Spotify", id="tab-spotify"):
                        yield Label("Spotify — connecting...", id="spotify-info")
                        yield ListView(id="spotify-list")
            with Vertical(id="right-pane"):
                yield Static("Now Playing: nothing", id="now-playing")
                yield Static("Status: idle", id="status")
                yield Static(
                    "Enter  play / open\n"
                    "Space  pause\n"
                    "h/l    seek ±5s\n"
                    "-/=    volume\n"
                    "n/p    next/prev\n"
                    "Esc    back (Spotify)\n"
                    "r      refresh\n"
                    "q      quit",
                    id="help",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Terminal Media Player"
        self.sub_title = str(self.media_dir)
        self.push_screen(SplashScreen())
        self._load_and_connect()

    @work(thread=True, name="init")
    def _load_and_connect(self) -> None:
        sp, err = _build_spotify_client()

        # fetch playlists in the worker thread
        playlists: list[dict] = []
        if sp:
            try:
                playlists = [{"id": "liked", "name": "\u2665 Liked Songs", "type": "liked"}]
                result = sp.current_user_playlists(limit=50)
                while result:
                    for pl in result["items"]:
                        if pl:
                            playlists.append({"id": pl["id"], "name": pl["name"], "type": "playlist"})
                    result = sp.next(result) if result["next"] else None
            except Exception as e:
                err = str(e)
                sp = None

        def finish(sp=sp, err=err, playlists=playlists):
            self.pop_screen()
            self.load_media()
            if sp:
                self.sp = sp
                self.spotify_playlists = playlists
                self.spotify_view = "playlists"
                lv = self.query_one("#spotify-list", ListView)
                lv.clear()
                for pl in playlists:
                    lv.append(ListItem(Label(pl["name"])))
                self.query_one("#spotify-info", Label).update(
                    f"Spotify \u2014 {len(playlists)} playlists"
                )
            else:
                self.query_one("#spotify-info", Label).update(f"Spotify \u2014 {err}")

        self.call_from_thread(finish)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _active_tab(self) -> str:
        return str(self.query_one("#tabs", TabbedContent).active)

    def update_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"Status: {text}")

    def update_now_playing(self, text: str) -> None:
        self.query_one("#now-playing", Static).update(f"Now Playing: {text}")

    # ── Local playback ────────────────────────────────────────────────────

    def load_media(self) -> None:
        self.media_files = sorted(
            [p for p in self.media_dir.rglob("*")
             if p.is_file() and p.suffix.lower() in MEDIA_EXTS],
            key=lambda p: p.name.lower(),
        )
        lv = self.query_one("#media-list", ListView)
        lv.clear()
        for path in self.media_files:
            lv.append(ListItem(Label(path.name)))
        if self.media_files:
            lv.index = 0
            self.current_index = 0
        self.query_one("#local-info", Label).update(
            f"Library: {self.media_dir} ({len(self.media_files)} files)"
        )
        self.update_status(f"Loaded {len(self.media_files)} local file(s).")

    def stop_mpv(self) -> None:
        if self.mpv and self.mpv.poll() is None:
            self.mpv.terminate()
            try:
                self.mpv.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.mpv.kill()
        self.mpv = None

    def play_local(self, index: int) -> None:
        if not (0 <= index < len(self.media_files)):
            return
        self.current_index = index
        file_path = self.media_files[index]
        self.stop_mpv()
        self.mpv = subprocess.Popen(
            ["mpv", "--force-window=no", str(file_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.paused = False
        self.update_now_playing(file_path.name)
        self.update_status("playing")
        self.query_one("#media-list", ListView).index = index

    def _send_mpv(self, cmd: str) -> None:
        if self.mpv and self.mpv.poll() is None and self.mpv.stdin:
            try:
                self.mpv.stdin.write(cmd + "\n")
                self.mpv.stdin.flush()
            except BrokenPipeError:
                self.update_status("mpv pipe closed")

    # ── Spotify workers ───────────────────────────────────────────────────

    def _fetch_and_show_playlists(self, sp) -> None:
        """Fetch playlists from Spotify (called from a background thread)."""
        try:
            items: list[dict] = [{"id": "liked", "name": "\u2665 Liked Songs", "type": "liked"}]
            result = sp.current_user_playlists(limit=50)
            while result:
                for pl in result["items"]:
                    if pl:
                        items.append({"id": pl["id"], "name": pl["name"], "type": "playlist"})
                result = sp.next(result) if result["next"] else None

            def show(items=items):
                self.spotify_playlists = items
                self.spotify_view = "playlists"
                lv = self.query_one("#spotify-list", ListView)
                lv.clear()
                for pl in items:
                    lv.append(ListItem(Label(pl["name"])))
                self.query_one("#spotify-info", Label).update(
                    f"Spotify \u2014 {len(items)} playlists"
                )
            self.call_from_thread(show)
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    @work(thread=True, name="spotify-load-playlists")
    def reload_spotify_playlists(self) -> None:
        if self.sp:
            self._fetch_and_show_playlists(self.sp)

    @work(thread=True, name="spotify-load-tracks")
    def load_spotify_tracks(self, playlist: dict) -> None:
        sp = self.sp
        if not sp:
            return
        try:
            tracks: list[dict] = []
            if playlist["type"] == "liked":
                result = sp.current_user_saved_tracks(limit=50)
                while result and len(tracks) < 200:
                    for item in result["items"]:
                        t = item["track"]
                        if t:
                            tracks.append({
                                "uri": t["uri"],
                                "name": t["name"],
                                "artist": t["artists"][0]["name"] if t["artists"] else "",
                            })
                    result = sp.next(result) if result["next"] else None
            else:
                result = sp.playlist_items(playlist["id"], limit=50, additional_types=("track",))
                # debug: log raw result to file
                import json
                with open("/tmp/spotify_debug.json", "w") as f:
                    json.dump(result, f, indent=2)
                while result and len(tracks) < 200:
                    for item in result["items"]:
                        if not item:
                            continue
                        # API returns track under "item" or "track" depending on version
                        t = item.get("item") or item.get("track")
                        if not t or not t.get("uri"):
                            continue
                        if t.get("type") != "track":
                            continue
                        tracks.append({
                            "uri": t["uri"],
                            "name": t["name"],
                            "artist": t["artists"][0]["name"] if t.get("artists") else "",
                        })
                    result = sp.next(result) if result.get("next") else None

            pl_name = playlist["name"]
            if not tracks:
                self.call_from_thread(self.update_status, f"No tracks found in {pl_name}")
                return

            def show(tracks=tracks, pl_name=pl_name):
                self.spotify_tracks = tracks
                self.current_playlist = playlist
                self.spotify_view = "tracks"
                lv = self.query_one("#spotify-list", ListView)
                lv.clear()
                for track in tracks:
                    lv.append(ListItem(Label(f"{track['artist']} \u2014 {track['name']}")))
                self.query_one("#spotify-info", Label).update(
                    f"Spotify / {pl_name} ({len(tracks)}) \u2014 Esc to go back"
                )
            self.call_from_thread(show)
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    @work(thread=True, name="spotify-play")
    def play_spotify(self, index: int) -> None:
        sp = self.sp
        if not sp or not (0 <= index < len(self.spotify_tracks)):
            return
        track = self.spotify_tracks[index]
        try:
            devices = sp.devices().get("devices", [])
            active = next((d for d in devices if d["is_active"]), None)
            device = active or (devices[0] if devices else None)
            if not device:
                self.call_from_thread(
                    self.update_status,
                    "No Spotify device found \u2014 open Spotify app first",
                )
                return
            device_id = device["id"]

            if self.current_playlist and self.current_playlist["type"] != "liked":
                sp.start_playback(
                    device_id=device_id,
                    context_uri=f"spotify:playlist:{self.current_playlist['id']}",
                    offset={"position": index},
                )
            else:
                sp.start_playback(device_id=device_id, uris=[track["uri"]])

            artist, name = track["artist"], track["name"]

            def update_ui(artist=artist, name=name):
                self.stop_mpv()
                self.paused = False
                self.update_now_playing(f"{artist} \u2014 {name}")
                self.update_status("playing (Spotify)")
            self.call_from_thread(update_ui)
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    # ── Event handlers ────────────────────────────────────────────────────

    @on(ListView.Selected)
    def on_list_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None:
            return
        if event.list_view.id == "media-list":
            self.play_local(idx)
        elif event.list_view.id == "spotify-list":
            if self.spotify_view == "playlists":
                self.load_spotify_tracks(self.spotify_playlists[idx])
            else:
                self.play_spotify(idx)

    # ── Actions ───────────────────────────────────────────────────────────

    def action_go_back(self) -> None:
        if self._active_tab() == "tab-spotify" and self.spotify_view == "tracks":
            self.reload_spotify_playlists()

    def action_pause(self) -> None:
        if self._active_tab() == "tab-local":
            if self.mpv and self.mpv.poll() is None:
                self._send_mpv("cycle pause")
                self.paused = not self.paused
                self.update_status("paused" if self.paused else "playing")
        else:
            self._spotify_pause_resume()

    @work(thread=True, name="spotify-pause")
    def _spotify_pause_resume(self) -> None:
        sp = self.sp
        if not sp:
            return
        try:
            pb = sp.current_playback()
            if pb and pb["is_playing"]:
                sp.pause_playback()
                self.call_from_thread(self.update_status, "paused (Spotify)")
            else:
                sp.start_playback()
                self.call_from_thread(self.update_status, "playing (Spotify)")
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    def action_seek_back(self) -> None:
        if self._active_tab() == "tab-local":
            self._send_mpv("seek -5")
            self.update_status("seek -5s")
        else:
            self._spotify_seek(-5000)

    def action_seek_forward(self) -> None:
        if self._active_tab() == "tab-local":
            self._send_mpv("seek 5")
            self.update_status("seek +5s")
        else:
            self._spotify_seek(5000)

    @work(thread=True, name="spotify-seek")
    def _spotify_seek(self, delta_ms: int) -> None:
        sp = self.sp
        if not sp:
            return
        try:
            pb = sp.current_playback()
            if pb:
                pos = max(0, pb["progress_ms"] + delta_ms)
                sp.seek_track(pos)
                sign = "+" if delta_ms > 0 else ""
                self.call_from_thread(
                    self.update_status, f"seek {sign}{delta_ms // 1000}s (Spotify)"
                )
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    def action_vol_down(self) -> None:
        if self._active_tab() == "tab-local":
            self._send_mpv("add volume -5")
            self.update_status("volume -5")
        else:
            self._spotify_volume(-5)

    def action_vol_up(self) -> None:
        if self._active_tab() == "tab-local":
            self._send_mpv("add volume 5")
            self.update_status("volume +5")
        else:
            self._spotify_volume(5)

    @work(thread=True, name="spotify-volume")
    def _spotify_volume(self, delta: int) -> None:
        sp = self.sp
        if not sp:
            return
        try:
            pb = sp.current_playback()
            if pb and pb.get("device"):
                vol = max(0, min(100, pb["device"]["volume_percent"] + delta))
                sp.volume(vol)
                self.call_from_thread(self.update_status, f"volume {vol}% (Spotify)")
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    def action_next_track(self) -> None:
        if self._active_tab() == "tab-local":
            if self.current_index is not None and self.media_files:
                self.play_local((self.current_index + 1) % len(self.media_files))
        else:
            self._spotify_skip(1)

    def action_prev_track(self) -> None:
        if self._active_tab() == "tab-local":
            if self.current_index is not None and self.media_files:
                self.play_local((self.current_index - 1) % len(self.media_files))
        else:
            self._spotify_skip(-1)

    @work(thread=True, name="spotify-skip")
    def _spotify_skip(self, direction: int) -> None:
        sp = self.sp
        if not sp:
            return
        try:
            if direction > 0:
                sp.next_track()
                self.call_from_thread(self.update_status, "next (Spotify)")
            else:
                sp.previous_track()
                self.call_from_thread(self.update_status, "prev (Spotify)")
        except Exception as e:
            self.call_from_thread(self.update_status, f"Spotify error: {e}")

    def action_refresh(self) -> None:
        if self._active_tab() == "tab-local":
            self.load_media()
        elif self.spotify_view == "playlists":
            self.reload_spotify_playlists()
        elif self.current_playlist:
            self.load_spotify_tracks(self.current_playlist)

    def on_unmount(self) -> None:
        self.stop_mpv()


if __name__ == "__main__":
    import sys

    media_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    if not os.path.isdir(os.path.expanduser(media_dir)):
        print(f"Not a directory: {media_dir}")
        raise SystemExit(1)

    MediaPlayerApp(media_dir).run()
