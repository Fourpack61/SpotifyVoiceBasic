import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import winsound
from pathlib import Path


def write_build_spec(destination):
    source = str(Path(__file__).resolve())
    deps = os.environ["SPOTIFY_BUILD_DEPS"]
    model_en = os.environ["SPOTIFY_MODEL_EN"]
    model_ru = os.environ["SPOTIFY_MODEL_RU"]
    spec = f'''# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    [{source!r}],
    pathex=[{deps!r}],
    binaries=collect_dynamic_libs("vosk"),
    datas=[({model_en!r}, "model-en"), ({model_ru!r}, "model-ru")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpotifyVoiceBasic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
'''
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(spec, encoding="utf-8")


if len(sys.argv) == 3 and sys.argv[1] == "--write-spec":
    write_build_spec(sys.argv[2])
    raise SystemExit(0)


if len(sys.argv) == 3 and sys.argv[1] == "--package-spec":
    from PyInstaller.__main__ import run as run_pyinstaller

    run_pyinstaller([
        "--noconfirm",
        "--clean",
        "--distpath", os.environ["SPOTIFY_BUILD_DIST"],
        "--workpath", os.environ["SPOTIFY_BUILD_WORK"],
        sys.argv[2],
    ])
    raise SystemExit(0)


import sounddevice as sd
import pystray
from PIL import Image, ImageDraw
from vosk import KaldiRecognizer, Model, SetLogLevel

SetLogLevel(-1)
AUDIO = queue.Queue()
EN = ["spotify", "spotify next", "spotify stop", "spotify close the app", "spotify pause", "spotify play", "spotify last", "spotify previous", "[unk]"]
RU = ["музыка", "музыка следующий", "музыка дальше", "музыка закрой приложение", "музыка стоп", "музыка пауза", "музыка играй", "музыка продолжи", "музыка предыдущий", "музыка прошлый", "музыка назад", "[unk]"]

VOLUME_COMMANDS = {}
for number, english, russian in (
    (5, "five", "пять"),
    (10, "ten", "десять"),
    (20, "twenty", "двадцать"),
    (50, "fifty", "пятьдесят"),
):
    VOLUME_COMMANDS[f"spotify volume up {english}"] = number
    VOLUME_COMMANDS[f"spotify volume down {english}"] = -number
    VOLUME_COMMANDS[f"spotify louder {english}"] = number
    VOLUME_COMMANDS[f"spotify quieter {english}"] = -number
    VOLUME_COMMANDS[f"музыка громче на {russian}"] = number
    VOLUME_COMMANDS[f"музыка тише на {russian}"] = -number
    VOLUME_COMMANDS[f"музыка увеличь громкость на {russian}"] = number
    VOLUME_COMMANDS[f"музыка уменьши громкость на {russian}"] = -number

MUTE_COMMANDS = {
    "spotify mute",
    "spotify no sound",
    "музыка выключи звук",
    "музыка без звука",
    "музыка громкость ноль",
}
EN = EN[:-1] + [command for command in VOLUME_COMMANDS if command.startswith("spotify ")] + sorted(command for command in MUTE_COMMANDS if command.startswith("spotify ")) + ["[unk]"]
RU = RU[:-1] + [command for command in VOLUME_COMMANDS if command.startswith("музыка ")] + sorted(command for command in MUTE_COMMANDS if command.startswith("музыка ")) + ["[unk]"]

ERROR_ALREADY_EXISTS = 183
INSTANCE_MUTEX = None
LOG_PATH = None
LISTENING_ENABLED = threading.Event()
SHUTDOWN = threading.Event()
WORKER_READY = threading.Event()
TRAY_ICON = None
WORKER_ERROR = None


def log(*args):
    if LOG_PATH is None:
        return
    try:
        with LOG_PATH.open("a", encoding="utf-8") as file:
            print(time.strftime("[%Y-%m-%d %H:%M:%S]"), *args, file=file)
    except OSError:
        pass


def start_new_log():
    global LOG_PATH
    folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    LOG_PATH = folder / "spotify_voice.log"
    LOG_PATH.write_text("", encoding="utf-8")
    log("Spotify Voice starting")


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def press(code):
    ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(code, 0, 2, 0)


def change_system_volume(points):
    # A Windows multimedia-volume key changes the master level by roughly two
    # percentage points. Odd values are rounded to the nearest available step.
    key = 0xAF if points > 0 else 0xAE
    presses = max(1, (abs(points) + 1) // 2)
    for _ in range(presses):
        press(key)
        time.sleep(0.02)


def toggle_system_mute():
    press(0xAD)


def close_spotify():
    subprocess.run(
        [
            "taskkill",
            "/F",
            "/IM",
            "Spotify.exe",
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def execute(command):
    if command in VOLUME_COMMANDS:
        change_system_volume(VOLUME_COMMANDS[command])
    elif command in MUTE_COMMANDS:
        toggle_system_mute()
    elif command in {"spotify", "музыка"}:
        os.startfile("spotify:")
    elif command in {"spotify close the app", "музыка закрой приложение"}:
        close_spotify()
    elif command in {"spotify next", "музыка следующий", "музыка дальше"}:
        press(0xB0)
    elif command in {"spotify last", "spotify previous", "музыка предыдущий", "музыка прошлый", "музыка назад"}:
        press(0xB1)
    elif command in {"spotify stop", "музыка стоп"}:
        press(0xB2)
    elif command in {"spotify pause", "spotify play", "музыка пауза", "музыка играй", "музыка продолжи"}:
        press(0xB3)
    else:
        return False
    log("Executed:", command)
    return True


def callback(indata, frames, timing, status):
    if status:
        log("Audio status:", status)
    if LISTENING_ENABLED.is_set() and not SHUTDOWN.is_set():
        AUDIO.put(bytes(indata))


def clear_audio_queue():
    while not AUDIO.empty():
        try:
            AUDIO.get_nowait()
        except queue.Empty:
            break


def tray_image(enabled):
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = (30, 215, 96, 255) if enabled else (125, 125, 125, 255)
    draw.ellipse((4, 4, 60, 60), fill=color)
    draw.text((22, 14), "S", fill=(255, 255, 255, 255), stroke_width=1)
    return image


def refresh_tray():
    if TRAY_ICON is None:
        return
    enabled = LISTENING_ENABLED.is_set()
    TRAY_ICON.icon = tray_image(enabled)
    TRAY_ICON.title = "Spotify Voice — включено" if enabled else "Spotify Voice — остановлено"
    TRAY_ICON.update_menu()


def enable_listening(icon=None, item=None):
    if LISTENING_ENABLED.is_set():
        return
    clear_audio_queue()
    LISTENING_ENABLED.set()
    log("Voice listening enabled from tray")
    refresh_tray()
    winsound.MessageBeep(winsound.MB_OK)


def stop_listening(icon=None, item=None):
    if not LISTENING_ENABLED.is_set():
        return
    LISTENING_ENABLED.clear()
    clear_audio_queue()
    log("Voice listening stopped from tray")
    refresh_tray()
    winsound.MessageBeep(winsound.MB_ICONASTERISK)


def exit_application(icon=None, item=None):
    log("Exit requested from tray")
    LISTENING_ENABLED.clear()
    SHUTDOWN.set()
    clear_audio_queue()
    if icon is not None:
        icon.stop()


def input_devices():
    devices = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0)) > 0:
            devices.append({"index": index, "name": str(device.get("name", f"Microphone {index}"))})
    return devices


def choose_microphone():
    devices = input_devices()
    if not devices:
        raise RuntimeError("No microphone was found in Windows.")

    try:
        default_index = int(sd.default.device[0])
    except (TypeError, ValueError):
        default_index = devices[0]["index"]
    selected_position = next(
        (position for position, item in enumerate(devices) if item["index"] == default_index),
        0,
    )

    env = os.environ.copy()
    env["SPOTIFY_MICROPHONES"] = json.dumps(devices, ensure_ascii=False)
    env["SPOTIFY_DEFAULT_MICROPHONE"] = str(selected_position)
    script = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$items = @($env:SPOTIFY_MICROPHONES | ConvertFrom-Json)
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Spotify Voice - microphone'
$form.Size = New-Object System.Drawing.Size(520,175)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Choose a microphone (the Windows default is selected automatically):'
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(15,15)
$combo = New-Object System.Windows.Forms.ComboBox
$combo.DropDownStyle = 'DropDownList'
$combo.Location = New-Object System.Drawing.Point(15,45)
$combo.Size = New-Object System.Drawing.Size(475,25)
foreach ($item in $items) { [void]$combo.Items.Add([string]$item.name) }
$combo.SelectedIndex = [Math]::Max(0, [int]$env:SPOTIFY_DEFAULT_MICROPHONE)
$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'Use microphone'
$ok.Location = New-Object System.Drawing.Point(350,85)
$ok.Size = New-Object System.Drawing.Size(140,30)
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $ok
$form.Controls.AddRange(@($label,$combo,$ok))
if ($form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $combo.SelectedIndex } else { $env:SPOTIFY_DEFAULT_MICROPHONE }
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        selected_position = int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    selected_position = min(max(selected_position, 0), len(devices) - 1)
    selected_index = devices[selected_position]["index"]
    sample_rate = int(float(sd.query_devices(selected_index)["default_samplerate"]))
    return selected_index, sample_rate


def voice_worker(microphone, sample_rate):
    global WORKER_ERROR
    try:
        log("Microphone:", sd.query_devices(microphone)["name"], "index:", microphone, "sample rate:", sample_rate)
        en = KaldiRecognizer(Model(str(resource("model-en"))), sample_rate, json.dumps(EN))
        ru = KaldiRecognizer(Model(str(resource("model-ru"))), sample_rate, json.dumps(RU, ensure_ascii=False))
        last_action_time = 0
        log("Spotify Voice Basic is running.")
        WORKER_READY.set()
        while not SHUTDOWN.is_set():
            if not LISTENING_ENABLED.wait(0.25):
                continue
            clear_audio_queue()
            en.Reset()
            ru.Reset()
            log("Microphone stream opened")
            with sd.RawInputStream(device=microphone, samplerate=sample_rate, blocksize=4000, dtype="int16", channels=1, callback=callback):
                while LISTENING_ENABLED.is_set() and not SHUTDOWN.is_set():
                    try:
                        audio = AUDIO.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    candidates = []
                    if en.AcceptWaveform(audio):
                        candidates.append((json.loads(en.Result()).get("text", "").strip(), True))
                    else:
                        candidates.append((json.loads(en.PartialResult()).get("partial", "").strip(), False))
                    if ru.AcceptWaveform(audio):
                        candidates.append((json.loads(ru.Result()).get("text", "").strip(), True))
                    else:
                        candidates.append((json.loads(ru.PartialResult()).get("partial", "").strip(), False))
                    for command, is_final in candidates:
                        if not command or command == "[unk]":
                            continue
                        if is_final:
                            log("Recognized:", command)
                        if command in {"spotify", "музыка"} and not is_final:
                            continue
                        now = time.time()
                        if now - last_action_time < 2.0:
                            continue
                        if execute(command):
                            last_action_time = now
                            en.Reset()
                            ru.Reset()
                            clear_audio_queue()
                            break
            clear_audio_queue()
            log("Microphone stream closed")
    except Exception as error:
        WORKER_ERROR = error
        WORKER_READY.set()
        log("Voice worker error:", repr(error))
        SHUTDOWN.set()
        if TRAY_ICON is not None:
            TRAY_ICON.stop()


def main():
    global INSTANCE_MUTEX, TRAY_ICON
    start_new_log()
    INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SpotifyVoiceBasic.SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        log("Another instance is already running")
        return
    microphone, sample_rate = choose_microphone()
    LISTENING_ENABLED.set()
    worker = threading.Thread(target=voice_worker, args=(microphone, sample_rate), name="SpotifyVoiceListener", daemon=True)
    worker.start()
    if not WORKER_READY.wait(timeout=90):
        raise RuntimeError("Voice recognizer initialization timed out.")
    if WORKER_ERROR is not None:
        raise WORKER_ERROR
    menu = pystray.Menu(
        pystray.MenuItem("Включить", enable_listening, enabled=lambda item: not LISTENING_ENABLED.is_set()),
        pystray.MenuItem("Остановить", stop_listening, enabled=lambda item: LISTENING_ENABLED.is_set()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выключить", exit_application),
    )
    TRAY_ICON = pystray.Icon("SpotifyVoiceBasic", tray_image(True), "Spotify Voice — включено", menu)
    winsound.MessageBeep(winsound.MB_OK)
    TRAY_ICON.run()
    SHUTDOWN.set()
    LISTENING_ENABLED.clear()
    worker.join(timeout=3)
    if WORKER_ERROR is not None:
        raise WORKER_ERROR


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped from keyboard")
        pass
    except Exception as error:
        log("Fatal error:", repr(error))
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Spotify Voice could not start:\n\n{error}",
            "Spotify Voice",
            0x10,
        )
