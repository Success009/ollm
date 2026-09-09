"""
Real-time streaming speech synthesizer for OLLM.
Synthesizes and queues audio sentence-by-sentence in parallel with model generation.
Filters out XML tool tags, code blocks, and markdown clutter to produce natural human speech.
"""
import os
import re
import sys
import queue
import asyncio
import tempfile
import threading
import subprocess
from typing import Optional

DEFAULT_VOICE = "en-US-ChristopherNeural"

def clean_for_speech(text: str) -> str:
    """Removes code blocks, XML tags, and raw formatting so only natural speech is spoken."""
    if not text:
        return ""
    # 1. Remove XML tool tags and their contents
    text = re.sub(r'<(calc|bash|read|write|find|sysinfo|tool_result|tool)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+/>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    # 2. Remove markdown code blocks and inline code
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', '', text)
    # 3. Remove markdown formatting symbols
    text = re.sub(r'[*#_~|>]', '', text)
    # 4. Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

class StreamingVoiceEngine:
    """
    Parallel sentence-by-sentence voice pipeline.
    Generates audio for line 1 while line 2 is generating, and plays without lag.
    """
    def __init__(self, voice: str = DEFAULT_VOICE, enabled: bool = False):
        self.voice = voice
        self.enabled = enabled
        self.text_queue: queue.Queue = queue.Queue()
        self.audio_queue: queue.Queue = queue.Queue()
        self.current_player: Optional[subprocess.Popen] = None
        self._running = True
        self._interrupted = threading.Event()
        self._lock = threading.Lock()

        # Start synthesizer and playback background threads
        self.synth_thread = threading.Thread(target=self._synthesize_worker, daemon=True)
        self.play_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.synth_thread.start()
        self.play_thread.start()

    def toggle(self) -> bool:
        """Toggles voice synthesis on or off."""
        self.enabled = not self.enabled
        if not self.enabled:
            self.stop()
        return self.enabled

    def feed_sentence(self, raw_sentence: str):
        """Feeds a sentence to be cleaned and synthesized."""
        if not self.enabled:
            return
        cleaned = clean_for_speech(raw_sentence)
        if cleaned and len(cleaned) >= 2:
            self.text_queue.put(cleaned)

    def stop(self):
        """Immediately interrupts active synthesis and stops audio playback."""
        self._interrupted.set()
        # Drain queues
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        while not self.audio_queue.empty():
            try:
                path = self.audio_queue.get_nowait()
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            except queue.Empty:
                break

        with self._lock:
            if self.current_player and self.current_player.poll() is None:
                try:
                    self.current_player.terminate()
                    self.current_player.wait(timeout=0.2)
                except Exception:
                    try:
                        self.current_player.kill()
                    except Exception:
                        pass
                self.current_player = None

        self._interrupted.clear()

    def _synthesize_worker(self):
        """Background worker: converts text sentences into audio chunks."""
        while self._running:
            try:
                text = self.text_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._interrupted.is_set() or not self.enabled:
                continue

            tmp_audio = tempfile.mktemp(suffix=".mp3", prefix="ollm_voice_")
            success = self._render_audio(text, tmp_audio)

            if success and os.path.exists(tmp_audio) and os.path.getsize(tmp_audio) > 0:
                if not self._interrupted.is_set():
                    self.audio_queue.put(tmp_audio)
                else:
                    try:
                        os.remove(tmp_audio)
                    except OSError:
                        pass
            else:
                if os.path.exists(tmp_audio):
                    try:
                        os.remove(tmp_audio)
                    except OSError:
                        pass

    def _render_audio(self, text: str, output_path: str) -> bool:
        """Attempts neural synthesis via edge-tts, with fallback to local spd-say."""
        try:
            import edge_tts
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                comm = edge_tts.Communicate(text, self.voice)
                loop.run_until_complete(comm.save(output_path))
                return True
            finally:
                loop.close()
        except Exception:
            pass

        # Offline fallback: spd-say
        try:
            if subprocess.run(["which", "spd-say"], stdout=subprocess.DEVNULL).returncode == 0:
                subprocess.Popen(["spd-say", "-r", "10", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return False
        except Exception:
            pass

        return False

    def _playback_worker(self):
        """Background worker: plays synthesized audio chunks sequentially without overlapping."""
        while self._running:
            try:
                audio_file = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._interrupted.is_set():
                if os.path.exists(audio_file):
                    try:
                        os.remove(audio_file)
                    except OSError:
                        pass
                continue

            # Play audio file using mpv, paplay, or ffplay
            player_cmd = None
            if subprocess.run(["which", "mpv"], stdout=subprocess.DEVNULL).returncode == 0:
                player_cmd = ["mpv", "--no-video", "--really-quiet", audio_file]
            elif subprocess.run(["which", "ffplay"], stdout=subprocess.DEVNULL).returncode == 0:
                player_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_file]
            elif subprocess.run(["which", "paplay"], stdout=subprocess.DEVNULL).returncode == 0:
                player_cmd = ["paplay", audio_file]

            if player_cmd:
                with self._lock:
                    self.current_player = subprocess.Popen(player_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.current_player.wait()
                with self._lock:
                    self.current_player = None

            # Clean up temp file
            if os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except OSError:
                    pass
