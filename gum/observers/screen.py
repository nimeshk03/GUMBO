from __future__ import annotations
###############################################################################
# Imports                                                                     #
###############################################################################

# — Standard library —
import base64
import logging
import os
import sys
import time
from collections import deque
from typing import Any, Dict, Iterable, List, Optional

import asyncio

# — Third-party —
import mss
from PIL import Image
from pynput import mouse           # still synchronous (macOS path)
from shapely.geometry import box
from shapely.ops import unary_union

# — Platform-specific window management —
if sys.platform == "darwin":
    try:
        import Quartz
    except ImportError:
        Quartz = None
else:
    Quartz = None

if sys.platform.startswith("linux"):
    from ewmh import EWMH as _EWMH
    from Xlib.display import Display as _Display

# — Local —
from .observer import Observer
from ..schemas import Update

# — OpenAI async client —
from openai import AsyncOpenAI

# — Local —
from gum.prompts.screen import TRANSCRIPTION_PROMPT, SUMMARY_PROMPT

###############################################################################
# Window-geometry helpers                                                     #
###############################################################################


def _get_global_bounds() -> tuple[float, float, float, float]:
    """Return a bounding box enclosing all physical displays.

    Returns
    -------
    (min_x, min_y, max_x, max_y) in screen coordinates.
    """
    if sys.platform == "darwin" and Quartz is not None:
        err, ids, cnt = Quartz.CGGetActiveDisplayList(16, None, None)
        if err != Quartz.kCGErrorSuccess:
            raise OSError(f"CGGetActiveDisplayList failed: {err}")

        min_x = min_y = float("inf")
        max_x = max_y = -float("inf")
        for did in ids[:cnt]:
            r = Quartz.CGDisplayBounds(did)
            x0, y0 = r.origin.x, r.origin.y
            x1, y1 = x0 + r.size.width, y0 + r.size.height
            min_x, min_y = min(min_x, x0), min(min_y, y0)
            max_x, max_y = max(max_x, x1), max(max_y, y1)
        return min_x, min_y, max_x, max_y

    # Linux (and fallback): use mss
    with mss.mss() as sct:
        monitors = sct.monitors[1:]  # index 0 is the combined virtual display
        if not monitors:
            return 0.0, 0.0, 0.0, 0.0
        min_x = min(m["left"] for m in monitors)
        min_y = min(m["top"] for m in monitors)
        max_x = max(m["left"] + m["width"] for m in monitors)
        max_y = max(m["top"] + m["height"] for m in monitors)
        return float(min_x), float(min_y), float(max_x), float(max_y)


def _get_visible_windows() -> List[tuple[dict, float]]:
    """List onscreen windows with their visible-area ratio.

    Each tuple is ``(window_info_dict, visible_ratio)`` where *visible_ratio*
    is in ``[0.0, 1.0]``.  Internal system windows are ignored.

    The info dict always contains an ``"ownerName"`` key with the application
    name so that :func:`_is_app_visible` works on both platforms.
    """
    if sys.platform == "darwin":
        return _get_visible_windows_darwin()
    return _get_visible_windows_linux()


def _get_visible_windows_darwin() -> List[tuple[dict, float]]:
    if Quartz is None:
        return []

    _, _, _, gmax_y = _get_global_bounds()

    opts = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListOptionIncludingWindow
    )
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    occupied = None
    result: list[tuple[dict, float]] = []

    for info in wins:
        owner = info.get("kCGWindowOwnerName", "")
        if owner in ("Dock", "WindowServer", "Window Server"):
            continue

        bounds = info.get("kCGWindowBounds", {})
        x, y, w, h = (
            bounds.get("X", 0),
            bounds.get("Y", 0),
            bounds.get("Width", 0),
            bounds.get("Height", 0),
        )
        if w <= 0 or h <= 0:
            continue

        inv_y = gmax_y - y - h  # Quartz→Shapely Y-flip
        poly = box(x, inv_y, x + w, inv_y + h)
        if poly.is_empty:
            continue

        visible = poly if occupied is None else poly.difference(occupied)
        if not visible.is_empty:
            ratio = visible.area / poly.area
            info = dict(info)
            info.setdefault("ownerName", owner)
            result.append((info, ratio))
            occupied = poly if occupied is None else unary_union([occupied, poly])

    return result


def _get_visible_windows_linux() -> List[tuple[dict, float]]:
    """X11 implementation using ewmh + python-xlib.

    _NET_CLIENT_LIST_STACKING is bottom-to-top; we reverse it to get
    front-to-back order so the occlusion logic (which accumulates already-
    occupied area from the front) behaves the same as on macOS.

    X11 uses a top-left origin identical to Shapely, so no Y-flip is needed.
    """
    ew = _EWMH()
    display = _Display()
    root = display.screen().root

    stacking = ew.getClientListStacking()
    if not stacking:
        return []

    # Front-to-back: frontmost window first
    wins = list(reversed(stacking))

    occupied = None
    result: list[tuple[dict, float]] = []

    for win in wins:
        try:
            wm_class = win.get_wm_class()
            # WM_CLASS is (instance, class); class is the conventional app name
            owner = wm_class[1] if wm_class and len(wm_class) >= 2 else ""

            geom = win.get_geometry()
            w, h = geom.width, geom.height
            if w <= 0 or h <= 0:
                continue

            # Translate window-local (0,0) to root/screen coordinates
            coords = win.translate_coords(root, 0, 0)
            x, y = coords.x, coords.y
        except Exception:
            continue

        poly = box(x, y, x + w, y + h)
        if poly.is_empty:
            continue

        visible = poly if occupied is None else poly.difference(occupied)
        if not visible.is_empty:
            ratio = visible.area / poly.area
            info: dict = {"ownerName": owner}
            result.append((info, ratio))
            occupied = poly if occupied is None else unary_union([occupied, poly])

    display.close()
    return result


def _is_app_visible(names: Iterable[str]) -> bool:
    """Return True if any window from names is at least partially visible."""
    targets = set(names)
    return any(
        # "ownerName" is set on both platforms; "kCGWindowOwnerName" is macOS-only
        (info.get("ownerName") or info.get("kCGWindowOwnerName", "")) in targets
        and ratio > 0
        for info, ratio in _get_visible_windows()
    )


def _get_active_window_info() -> dict:
    """Return the name and title of the currently focused window.

    Returns a dict with keys ``app_name`` and ``window_title``.
    Falls back to ``{"app_name": "Unknown", "window_title": ""}`` on any error.
    """
    if sys.platform.startswith("linux"):
        try:
            ew = _EWMH()
            win = ew.getActiveWindow()
            if win:
                wm_class = win.get_wm_class()
                app_name = wm_class[1] if wm_class and len(wm_class) >= 2 else "Unknown"
                raw_title = ew.getWmName(win) or ""
                if isinstance(raw_title, bytes):
                    raw_title = raw_title.decode("utf-8", errors="replace")
                return {"app_name": app_name, "window_title": raw_title}
        except Exception:
            pass

    elif sys.platform == "darwin" and Quartz is not None:
        try:
            opts = (
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListOptionIncludingWindow
            )
            wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
            for info in wins:
                owner = info.get("kCGWindowOwnerName", "")
                if owner in ("Dock", "WindowServer", "Window Server"):
                    continue
                layer = info.get("kCGWindowLayer", 999)
                if layer == 0:
                    title = info.get("kCGWindowName", "")
                    return {"app_name": owner, "window_title": title}
        except Exception:
            pass

    return {"app_name": "Unknown", "window_title": ""}


###############################################################################
# Linux mouse listener (evdev + Xlib position query)                          #
# pynput's Linux backend uses XRecord which does not work under XWayland.     #
# evdev reads /dev/input directly and works on both X11 and Wayland.          #
###############################################################################

if sys.platform.startswith("linux"):
    import threading as _threading
    import evdev as _evdev

    def _start_linux_mouse_listener(loop, on_event):
        """Start an evdev-based mouse listener for Linux/Wayland.

        Only dispatches click and scroll events. Touchpad move events (EV_ABS)
        are intentionally ignored because they fire continuously and would
        prevent the debounce timer from ever expiring.

        Returns a callable that stops all listener threads.
        """
        try:
            x_display = _Display()
            x_root = x_display.screen().root

            def _ptr_pos():
                try:
                    p = x_root.query_pointer()
                    return p.root_x, p.root_y
                except Exception:
                    return 0, 0
        except Exception:
            def _ptr_pos():
                return 0, 0

        def _find_mice():
            mice = []
            for path in _evdev.list_devices():
                try:
                    d = _evdev.InputDevice(path)
                    caps = d.capabilities()
                    has_buttons = _evdev.ecodes.EV_KEY in caps and any(
                        btn in caps[_evdev.ecodes.EV_KEY]
                        for btn in (_evdev.ecodes.BTN_LEFT, _evdev.ecodes.BTN_RIGHT,
                                    _evdev.ecodes.BTN_TOUCH)
                    )
                    has_rel = _evdev.ecodes.EV_REL in caps
                    has_abs = _evdev.ecodes.EV_ABS in caps
                    if has_buttons and (has_rel or has_abs):
                        mice.append(d)
                except Exception:
                    pass
            return mice

        stop_flag = _threading.Event()

        def _read_device(device):
            try:
                for event in device.read_loop():
                    if stop_flag.is_set():
                        break
                    if event.type == _evdev.ecodes.EV_KEY:
                        if event.code in (
                            _evdev.ecodes.BTN_LEFT,
                            _evdev.ecodes.BTN_RIGHT,
                            _evdev.ecodes.BTN_MIDDLE,
                        ) and event.value == 1:
                            x, y = _ptr_pos()
                            asyncio.run_coroutine_threadsafe(on_event(x, y, "click"), loop)
                    elif event.type == _evdev.ecodes.EV_REL:
                        if event.code == _evdev.ecodes.REL_WHEEL:
                            x, y = _ptr_pos()
                            asyncio.run_coroutine_threadsafe(on_event(x, y, "scroll"), loop)
            except Exception:
                pass

        mice = _find_mice()
        threads = []
        for dev in mice:
            t = _threading.Thread(target=_read_device, args=(dev,), daemon=True)
            t.start()
            threads.append(t)

        def stop():
            stop_flag.set()
            for dev in mice:
                try:
                    dev.close()
                except Exception:
                    pass

        return stop, len(mice)


###############################################################################
# Screen observer                                                             #
###############################################################################

class Screen(Observer):
    """Observer that captures and analyzes screen content around user interactions.

    Captures screenshots before and after user interactions (mouse clicks and
    scrolls) and uses a vision LLM to analyze the content. Also injects the
    currently focused application name and window title into the prompt to
    prevent the LLM from misidentifying the active application.

    Args:
        model_name (str): Vision model to use. Defaults to "gpt-4o-mini".
        screenshots_dir (str): Directory to store screenshots.
        skip_when_visible (Optional[str | list[str]]): App names to skip when visible.
        transcription_prompt (Optional[str]): Custom transcription prompt.
        summary_prompt (Optional[str]): Custom summary prompt.
        history_k (int): Number of recent screenshots to keep in history.
        debug (bool): Enable debug logging.
        api_key (str | None): API key override.
        api_base (str | None): API base URL override.
    """

    _CAPTURE_FPS: int = 10
    _DEBOUNCE_SEC: int = 1
    _PERIODIC_SEC: int = 60   # periodic capture interval when no interaction occurs
    _MON_START: int = 1       # first real display in mss

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        screenshots_dir: str = "~/.cache/gum/screenshots",
        skip_when_visible: Optional[str | list[str]] = None,
        transcription_prompt: Optional[str] = None,
        summary_prompt: Optional[str] = None,
        history_k: int = 10,
        debug: bool = False,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self.screens_dir = os.path.abspath(os.path.expanduser(screenshots_dir))
        os.makedirs(self.screens_dir, exist_ok=True)

        self._guard = {skip_when_visible} if isinstance(skip_when_visible, str) else set(skip_when_visible or [])

        self.transcription_prompt = transcription_prompt or TRANSCRIPTION_PROMPT
        self.summary_prompt = summary_prompt or SUMMARY_PROMPT
        self.model_name = model_name

        self.debug = debug

        # state shared with worker
        self._frames: Dict[int, Any] = {}
        self._frame_lock = asyncio.Lock()
        self._history: deque[str] = deque(maxlen=max(0, history_k))
        self._pending_event: Optional[dict] = None
        self._debounce_deadline: float | None = None
        self.client = AsyncOpenAI(
            base_url=api_base or os.getenv("SCREEN_LM_API_BASE") or os.getenv("GUM_LM_API_BASE"),
            api_key=api_key or os.getenv("SCREEN_LM_API_KEY") or os.getenv("GUM_LM_API_KEY") or os.getenv("OPENAI_API_KEY") or "None"
        )

        super().__init__()

    # ────────────────────────────── tiny sync helpers
    @staticmethod
    def _mon_for(x: float, y: float, mons: list[dict]) -> Optional[int]:
        for idx, m in enumerate(mons, 1):
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return idx
        return None

    @staticmethod
    def _encode_image(img_path: str) -> str:
        with open(img_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode()

    # ────────────────────────────── OpenAI Vision (async)
    async def _call_gpt_vision(self, prompt: str, img_paths: list[str]) -> str:
        content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
            for encoded in (await asyncio.gather(
                *[asyncio.to_thread(self._encode_image, p) for p in img_paths]
            ))
        ]
        content.append({"type": "text", "text": prompt})

        rsp = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "text"},
        )
        return rsp.choices[0].message.content

    # ────────────────────────────── I/O helpers
    async def _capture_screenshot(self, tag: str) -> str:
        """Capture a full-screen screenshot.

        Uses spectacle on Linux (works on both X11 and Wayland).
        Falls back to mss on macOS.

        Returns:
            str: Path to the saved JPEG image.
        """
        ts = f"{time.time():.5f}"
        path = os.path.join(self.screens_dir, f"{ts}_{tag}.jpg")

        if sys.platform.startswith("linux"):
            import subprocess
            result = await asyncio.to_thread(
                lambda: subprocess.run(
                    ["spectacle", "-f", "-b", "-n", "-o", path],
                    capture_output=True,
                )
            )
            if result.returncode != 0 or not os.path.exists(path):
                raise RuntimeError(
                    f"spectacle failed (rc={result.returncode}): "
                    f"{result.stderr.decode(errors='replace')}"
                )
            # spectacle saves PNG; convert to JPEG to keep file sizes small
            if path.endswith(".jpg"):
                await asyncio.to_thread(
                    lambda: Image.open(path).convert("RGB").save(path, "JPEG", quality=70)
                )
        else:
            # macOS: use mss directly
            import mss as _mss
            with _mss.mss() as sct:
                frame = sct.grab(sct.monitors[self._MON_START])
            await asyncio.to_thread(
                Image.frombytes("RGB", (frame.width, frame.height), frame.rgb).save,
                path, "JPEG", quality=70,
            )

        return path

    async def _save_frame(self, frame, tag: str) -> str:
        """Save an mss frame as a JPEG image (macOS / legacy path)."""
        ts = f"{time.time():.5f}"
        path = os.path.join(self.screens_dir, f"{ts}_{tag}.jpg")
        await asyncio.to_thread(
            Image.frombytes("RGB", (frame.width, frame.height), frame.rgb).save,
            path,
            "JPEG",
            quality=70,
        )
        return path

    async def _process_and_emit(self, before_path: str, after_path: str) -> None:
        """Process screenshots and emit an update.

        Injects the currently active application name and window title into the
        transcription prompt before calling the vision LLM, so the model uses
        verified metadata rather than inferring the application from visual cues.
        """
        log = logging.getLogger("Screen")
        self._history.append(before_path)
        prev_paths = list(self._history)

        # Build app context header from the currently focused window
        app_info = _get_active_window_info()
        log.info(
            f"[SCREEN] Active window — app='{app_info['app_name']}', "
            f"title='{app_info['window_title']}'"
        )
        app_context = (
            f"ACTIVE APPLICATION CONTEXT:\n"
            f"- Application: {app_info['app_name']}\n"
            f"- Window Title: {app_info['window_title']}\n\n"
        )
        transcription_prompt_with_context = app_context + self.transcription_prompt

        log.info("[SCREEN] Calling vision LLM for transcription...")
        try:
            transcription = await self._call_gpt_vision(
                transcription_prompt_with_context, [before_path, after_path]
            )
            log.info(f"[SCREEN] Transcription received ({len(transcription)} chars)")
        except Exception as exc:
            log.error(f"[SCREEN] Transcription failed: {exc}")
            return

        if not self._is_valid_content(transcription):
            log.warning(
                f"[SCREEN] Invalid transcription content — skipping: "
                f"{transcription[:100] if transcription else 'None'}..."
            )
            return

        prev_paths.append(before_path)
        prev_paths.append(after_path)
        log.info("[SCREEN] Calling vision LLM for summary...")
        try:
            summary = await self._call_gpt_vision(self.summary_prompt, prev_paths)
            log.info(f"[SCREEN] Summary received ({len(summary)} chars)")
        except Exception as exc:
            log.error(f"[SCREEN] Summary failed: {exc}")
            return

        if not self._is_valid_content(summary):
            log.warning(
                f"[SCREEN] Invalid summary content — skipping: "
                f"{summary[:100] if summary else 'None'}..."
            )
            return

        txt = transcription.strip()
        if not self._is_valid_final_content(txt):
            log.warning(
                f"[SCREEN] Invalid final content — skipping: "
                f"{txt[:100] if txt else 'None'}..."
            )
            return

        log.info(f"[SCREEN] Emitting observation to queue ({len(txt)} chars)")
        await self.update_queue.put(Update(content=txt, content_type="input_text"))

    def _is_valid_content(self, content: str) -> bool:
        """Check if content is valid for behavioral analysis."""
        if not content or not content.strip():
            return False

        content_lower = content.lower()

        error_indicators = [
            "failed:", "error:", "rate limit", "timeout", "unable to process",
            "no content", "empty", "invalid", "exception", "429", "500", "503",
            "[transcription failed:", "[summary failed:"
        ]
        for indicator in error_indicators:
            if indicator in content_lower:
                return False

        if len(content.strip()) < 20:
            return False

        prompt_indicators = [
            "transcribe in markdown all the content from the screenshots",
            "provide a detailed description of the actions occurring across the provided images",
            "generate a handful of bullet points and reference specific actions",
            "keep in mind that that the content on the screen is what the user is viewing"
        ]
        for indicator in prompt_indicators:
            if indicator in content_lower:
                return False

        return True

    def _is_valid_final_content(self, content: str) -> bool:
        """Additional validation for final content before sending to behavioral analysis."""
        if not self._is_valid_content(content):
            return False

        content_lower = content.lower()

        transcription_indicators = [
            "markdown", "screenshot", "application:", "window:", "browser:",
            "url:", "file:", "folder:", "text:", "content:", "user", "screen"
        ]
        if any(indicator in content_lower for indicator in transcription_indicators):
            return True

        activity_indicators = [
            "click", "scroll", "typing", "reading", "viewing", "opened", "closed", "switched"
        ]
        return any(indicator in content_lower for indicator in activity_indicators)

    # ────────────────────────────── skip guard
    def _skip(self) -> bool:
        """Return True if capture should be skipped based on visible applications."""
        return _is_app_visible(self._guard) if self._guard else False

    # ────────────────────────────── main async worker
    async def _worker(self) -> None:
        """Main worker that captures and processes screenshots.

        - On Linux: uses evdev for mouse events (Wayland-safe) and spectacle for screenshots.
        - On macOS: uses pynput for mouse events and mss for screenshots.
        - Runs a periodic capture every _PERIODIC_SEC seconds regardless of interaction.
        """
        log = logging.getLogger("Screen")
        if self.debug:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        else:
            log.addHandler(logging.NullHandler())
            log.propagate = False

        DEBOUNCE = self._DEBOUNCE_SEC
        loop = asyncio.get_running_loop()

        self._debounce_deadline: float | None = None
        _flush_running = False
        _periodic_deadline: float = time.time() + self._PERIODIC_SEC

        def schedule_event(x: float, y: float, typ: str):
            asyncio.run_coroutine_threadsafe(mouse_event(x, y, typ), loop)

        async def flush():
            """Capture before+after screenshots and emit an observation."""
            nonlocal _flush_running
            if _flush_running:
                return
            _flush_running = True
            try:
                if self._pending_event is None:
                    return
                if self._skip():
                    self._pending_event = None
                    return

                ev = self._pending_event
                log.info(f"Debounce fired — capturing {ev['type']}...")

                aft_path = await self._capture_screenshot("after")
                bef_path = ev["before"]

                log.info("Screenshots saved, sending to vision LLM...")
                await self._process_and_emit(bef_path, aft_path)
                self._pending_event = None
            except Exception:
                log.exception("flush() FAILED")
                self._pending_event = None
            finally:
                _flush_running = False

        async def mouse_event(x: float, y: float, typ: str):
            log.info(f"{typ:<6} @({x:7.1f},{y:7.1f})")
            if self._skip():
                return

            if self._pending_event is None:
                bef_path = await self._capture_screenshot("before")
                self._pending_event = {"type": typ, "before": bef_path}
                log.info("Before screenshot captured")

            self._debounce_deadline = time.time() + DEBOUNCE

        # Start the appropriate mouse listener for the current platform
        _stop_linux_listener = None
        if sys.platform.startswith("linux"):
            _stop_linux_listener, _num_mice = _start_linux_mouse_listener(loop, mouse_event)
            log.info(f"Linux evdev listener started ({_num_mice} pointing devices)")
        else:
            listener = mouse.Listener(
                on_move=lambda x, y: schedule_event(x, y, "move"),
                on_click=lambda x, y, btn, prs: schedule_event(x, y, "click") if prs else None,
                on_scroll=lambda x, y, dx, dy: schedule_event(x, y, "scroll"),
            )
            listener.start()

        log.info(f"Screen observer started — guarding {self._guard or '(none)'}")

        while self._running:
            t0 = time.time()

            # Debounce check: fires after _DEBOUNCE_SEC of inactivity following a click/scroll
            if (self._debounce_deadline is not None
                    and time.time() >= self._debounce_deadline):
                self._debounce_deadline = None
                log.info("Debounce deadline reached, calling flush...")
                await flush()

            # Periodic check: fires every _PERIODIC_SEC regardless of interaction
            elif time.time() >= _periodic_deadline:
                _periodic_deadline = time.time() + self._PERIODIC_SEC
                if not _flush_running and not self._skip():
                    log.info("Periodic capture triggered...")
                    try:
                        path = await self._capture_screenshot("periodic")
                        await self._process_and_emit(path, path)
                        log.info("Periodic capture complete")
                    except Exception:
                        log.exception("Periodic capture FAILED")

            await asyncio.sleep(max(0, (1 / self._CAPTURE_FPS) - (time.time() - t0)))

        # Shutdown
        if sys.platform.startswith("linux") and _stop_linux_listener is not None:
            _stop_linux_listener()
        elif not sys.platform.startswith("linux"):
            listener.stop()
