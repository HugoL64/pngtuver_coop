try:
    import pyaudiowpatch as pyaudio
except ImportError:
    import pyaudio
import numpy as np
import threading
import time
import sys
import os
import psutil
import json
import shutil
import subprocess
from types import SimpleNamespace
from typing import Optional, List, Dict


class PipeWireAudioCapture:
    """Implementación de captura aislada de audio por proceso para Linux usando PipeWire."""
    IGNORE_BINARIES = {
        'pw-dump', 'pw-record', 'pw-link', 'pw-cli', 'wireplumber', 'pipewire',
        'mutter', 'gnome-shell', 'gsd-media-keys', 'xdg-desktop-portal', 'cava',
        'python', 'python3', 'python3.14', 'antigravity', 'antigravity-ide'
    }

    @classmethod
    def is_supported(cls):
        return bool(shutil.which('pw-record') and shutil.which('pw-dump'))

    @classmethod
    def enumerate_audio_processes(cls):
        try:
            dump = json.loads(subprocess.check_output(['pw-dump'], stderr=subprocess.DEVNULL))
        except Exception:
            return []

        clients = {}
        nodes = []
        for obj in dump:
            t = obj.get('type')
            props = obj.get('info', {}).get('props', {})
            if t == 'PipeWire:Interface:Client':
                cid = obj.get('id')
                clients[cid] = {
                    'name': props.get('application.name') or props.get('node.name') or '',
                    'binary': props.get('application.process.binary') or '',
                    'pid': props.get('application.process.id')
                }
            elif t == 'PipeWire:Interface:Node' and props.get('media.class') == 'Stream/Output/Audio':
                nodes.append({
                    'serial': props.get('object.serial', obj.get('id')),
                    'client_id': props.get('client.id'),
                    'app_name': props.get('application.name', '')
                })

        procs = []
        seen_pids = set()
        seen_names = set()

        # 1. Aplicaciones con streams de audio activos en este instante
        for n in nodes:
            c = clients.get(n['client_id'], {})
            raw_name = n.get('app_name') or c.get('name') or c.get('binary')
            if not raw_name:
                continue
            name = raw_name.capitalize()
            low_name = name.lower()
            if any(ig in low_name for ig in cls.IGNORE_BINARIES):
                continue

            pid = c.get('pid')
            if pid:
                try:
                    pid = int(pid)
                    if pid == os.getpid():
                        continue
                    if pid not in seen_pids:
                        seen_pids.add(pid)
                        seen_names.add(low_name)
                        procs.append(SimpleNamespace(pid=pid, name=name, window_title='En reproducción'))
                except Exception:
                    pass

        # 2. Clientes de audio conectados a PipeWire (ej: Brave, Discord, Spotify en reposo)
        for c in clients.values():
            raw_name = c.get('binary') or c.get('name')
            if not raw_name:
                continue
            name = raw_name.capitalize()
            low_name = name.lower()
            if low_name in seen_names or any(ig in low_name for ig in cls.IGNORE_BINARIES):
                continue
            if any(ig in low_name for ig in ['input', 'hardware_mute', 'volume control']):
                continue

            pid = c.get('pid')
            if pid:
                try:
                    pid = int(pid)
                    if pid == os.getpid():
                        continue
                    if pid not in seen_pids:
                        seen_pids.add(pid)
                        seen_names.add(low_name)
                        procs.append(SimpleNamespace(pid=pid, name=name, window_title=''))
                except Exception:
                    pass

        return procs

    def __init__(self, pid=None, level_callback=None):
        self.pid = int(pid) if pid is not None else None
        self.level_callback = level_callback or (lambda db: None)
        self.running = False
        self.thread = None
        self.proc = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

    def _find_target_serial(self):
        try:
            dump = json.loads(subprocess.check_output(['pw-dump'], stderr=subprocess.DEVNULL))
        except Exception:
            return None

        target_clients = set()
        for obj in dump:
            if obj.get('type') == 'PipeWire:Interface:Client':
                props = obj.get('info', {}).get('props', {})
                cid = obj.get('id')
                cpid = props.get('application.process.id')
                if self.pid is not None and cpid is not None:
                    try:
                        if int(cpid) == self.pid:
                            target_clients.add(cid)
                    except Exception:
                        pass

        for obj in dump:
            if obj.get('type') == 'PipeWire:Interface:Node':
                props = obj.get('info', {}).get('props', {})
                if props.get('media.class') == 'Stream/Output/Audio':
                    if props.get('client.id') in target_clients:
                        return props.get('object.serial', obj.get('id'))

        return None

    def _run(self):
        while self.running:
            serial = self._find_target_serial()
            if not serial:
                self.level_callback(-60.0)
                time.sleep(0.5)
                continue

            cmd = [
                'pw-record',
                '--target', str(serial),
                '--raw',
                '--rate', '48000',
                '--channels', '2',
                '--format', 's16',
                '-'
            ]
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                while self.running and self.proc.poll() is None:
                    data = self.proc.stdout.read(2048)
                    if not data:
                        break
                    arr = np.frombuffer(data, dtype=np.int16)
                    if len(arr) > 0:
                        rms = float(np.sqrt(np.mean(arr.astype(np.float32)**2)))
                        pct = min(100.0, max(0.0, (rms / 4000.0) * 100.0))
                        db = (pct * 0.6) - 60.0
                        self.level_callback(db)
            except Exception:
                pass
            finally:
                if self.proc:
                    try:
                        self.proc.terminate()
                    except Exception:
                        pass
                    self.proc = None

            if self.running:
                time.sleep(0.3)


if sys.platform.startswith("win"):
    try:
        from process_audio_capture import ProcessAudioCapture
        PROCESS_CAPTURE_AVAILABLE = ProcessAudioCapture.is_supported()
    except Exception as e:
        print(f"[AudioEngine] process_audio_capture no disponible: {e}")
        PROCESS_CAPTURE_AVAILABLE = False
else:
    ProcessAudioCapture = PipeWireAudioCapture
    PROCESS_CAPTURE_AVAILABLE = PipeWireAudioCapture.is_supported()


class AudioEngine:
    def __init__(self, on_mic_level=None, on_discord_level=None, on_mic_state=None, on_discord_state=None, on_mic_scream=None, on_discord_scream=None):
        self.p = pyaudio.PyAudio()
        self.on_mic_level = on_mic_level
        self.on_discord_level = on_discord_level
        self.on_mic_state = on_mic_state
        self.on_discord_state = on_discord_state
        self.on_mic_scream = on_mic_scream
        self.on_discord_scream = on_discord_scream

        self.mic_stream = None
        self.discord_stream = None
        self.process_captures: List[ProcessAudioCapture] = []
        self.process_monitor_active = False
        self.mic_vowel_hint = None
        self.discord_vowel_hint = None
        self._mic_rate = 44100
        self._mic_channels = 1
        self._discord_rate = 44100
        self._discord_channels = 2

        self.mic_threshold = 20.0
        self.discord_threshold = 25.0
        self.mic_scream_threshold = 50.0
        self.discord_scream_threshold = 50.0

        # Histéresis: ratio de cierre (70% del umbral de apertura)
        self.hysteresis_ratio = 0.70

        # Estados y tiempos de tolerancia (hangover) para evitar parpadeo
        self.mic_talking = False
        self.discord_talking = False
        self.mic_last_speak_time = 0.0
        self.discord_last_speak_time = 0.0
        self.hangover_time = 0.18  # 180ms delay antes de cerrar la boca

        # Estados de grito sostenido
        self.mic_screaming = False
        self.discord_screaming = False
        self.mic_scream_start_time = 0.0
        self.mic_last_loud_time = 0.0
        self.mic_scream_end_time = 0.0

        self.discord_scream_start_time = 0.0
        self.discord_last_loud_time = 0.0
        self.discord_scream_end_time = 0.0

        # Mute manual por hotkey
        self.mic_muted = False
        self.discord_muted = False
        self.mic_last_callback_time = 0.0
        self.current_mic_index = None

        self.running = False
        self.monitor_thread = None
        self._lock = threading.Lock()

        # Guardar niveles actuales de procesos
        self._process_levels: Dict[int, float] = {}

    def get_input_devices(self):
        """Devuelve lista de micrófonos y dispositivos de entrada normales."""
        devices = []
        default_index = -1
        try:
            default_info = self.p.get_default_input_device_info()
            default_index = default_info['index']
        except Exception:
            pass

        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            name = dev['name']
            name_lower = name.lower()
            is_loopback = (
                dev.get('isLoopbackDevice', False)
                or (not sys.platform.startswith("win") and ('.monitor' in name_lower or 'monitor of' in name_lower))
            )
            if dev.get('maxInputChannels', 0) > 0 and not is_loopback:
                is_default = (i == default_index)
                devices.append({
                    'index': i,
                    'name': f"{name}{' (Predeterminado)' if is_default else ''}",
                    'raw_name': name,
                    'channels': dev['maxInputChannels'],
                    'rate': int(dev['defaultSampleRate']),
                    'is_default': is_default
                })
        return devices

    def get_discord_sources(self):
        """Devuelve todas las fuentes posibles para Discord."""
        sources = []

        if PROCESS_CAPTURE_AVAILABLE:
            sources.append({
                'type': 'app_discord',
                'id': 'app:discord',
                'name': '🎯 Discord (SOLO tus amigos - Ignora juego y música) [Recomendado]',
                'raw_name': 'app:discord'
            })

            try:
                audio_procs = ProcessAudioCapture.enumerate_audio_processes()
                for ap in audio_procs:
                    if 'discord' not in ap.name.lower():
                        title = f" ({ap.window_title})" if ap.window_title else ""
                        sources.append({
                            'type': 'app_pid',
                            'id': f"pid:{ap.pid}",
                            'pid': ap.pid,
                            'name': f"🎯 App: {ap.name}{title}",
                            'raw_name': f"pid:{ap.name}"
                        })
            except Exception as e:
                print(f"[AudioEngine] Error enumerando procesos con audio: {e}")

        # En Linux/PipeWire, detectar cuál es el sink/monitor predeterminado del sistema
        pipewire_default_monitor = None
        if not sys.platform.startswith("win"):
            try:
                import subprocess, re
                wp_out = subprocess.check_output(['wpctl', 'status'], text=True, stderr=subprocess.DEVNULL)
                m_def = re.search(r'Audio/Sink\s+([\w\.\-]+)', wp_out)
                if m_def:
                    pipewire_default_monitor = m_def.group(1).lower()
            except Exception:
                pass

        default_out_name = ""
        try:
            default_out = self.p.get_default_output_device_info()
            default_out_name = (default_out.get('name') or "").lower()
        except Exception:
            pass

        loopback_sources = []
        input_sources = []

        for i in range(self.p.get_device_count()):
            dev = self.p.get_device_info_by_index(i)
            name = dev['name']
            name_lower = name.lower()

            is_loopback = (
                dev.get('isLoopbackDevice', False)
                or (not sys.platform.startswith("win") and ('.monitor' in name_lower or 'monitor of' in name_lower))
            )

            if is_loopback:
                is_default = False
                if pipewire_default_monitor and pipewire_default_monitor in name_lower:
                    is_default = True
                elif default_out_name and default_out_name in name_lower:
                    is_default = True

                if not sys.platform.startswith("win"):
                    clean_name = name.replace('.monitor', '').replace('alsa_output.', '')
                    try:
                        import re
                        clean_name = re.sub(r'pci-[0-9a-fA-F:\.]+\.', '', clean_name)
                    except Exception:
                        pass
                    display_name = f"🔊 Salida de PC / Discord ({clean_name})"
                else:
                    display_name = f"🔊 Todo el audio: {name}"

                if is_default:
                    display_name += " [Altavoces Actuales / Recomendado]"

                loopback_sources.append({
                    'type': 'device_loopback',
                    'id': f"dev:{i}",
                    'index': i,
                    'name': display_name,
                    'raw_name': name,
                    'is_default': is_default
                })
            elif dev.get('maxInputChannels', 0) > 0:
                input_sources.append({
                    'type': 'device_input',
                    'id': f"dev:{i}",
                    'index': i,
                    'name': f"🎤 Dispositivo de Entrada: {name}",
                    'raw_name': name,
                    'is_default': False
                })

        # Mostrar las salidas de audio y monitor de primero (con la predeterminada al frente)
        loopback_sources.sort(key=lambda s: not s.get('is_default', False))
        sources.extend(loopback_sources)
        sources.extend(input_sources)

        return sources

    def _stop_mic_stream(self):
        if self.mic_stream:
            try:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
            except Exception:
                pass
            self.mic_stream = None

    def _stop_discord_stream(self):
        self.process_monitor_active = False
        self.mic_vowel_hint = None
        self.discord_vowel_hint = None
        self._mic_rate = 44100
        self._mic_channels = 1
        self._discord_rate = 44100
        self._discord_channels = 2
        if self.discord_stream:
            try:
                self.discord_stream.stop_stream()
                self.discord_stream.close()
            except Exception:
                pass
            self.discord_stream = None

        with self._lock:
            caps_to_stop = list(self.process_captures)
            self.process_captures.clear()
            self._process_levels.clear()

        for cap in caps_to_stop:
            try:
                cap.stop()
            except Exception:
                pass

    def _open_mic_stream(self, mic_device_index):
        self._stop_mic_stream()
        self.current_mic_index = mic_device_index
        if mic_device_index is not None:
            try:
                mic_info = self.p.get_device_info_by_index(mic_device_index)
                channels = min(2, max(1, mic_info['maxInputChannels']))
                rate = int(mic_info['defaultSampleRate'])
                self._mic_channels = channels
                self._mic_rate = rate

                self.mic_stream = self.p.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=mic_device_index,
                    frames_per_buffer=1024,
                    stream_callback=self._mic_callback
                )
                self.mic_last_callback_time = time.time()
                self.mic_stream.start_stream()
            except Exception as e:
                print(f"[AudioEngine] Error al abrir micrófono (index {mic_device_index}): {e}")

    def start(self, mic_device_index, discord_source_info, mic_threshold=20.0, discord_threshold=25.0, mic_scream_threshold=50.0, discord_scream_threshold=50.0, single_player=False):
        self.mic_threshold = float(mic_threshold)
        self.discord_threshold = float(discord_threshold)
        self.mic_scream_threshold = float(mic_scream_threshold)
        self.discord_scream_threshold = float(discord_scream_threshold)

        mic_inactive = False
        if self.mic_stream is not None:
            try:
                mic_inactive = not self.mic_stream.is_active()
            except Exception:
                mic_inactive = True
        mic_changed = (mic_device_index != getattr(self, "current_mic_index", None) or self.mic_stream is None or mic_inactive)
        source_changed = (discord_source_info != getattr(self, "current_discord_source_info", None))
        has_active_discord = (self.discord_stream is not None) or bool(self.process_captures) or self.process_monitor_active

        self.single_player = single_player
        self.running = True

        if self.single_player:
            self.discord_talking = False
            self.discord_screaming = False

        # Iniciar/cambiar micrófono solo si cambió o se detuvo
        if mic_changed:
            self._open_mic_stream(mic_device_index)

        # Iniciar/cambiar Discord solo si cambió la fuente o si se activa Co-op por primera vez
        # (Evita destruir y recrear sesiones COM/WASAPI repetidamente al alternar 1P <-> 2P)
        if not self.single_player and discord_source_info:
            if source_changed or not has_active_discord:
                self._stop_discord_stream()
                self.current_discord_source_info = discord_source_info
                src_type = discord_source_info.get('type')
                if src_type == 'app_discord':
                    self._start_discord_process_capture()
                elif src_type == 'app_pid':
                    pid = discord_source_info.get('pid')
                    if pid:
                        self._start_single_process_capture(pid)
                elif src_type in ('device_loopback', 'device_input'):
                    dev_index = discord_source_info.get('index')
                    if dev_index is not None:
                        self._start_device_discord_stream(dev_index)

        # Monitor loop solo si no está corriendo
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

    def _start_discord_process_capture(self):
        self.process_monitor_active = True
        self._refresh_discord_pids()
        if not hasattr(self, "_watchdog_thread") or self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._watchdog_thread = threading.Thread(target=self._discord_pids_watchdog, daemon=True)
            self._watchdog_thread.start()

    def _refresh_discord_pids(self):
        if not self.process_monitor_active:
            return
        discord_pids = []
        try:
            for p in psutil.process_iter(['pid', 'name']):
                name = p.info.get('name') or ''
                if 'discord' in name.lower():
                    discord_pids.append(p.info['pid'])
        except Exception:
            pass

        with self._lock:
            active_pids = set(self._process_levels.keys())

        new_caps = []
        for pid in discord_pids:
            if pid not in active_pids and self.process_monitor_active:
                try:
                    cap = ProcessAudioCapture(pid=pid, level_callback=lambda db, p=pid: self._process_level_callback(p, db))
                    cap.start()
                    new_caps.append((pid, cap))
                except Exception:
                    pass

        if new_caps:
            with self._lock:
                for pid, cap in new_caps:
                    self.process_captures.append(cap)
                    self._process_levels[pid] = 0.0

    def _discord_pids_watchdog(self):
        while self.running and self.process_monitor_active:
            time.sleep(3.0)
            if self.running and self.process_monitor_active and not getattr(self, "single_player", False):
                self._refresh_discord_pids()

    def _start_single_process_capture(self, pid):
        try:
            cap = ProcessAudioCapture(pid=pid, level_callback=lambda db, p=pid: self._process_level_callback(p, db))
            cap.start()
            with self._lock:
                self.process_captures.append(cap)
                self._process_levels[pid] = 0.0
        except Exception as e:
            print(f"[AudioEngine] Error capturando PID {pid}: {e}")

    def _process_level_callback(self, pid, db):
        if getattr(self, "single_player", False) or self.discord_muted or not self.running:
            self.discord_vowel_hint = None
            if self.on_discord_level:
                self.on_discord_level(0.0)
            return

        clamped_db = max(-60.0, min(0.0, float(db)))
        pct = ((clamped_db + 60.0) / 60.0) * 100.0

        with self._lock:
            self._process_levels[pid] = pct
            max_level = max(self._process_levels.values()) if self._process_levels else 0.0

        now = time.time()
        if self.on_discord_level:
            self.on_discord_level(max_level)

        # Histéresis: umbral de apertura vs cierre
        open_thresh = self.discord_threshold
        close_thresh = self.discord_threshold * self.hysteresis_ratio

        if not self.discord_talking:
            if max_level >= open_thresh:
                self.discord_talking = True
                self.discord_last_speak_time = now
                if self.on_discord_state:
                    self.on_discord_state(True)
        else:
            if max_level >= close_thresh:
                self.discord_last_speak_time = now

        self._handle_scream_level("discord", max_level, now)

    def _start_device_discord_stream(self, dev_index):
        try:
            dev_info = self.p.get_device_info_by_index(dev_index)
            channels = min(2, max(1, dev_info['maxInputChannels']))
            rate = int(dev_info['defaultSampleRate'])
            self._discord_channels = channels
            self._discord_rate = rate

            self.discord_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=dev_index,
                frames_per_buffer=1024,
                stream_callback=self._discord_device_callback
            )
            self.discord_stream.start_stream()
        except Exception as e:
            print(f"[AudioEngine] Error abriendo dispositivo de audio Discord (index {dev_index}): {e}")

    def _calc_level(self, in_data):
        if not in_data:
            return 0.0
        try:
            arr = np.frombuffer(in_data, dtype=np.int16)
            if len(arr) == 0:
                return 0.0
            rms = np.sqrt(np.mean(arr.astype(np.float32)**2))
            normalized = (rms / 4000.0) * 100.0
            return float(min(100.0, max(0.0, normalized)))
        except Exception:
            return 0.0

    @staticmethod
    def _estimate_vowel_from_pcm(in_data, sample_rate, channels):
        """Estima una vocal (vowel_a/e/i/o/u) mediante FFT ligera por bandas formánticas."""
        if not in_data:
            return None
        try:
            arr = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
            if channels > 1 and len(arr) >= channels:
                arr = arr[: (len(arr) // channels) * channels].reshape(-1, channels).mean(axis=1)
            n = len(arr)
            if n < 128:
                return None
            window = np.hanning(n).astype(np.float32)
            spec = np.abs(np.fft.rfft(arr * window))
            freqs = np.fft.rfftfreq(n, d=1.0 / max(8000.0, float(sample_rate or 44100)))

            very_low = float(np.sum(spec[(freqs >= 120) & (freqs < 350)]))
            low = float(np.sum(spec[(freqs >= 200) & (freqs < 650)]))
            mid = float(np.sum(spec[(freqs >= 650) & (freqs < 1550)]))
            high = float(np.sum(spec[(freqs >= 1600) & (freqs <= 3800)]))

            total = low + mid + high
            if total <= 1e-3:
                return None

            if (high / (mid + 1e-6)) > 0.72:
                return "vowel_e" if (low / (high + 1e-6)) > 0.65 else "vowel_i"
            if mid >= low * 0.85:
                return "vowel_a"
            if (very_low / (low + 1e-6)) > 0.58:
                return "vowel_u"
            return "vowel_o"
        except Exception:
            return None

    def _mic_callback(self, in_data, frame_count, time_info, status):
        now = time.time()
        self.mic_last_callback_time = now
        if self.mic_muted:
            self.mic_vowel_hint = None
            if self.mic_talking:
                self.mic_talking = False
                if self.on_mic_state:
                    self.on_mic_state(False)
            if self.mic_screaming:
                self.mic_screaming = False
                if self.on_mic_scream:
                    self.on_mic_scream(False)
            if self.on_mic_level:
                self.on_mic_level(0.0)
            return (None, pyaudio.paContinue)

        level = self._calc_level(in_data)

        if self.on_mic_level:
            self.on_mic_level(level)

        open_thresh = self.mic_threshold
        close_thresh = self.mic_threshold * self.hysteresis_ratio

        if not self.mic_talking:
            if level >= open_thresh:
                self.mic_talking = True
                self.mic_last_speak_time = now
                if self.on_mic_state:
                    self.on_mic_state(True)
        else:
            if level >= close_thresh:
                self.mic_last_speak_time = now

        self._handle_scream_level("mic", level, now)
        if level >= close_thresh:
            self.mic_vowel_hint = self._estimate_vowel_from_pcm(in_data, self._mic_rate, self._mic_channels)
        else:
            self.mic_vowel_hint = None

        return (None, pyaudio.paContinue)

    def _discord_device_callback(self, in_data, frame_count, time_info, status):
        if getattr(self, "single_player", False) or self.discord_muted or not self.running:
            self.discord_vowel_hint = None
            if self.on_discord_level:
                self.on_discord_level(0.0)
            return (None, pyaudio.paContinue)

        level = self._calc_level(in_data)
        now = time.time()

        if self.on_discord_level:
            self.on_discord_level(level)

        open_thresh = self.discord_threshold
        close_thresh = self.discord_threshold * self.hysteresis_ratio

        if not self.discord_talking:
            if level >= open_thresh:
                self.discord_talking = True
                self.discord_last_speak_time = now
                if self.on_discord_state:
                    self.on_discord_state(True)
        else:
            if level >= close_thresh:
                self.discord_last_speak_time = now

        self._handle_scream_level("discord", level, now)
        if level >= close_thresh:
            self.discord_vowel_hint = self._estimate_vowel_from_pcm(in_data, self._discord_rate, self._discord_channels)
        else:
            self.discord_vowel_hint = None

        return (None, pyaudio.paContinue)

    def _handle_scream_level(self, channel, level, now):
        """Procesa la detección de grito sostenido en tiempo real en cada buffer."""
        if channel == "mic":
            if self.mic_muted:
                self.mic_vowel_hint = None
                return
            thresh = self.mic_scream_threshold
            if level >= thresh:
                self.mic_last_loud_time = now
                if self.mic_scream_start_time == 0.0:
                    self.mic_scream_start_time = now
                elif (now - self.mic_scream_start_time) >= 0.50:  # ~500ms sostenido
                    if not self.mic_screaming:
                        self.mic_screaming = True
                        if self.on_mic_scream:
                            self.on_mic_scream(True)
                    self.mic_scream_end_time = now + 1.6
        elif channel == "discord":
            if self.discord_muted:
                return
            thresh = self.discord_scream_threshold
            if level >= thresh:
                self.discord_last_loud_time = now
                if self.discord_scream_start_time == 0.0:
                    self.discord_scream_start_time = now
                elif (now - self.discord_scream_start_time) >= 0.50:
                    if not self.discord_screaming:
                        self.discord_screaming = True
                        if self.on_discord_scream:
                            self.on_discord_scream(True)
                    self.discord_scream_end_time = now + 1.6

    def _monitor_loop(self):
        """Verifica tiempos de tolerancia de habla y grito."""
        while self.running:
            now = time.time()

            # Mic talking check
            if self.mic_talking and (now - self.mic_last_speak_time > self.hangover_time):
                self.mic_talking = False
                if self.on_mic_state:
                    self.on_mic_state(False)

            # Discord talking check
            if self.discord_talking and (now - self.discord_last_speak_time > self.hangover_time):
                self.discord_talking = False
                if self.on_discord_state:
                    self.on_discord_state(False)

            # Mic scream check: termina de inmediato si deja de hablar o si el volumen alto cesó hace 0.35s
            if self.mic_screaming:
                if not self.mic_talking or (now - self.mic_last_loud_time > 0.35):
                    self.mic_screaming = False
                    self.mic_scream_start_time = 0.0
                    if self.on_mic_scream:
                        self.on_mic_scream(False)
            elif self.mic_scream_start_time > 0.0:
                if not self.mic_talking or (now - self.mic_last_loud_time > 0.35):
                    self.mic_scream_start_time = 0.0

            # Discord scream check: termina de inmediato si deja de hablar o si el volumen alto cesó hace 0.35s
            if self.discord_screaming:
                if not self.discord_talking or (now - self.discord_last_loud_time > 0.35):
                    self.discord_screaming = False
                    self.discord_scream_start_time = 0.0
                    if self.on_discord_scream:
                        self.on_discord_scream(False)
            elif self.discord_scream_start_time > 0.0:
                if not self.discord_talking or (now - self.discord_last_loud_time > 0.35):
                    self.discord_scream_start_time = 0.0

            # Auto-recuperación si el stream del micrófono se queda trabado sin enviar datos (> 2s)
            if self.current_mic_index is not None and self.mic_last_callback_time > 0 and (now - self.mic_last_callback_time) > 2.0:
                self.mic_last_callback_time = now
                if self.mic_talking:
                    self.mic_talking = False
                    if self.on_mic_state:
                        self.on_mic_state(False)
                if self.mic_screaming:
                    self.mic_screaming = False
                    self.mic_scream_start_time = 0.0
                    if self.on_mic_scream:
                        self.on_mic_scream(False)
                if self.on_mic_level:
                    self.on_mic_level(0.0)
                print("[AudioEngine] Micrófono congelado detectado, reiniciando stream automáticamente...")
                self._open_mic_stream(self.current_mic_index)

            time.sleep(0.02)

    def update_thresholds(self, mic_thresh, discord_thresh, mic_scream_thresh=None, discord_scream_thresh=None):
        self.mic_threshold = float(mic_thresh)
        self.discord_threshold = float(discord_thresh)
        if mic_scream_thresh is not None:
            self.mic_scream_threshold = float(mic_scream_thresh)
        if discord_scream_thresh is not None:
            self.discord_scream_threshold = float(discord_scream_thresh)

    def toggle_mic_mute(self):
        self.mic_muted = not self.mic_muted
        if self.mic_muted:
            self.mic_vowel_hint = None
            self.mic_talking = False
            if self.on_mic_state:
                self.on_mic_state(False)
        return self.mic_muted

    def toggle_discord_mute(self):
        self.discord_muted = not self.discord_muted
        if self.discord_muted:
            self.discord_talking = False
            if self.on_discord_state:
                self.on_discord_state(False)
        return self.discord_muted

    def stop(self):
        self.running = False
        self._stop_mic_stream()
        self._stop_discord_stream()
        self.current_mic_index = None
        self.current_discord_source_info = None

    def terminate(self):
        self.stop()
        try:
            self.p.terminate()
        except Exception:
            pass
