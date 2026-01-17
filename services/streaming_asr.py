# services/streaming_asr.py
"""
Streaming ASR (Automatic Speech Recognition) Manager
=====================================================
Manages real-time speech-to-text streaming using Google Cloud Speech API.

Features:
- Bidirectional gRPC streaming
- Interim (partial) results support
- Automatic stream restart for long sessions
- Thread-safe audio queue management
"""

from google.cloud import speech_v1 as speech
from google.api_core import exceptions as google_exceptions
import threading
import queue
import time
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum


class StreamState(Enum):
    """Streaming session states"""
    IDLE = "idle"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class TranscriptionResult:
    """Transcription result container"""
    text: str
    is_final: bool
    confidence: float
    stability: float
    language: str
    timestamp: float


# Language code mappings for Google Speech API
SPEECH_LANGUAGE_CODES = {
    "en": "en-US",
    "ja": "ja-JP",
    "zh": "zh-CN",
    "ko": "ko-KR",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "my": "ms-MY",
    "th": "th-TH",
    "vi": "vi-VN",
    "id": "id-ID",
    "pt": "pt-BR",
    "ru": "ru-RU",
    "ar": "ar-XA"
}


class StreamingASRManager:
    """
    Manages a streaming speech recognition session.
    
    Usage:
        manager = StreamingASRManager(
            language='en',
            on_partial=lambda r: print(f"Partial: {r.text}"),
            on_final=lambda r: print(f"Final: {r.text}"),
            on_error=lambda e: print(f"Error: {e}")
        )
        manager.start()
        manager.add_audio(audio_chunk)
        manager.stop()
    """
    
    # Google Speech API limits
    MAX_STREAM_DURATION = 290  # seconds (limit is 305, we restart before)
    RESTART_BUFFER_TIME = 5   # seconds before limit to restart
    
    def __init__(
        self,
        language: str,
        on_partial: Optional[Callable[[TranscriptionResult], None]] = None,
        on_final: Optional[Callable[[TranscriptionResult], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        sample_rate: int = 16000,
        encoding: str = "LINEAR16"
    ):
        """
        Initialize streaming ASR manager.
        
        Args:
            language: Language code (e.g., 'en', 'ja', 'zh')
            on_partial: Callback for partial (interim) results
            on_final: Callback for final results
            on_error: Callback for errors
            sample_rate: Audio sample rate in Hz
            encoding: Audio encoding format
        """
        self.language = language
        self.language_code = SPEECH_LANGUAGE_CODES.get(language, "en-US")
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error
        self.sample_rate = sample_rate
        self.encoding = self._get_encoding(encoding)
        
        # State management
        self.state = StreamState.IDLE
        self._state_lock = threading.Lock()
        
        # Audio queue
        self._audio_queue: queue.Queue = queue.Queue()
        
        # Streaming thread
        self._stream_thread: Optional[threading.Thread] = None
        
        # Timing
        self._stream_start_time: Optional[float] = None
        self._last_audio_time: Optional[float] = None
        
        # Client
        self._client: Optional[speech.SpeechClient] = None
        
        # Stats
        self.total_audio_chunks = 0
        self.total_results = 0
    
    def _get_encoding(self, encoding: str) -> speech.RecognitionConfig.AudioEncoding:
        """Convert encoding string to enum"""
        encodings = {
            "LINEAR16": speech.RecognitionConfig.AudioEncoding.LINEAR16,
            "FLAC": speech.RecognitionConfig.AudioEncoding.FLAC,
            "MULAW": speech.RecognitionConfig.AudioEncoding.MULAW,
            "OGG_OPUS": speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
            "WEBM_OPUS": speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
        }
        return encodings.get(encoding, speech.RecognitionConfig.AudioEncoding.LINEAR16)
    
    def start(self) -> bool:
        """
        Start the streaming recognition session.
        
        Returns:
            True if started successfully, False otherwise
        """
        with self._state_lock:
            if self.state != StreamState.IDLE:
                return False
            self.state = StreamState.STARTING
        
        try:
            # Initialize client
            self._client = speech.SpeechClient()
            
            # Clear queue
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Start streaming thread
            self._stream_thread = threading.Thread(
                target=self._streaming_loop,
                daemon=True
            )
            self._stream_thread.start()
            
            with self._state_lock:
                self.state = StreamState.ACTIVE
            
            self._stream_start_time = time.time()
            print(f"[StreamingASR] Started for language: {self.language_code}")
            return True
            
        except Exception as e:
            with self._state_lock:
                self.state = StreamState.ERROR
            if self.on_error:
                self.on_error(e)
            print(f"[StreamingASR] Start error: {e}")
            return False
    
    def stop(self) -> None:
        """Stop the streaming recognition session."""
        with self._state_lock:
            if self.state not in [StreamState.ACTIVE, StreamState.STARTING]:
                return
            self.state = StreamState.STOPPING
        
        # Signal end of audio
        self._audio_queue.put(None)
        
        # Wait for thread to finish
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=5.0)
        
        with self._state_lock:
            self.state = StreamState.IDLE
        
        print(f"[StreamingASR] Stopped. Chunks: {self.total_audio_chunks}, Results: {self.total_results}")
    
    def add_audio(self, audio_bytes: bytes) -> bool:
        """
        Add audio chunk to the stream.
        
        Args:
            audio_bytes: Raw audio data
            
        Returns:
            True if added successfully, False otherwise
        """
        with self._state_lock:
            if self.state != StreamState.ACTIVE:
                return False
        
        self._audio_queue.put(audio_bytes)
        self._last_audio_time = time.time()
        self.total_audio_chunks += 1
        
        # Check if we need to restart the stream (approaching time limit)
        if self._should_restart():
            self._restart_stream()
        
        return True
    
    def _should_restart(self) -> bool:
        """Check if stream needs to be restarted due to duration limit"""
        if self._stream_start_time is None:
            return False
        
        elapsed = time.time() - self._stream_start_time
        return elapsed >= (self.MAX_STREAM_DURATION - self.RESTART_BUFFER_TIME)
    
    def _restart_stream(self) -> None:
        """Restart the stream to avoid hitting the duration limit"""
        print("[StreamingASR] Restarting stream due to duration limit...")
        
        # Stop current stream
        self._audio_queue.put(None)
        
        # Wait briefly
        time.sleep(0.1)
        
        # Start new stream
        self._stream_start_time = time.time()
        
        # Start new streaming thread
        self._stream_thread = threading.Thread(
            target=self._streaming_loop,
            daemon=True
        )
        self._stream_thread.start()
    
    def _streaming_loop(self) -> None:
        """Main streaming loop (runs in separate thread)"""
        try:
            # Determine best model for language
            # 'latest_long' is optimized for long form but has limited language support
            model = "latest_long"
            use_enhanced = True
            
            # Use 'default' for languages known to have issues with latest_long
            if self.language_code.startswith("zh"):  # Chinese
                model = "default"
                use_enhanced = False
            elif self.language_code.startswith("ja"): # Japanese
                model = "default"
                use_enhanced = False
            elif self.language_code.startswith("ko"): # Korean
                model = "default"
                use_enhanced = False
            
            # Build recognition config
            config = speech.RecognitionConfig(
                encoding=self.encoding,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language_code,
                enable_automatic_punctuation=True,
                model=model,
                use_enhanced=use_enhanced,
                # Enable word-level confidence
                enable_word_confidence=True,
            )
            
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=True,  # 👈 Key: Enable partial results
                single_utterance=False,  # Allow multiple utterances
            )
            
            # Start streaming recognition
            try:
                # Try standard signature first (keyword args to be safe)
                # Standard uses _request_generator (Config + Audio)
                requests = self._request_generator(streaming_config)
                responses = self._client.streaming_recognize(requests=requests)
            except TypeError as e:
                print(f"[StreamingASR] Standard call failed: {e}. Attempting SpeechHelpers signature...")
                
                # SpeechHelpers typically takes (config, requests) where requests is AUDIO ONLY
                # because it sends the config itself.
                audio_requests = self._audio_generator()
                
                # Try with config argument
                responses = self._client.streaming_recognize(config=streaming_config, requests=audio_requests)
            
            # Process responses
            for response in responses:
                if self.state == StreamState.STOPPING:
                    break
                self._handle_response(response)
                
        except google_exceptions.OutOfRange:
            # Stream duration exceeded - this is expected
            print("[StreamingASR] Stream duration limit reached")
        except google_exceptions.Cancelled:
            # Stream was cancelled - expected on stop
            pass
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[StreamingASR] Streaming error: {e}")
            if self.on_error:
                self.on_error(e)
    
    def _request_generator(self, streaming_config):
        """Generate streaming requests (Config + Audio)"""
        # First request must contain config
        yield speech.StreamingRecognizeRequest(
            streaming_config=streaming_config
        )
        
        # Subsequent requests contain audio
        yield from self._audio_generator()
            
    def _audio_generator(self):
        """Generate only audio chunks"""
        while True:
            try:
                chunk = self._audio_queue.get(timeout=1.0)
                
                if chunk is None:
                    # End of stream signal
                    break
                
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
                
            except queue.Empty:
                # No audio received, check if still active
                if self.state == StreamState.STOPPING:
                    break
                continue
    
    def _handle_response(self, response) -> None:
        """Handle streaming recognition response"""
        if not response.results:
            return
        
        for result in response.results:
            if not result.alternatives:
                continue
            
            alternative = result.alternatives[0]
            
            transcription = TranscriptionResult(
                text=alternative.transcript,
                is_final=result.is_final,
                confidence=alternative.confidence if result.is_final else 0.0,
                stability=result.stability if hasattr(result, 'stability') else 0.0,
                language=self.language,
                timestamp=time.time()
            )
            
            self.total_results += 1
            
            if result.is_final:
                if self.on_final:
                    self.on_final(transcription)
            else:
                if self.on_partial:
                    self.on_partial(transcription)
    
    @property
    def is_active(self) -> bool:
        """Check if streaming is active"""
        with self._state_lock:
            return self.state == StreamState.ACTIVE
    
    def get_stats(self) -> dict:
        """Get streaming statistics"""
        elapsed = 0
        if self._stream_start_time:
            elapsed = time.time() - self._stream_start_time
        
        return {
            "state": self.state.value,
            "language": self.language_code,
            "total_chunks": self.total_audio_chunks,
            "total_results": self.total_results,
            "elapsed_seconds": round(elapsed, 2),
            "queue_size": self._audio_queue.qsize()
        }


class ConversationStreamManager:
    """
    Manages streaming for a two-speaker conversation.
    Handles Speaker A and Speaker B with their respective languages.
    """
    
    def __init__(
        self,
        lang_a: str,
        lang_b: str,
        on_partial: Optional[Callable[[str, TranscriptionResult], None]] = None,
        on_final: Optional[Callable[[str, TranscriptionResult], None]] = None,
        on_error: Optional[Callable[[str, Exception], None]] = None
    ):
        """
        Initialize conversation stream manager.
        
        Args:
            lang_a: Speaker A's language
            lang_b: Speaker B's language
            on_partial: Callback(speaker, result) for partial results
            on_final: Callback(speaker, result) for final results
            on_error: Callback(speaker, error) for errors
        """
        self.lang_a = lang_a
        self.lang_b = lang_b
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        
        self._streams: dict[str, Optional[StreamingASRManager]] = {
            'A': None,
            'B': None
        }
        self._current_speaker: Optional[str] = None
    
    def start_speaker(self, speaker: str) -> bool:
        """Start streaming for a specific speaker"""
        if speaker not in ['A', 'B']:
            return False
        
        # Stop previous speaker if different
        if self._current_speaker and self._current_speaker != speaker:
            self.stop_speaker(self._current_speaker)
        
        language = self.lang_a if speaker == 'A' else self.lang_b
        
        # Create callbacks that include speaker info
        def on_partial(result):
            if self._on_partial:
                self._on_partial(speaker, result)
        
        def on_final(result):
            if self._on_final:
                self._on_final(speaker, result)
        
        def on_error(error):
            if self._on_error:
                self._on_error(speaker, error)
        
        # Create and start stream with WebM Opus encoding (browser standard)
        stream = StreamingASRManager(
            language=language,
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            sample_rate=48000,  # WebM Opus typically uses 48kHz
            encoding="WEBM_OPUS"
        )
        
        if stream.start():
            self._streams[speaker] = stream
            self._current_speaker = speaker
            return True
        
        return False
    
    def stop_speaker(self, speaker: str) -> None:
        """Stop streaming for a specific speaker"""
        if speaker in self._streams and self._streams[speaker]:
            self._streams[speaker].stop()
            self._streams[speaker] = None
        
        if self._current_speaker == speaker:
            self._current_speaker = None
    
    def add_audio(self, speaker: str, audio_bytes: bytes) -> bool:
        """Add audio for a specific speaker"""
        if speaker not in self._streams or not self._streams[speaker]:
            return False
        
        return self._streams[speaker].add_audio(audio_bytes)
    
    def stop_all(self) -> None:
        """Stop all streaming"""
        for speaker in ['A', 'B']:
            self.stop_speaker(speaker)
    
    def swap_languages(self) -> None:
        """Swap languages between speakers"""
        self.lang_a, self.lang_b = self.lang_b, self.lang_a
    
    @property
    def current_speaker(self) -> Optional[str]:
        """Get current active speaker"""
        return self._current_speaker
    
    def get_stats(self) -> dict:
        """Get stats for all streams"""
        return {
            "current_speaker": self._current_speaker,
            "lang_a": self.lang_a,
            "lang_b": self.lang_b,
            "streams": {
                speaker: stream.get_stats() if stream else None
                for speaker, stream in self._streams.items()
            }
        }
