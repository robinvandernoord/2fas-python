import base64
import json
import sys
import types
import typing
import warnings
from pathlib import Path
from zipfile import ZipFile

import requests

try:
    from result import Err, Ok, Result
    from threadful import ThreadWithReturn, thread
except ImportError:
    # when the [gui] extra is not installed
    # an error will be thrown later.
    Ok = typing.Any  # type: ignore
    Err = typing.Any  # type: ignore
    Result = typing.Any  # type: ignore


def has_eel() -> tuple[typing.Optional[types.ModuleType], typing.Optional[ImportError]]:
    try:
        # import gevent.monkey
        # gevent.monkey.patch_all()

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


def calc_window_size() -> dict[str, tuple[int, int]]:
    screen_width, screen_height = get_screen_width()

    window_size = screen_width // 8, screen_height // 3

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
    expose: typing.Callable[[typing.Callable[..., typing.Any]], None]

    # js:
    python_task_started: typing.Callable[[str], None]
    python_task_completed: typing.Callable[[str], None]
    hello: typing.Callable[[], None]


class GUI:
    icons: dict[str, list[str]]
    tasks: dict[str, tuple[threadedfunction[typing.Any], typing.Callable[[typing.Any], None] | None]]
    js: EelWithJavascript

    _threads: dict[str, ThreadWithReturn[typing.Any]]
    _callbacks: dict[str, typing.Callable[[typing.Any], None] | None]

    def __init__(self) -> None:
        self.icons = {}
        self.tasks = {
            "load_icons": (load_icons, self.icons.update),  # todo: deal with dark/light etc.
        }

        self._threads = {}
        self._callbacks = {}

    def _start(self) -> None:
        eel, e = has_eel()

        if typing.TYPE_CHECKING:
            import eel

        if e or not eel:
            warnings.warn("Can't use the gui! You may need to run `pip install 2fas[gui]` to fix this.", source=e)
            return

        eel.init(str(WEB_DIR))
        eel.start("main.html", port=0, block=False, **calc_window_size())

        self.js = typing.cast(EelWithJavascript, eel)
        self._auto_expose()
        self._start_tasks()

        self.js.hello()

        while True:
            eel.sleep(1)
            self._check_tasks()

    def _start_tasks(self) -> None:
        for key, (threadfunc, then) in self.tasks.copy().items():
            self._threads[key] = threadfunc()
            self._callbacks[key] = then
            del self.tasks[key]
            self.js.python_task_started(key)

    def _check_tasks(self) -> None:
        for key, thread in self._threads.copy().items():
            if thread.is_alive():
                # still active
                continue
            thread.join(1)
            result = thread.result().unwrap()
            del thread
            del self._threads[key]
            if then := self._callbacks.get(key):
                then(result)
                del self._callbacks[key]
                self.js.python_task_completed(key)

    def _auto_expose(self) -> None:
        # expose every non-internal function to JS
        method_list = [
            getattr(self, func) for func in dir(self) if not func.startswith("_") and callable(getattr(self, func))
        ]
        for method in method_list:
            self.js.expose(method)

    # public JS methods:
    def hello(self) -> None:
        print("JS says hello!", file=sys.stderr)

    def load_image(self, uuid: str) -> str:
        for icon_uuid in self.icons.get(uuid, []):
            path = ICON_DIR / f"{icon_uuid}.png"

            if not path.exists():
                continue

            base64_utf8_str = base64.b64encode(path.read_bytes()).decode()

            return f"data:image/png;base64,{base64_utf8_str}"

        # else: nothing found :/
        return ""


def start_gui() -> None:
    gui = GUI()
    gui._start()
