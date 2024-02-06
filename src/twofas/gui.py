import base64
import json
import sys
import types
import typing
import warnings
from pathlib import Path
from typing import Any, Optional
from zipfile import ZipFile

import requests
from configuraptor import asdict
from lib2fas import load_services
from threadful import ThreadWithReturn, thread

# todo: extract to separate gui lib


def has_eel() -> tuple[Optional[types.ModuleType], Optional[ImportError]]:
    try:
        import eel

        return eel, None
    except ImportError as e:
        return None, e


WEB_DIR = Path(__file__).parent / "web"
CACHE_DIR = Path("~/.cache").expanduser() / "2fas"
ICON_DIR = CACHE_DIR / "icons"


def get_screen_width() -> tuple[int, int]:
    from screeninfo import get_monitors

    monitors = get_monitors()
    width = monitors[0].width
    height = monitors[0].height
    return width, height


def center_position(screen_size: tuple[int, int], window_size: tuple[int, int]) -> tuple[int, int]:
    screen_width, screen_height = screen_size
    window_width, window_height = window_size

    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2

    return (x, y)


number = typing.TypeVar("number", int, float)


def minmax(value: number, minimum: Optional[number] = 0, maximum: Optional[number] = None) -> number:
    """
    Returns the value constrained between a minimum and maximum value.

    Parameters:
    - value: The value to be constrained.
    - minimum: The minimum allowed value (defaults to 0).
    - maximum: The maximum allowed value (defaults to None, which means value itself).

    Returns:
    - The value constrained between minimum and maximum.
    """
    if minimum is None:
        # Set minimum to 0 if it's None
        minimum = 0

    # Set maximum to value if it's None
    maximum = maximum if maximum is not None else value

    # Ensure that value is within the specified range
    if value < minimum:
        return minimum
    elif value > maximum:
        return maximum
    else:
        return value


def calc_window_size(
    min_width: int = 0,
    min_height: int = 0,
    max_width: int = 1920,
    max_height: int = 1080,
) -> dict[str, tuple[int, int]]:
    screen_width, screen_height = get_screen_width()

    window_size = (minmax(screen_width // 8, min_width, max_width), minmax(screen_height // 3, min_height, max_height))

    return {"size": window_size, "position": center_position((screen_width, screen_height), window_size)}


def unpack_icons(file: Path) -> None:
    target_directory = "2fas-android-develop/parsers/src/main/assets/"
    extensions = (".png", ".json")

    with ZipFile(str(file), "r") as zip_ref:
        for filepath in zip_ref.namelist():
            if filepath.startswith(target_directory) and filepath.endswith(extensions):
                filename = filepath.removeprefix(target_directory)
                if not filename:
                    # root is empty
                    continue

                cache_path = CACHE_DIR / filename
                cache_path.parent.mkdir(exist_ok=True, parents=True)

                with cache_path.open("wb") as f:
                    if contents := zip_ref.read(filepath):
                        f.write(contents)


def parse_services_json() -> dict[str, list[str]]:
    services_file = CACHE_DIR / "services.json"
    full_str = services_file.read_text()
    obj = json.loads(full_str)
    del full_str

    result: dict[str, list[str]] = {}

    for service in obj:
        for collection in service["icons_collections"]:
            result[collection["id"]] = [_["id"] for _ in collection["icons"]]

    return result


@thread
def load_icons() -> dict[str, list[str]]:
    # threaded
    github_url = "https://github.com/twofas/2fas-android/archive/refs/heads/develop.zip"
    tmpfile = Path("/tmp/2fas-icons.zip")

    if not tmpfile.exists():
        response = requests.get(github_url, timeout=30, stream=True)

        with tmpfile.open("wb") as file:
            for chunk in response.iter_content(chunk_size=256):
                file.write(chunk)

    unpack_icons(tmpfile)
    result = parse_services_json()
    return result


T = typing.TypeVar("T")
threadedfunction: typing.TypeAlias = typing.Callable[[], ThreadWithReturn[T]]


class EelWithJavascript(typing.Protocol):
    # eel:
    expose: typing.Callable[[typing.Callable[..., Any]], None]

    # js:
    python_task_started: typing.Callable[[str], None]
    python_task_completed: typing.Callable[[str], None]
    hello: typing.Callable[[], None]


class GUI:
    icons: dict[str, list[str]]
    tasks: dict[str, tuple[threadedfunction[Any], typing.Callable[[Any], None] | None]]
    js: EelWithJavascript

    _threads: dict[str, ThreadWithReturn[Any]]
    _callbacks: dict[str, typing.Callable[[Any], None] | None]
    _verbose: bool = False
    _log: typing.Callable[..., None]

    def __init__(self, verbose: bool = False) -> None:
        self.icons = {}
        self.tasks = {
            "load_icons": (load_icons, self.icons.update),  # todo: deal with dark/light etc.
        }

        self._threads = {}
        self._callbacks = {}
        if verbose:
            self._verbose = True
            self._log = self._log_verbose
        else:
            self._log = self._noop

    def _noop(self, *_: Any, **__: Any) -> None:
        return

    def _log_verbose(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", sys.stderr)
        print(*args, **kwargs)

    def _start(self) -> None:
        eel, e = has_eel()

        if typing.TYPE_CHECKING:
            import eel

        if e or not eel:
            warnings.warn("Can't use the gui! You may need to run `pip install 2fas[gui]` to fix this.", source=e)
            return

        eel.init(str(WEB_DIR))
        self._log("eel.init", WEB_DIR)
        sizes = calc_window_size(
            min_height=700,
            min_width=400,
        )

        eel.start("main.html", port=0, block=False, **sizes)

        self.js = typing.cast(EelWithJavascript, eel)
        self._auto_expose()
        self._start_tasks()

        self.js.hello()

        while True:
            eel.sleep(1)
            self._check_tasks()

    def _start_tasks(self) -> None:
        for key, (threadfunc, then) in self.tasks.copy().items():
            self._log("start task", key)
            self._threads[key] = threadfunc()
            self._callbacks[key] = then
            del self.tasks[key]
            self.js.python_task_started(key)

        self._log("end of start tasks", self._threads)

    def _check_tasks(self) -> None:
        for key, thrd in self._threads.copy().items():
            self._log("check task", key, thrd)
            if thrd.is_alive():
                # still active
                self._log(f"{key} still working")
                continue

            self._log(f"{key} is done:", end=" ")
            result = thrd.join(1)
            self._log(result)
            del thrd
            del self._threads[key]
            if then := self._callbacks.get(key):
                self._log(f"Running callback for {key}", then)
                then(result)
                del self._callbacks[key]

            self.js.python_task_completed(key)

    def _auto_expose(self) -> None:
        # expose every non-internal function to JS
        method_list = [
            getattr(self, func) for func in dir(self) if not func.startswith("_") and callable(getattr(self, func))
        ]
        for method in method_list:
            self._log("js.expose", method)
            self.js.expose(method)

    # public JS methods:
    def hello(self) -> None:
        print("JS says hello!", file=sys.stderr)

    def get_services(self):
        services = load_services("/home/robin/Nextcloud/2fa/2fas-backup-20240117132052.2fas")
        return [s.as_dict() for s in services]

    def load_image(self, uuid: str) -> str:
        self._log("start load image", uuid)
        for icon_uuid in self.icons.get(uuid, []):
            path = ICON_DIR / f"{icon_uuid}.png"

            if not path.exists():
                continue

            base64_utf8_str = base64.b64encode(path.read_bytes()).decode()

            self._log("end load image", len(base64_utf8_str))
            return f"data:image/png;base64,{base64_utf8_str}"

        # else: nothing found :/
        self._log("end load image", 0)
        return ""


def start_gui(verbose: bool = False) -> None:
    gui = GUI(verbose=verbose)
    gui._start()
