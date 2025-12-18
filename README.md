# Faster-Whisper AI Transcriber

A powerful desktop GUI application for accurate audio/video transcription using OpenAI's Whisper model via the faster-whisper implementation. Features advanced audio preprocessing, batch processing, session recovery, and intelligent memory management.

## Features

### Core Transcription
- **Multiple Model Sizes**: tiny, base, small, medium, large-v2, large-v3
- **GPU Acceleration**: CUDA support for faster processing (requires NVIDIA GPU)
- **Multi-language Support**: Auto-detect or specify from 10+ languages
- **Batch Processing**: Queue multiple files for sequential transcription
- **Session Resume**: Automatic crash recovery and resume capability
- **Smart Memory Management**: Prevents MemoryError crashes with automatic cleanup

### Audio Preprocessing
- **Noise Reduction**: DeepFilterNet-based noise suppression
- **Music Removal**: Demucs-powered vocal isolation
- **Audio Normalization**: Peak and loudness normalization
- **Voice Activity Detection (VAD)**: Remove silence from recordings
- **Format Conversion**: WAV conversion with customizable sample rate

### Output Options
- **Multiple Formats**: TXT, SRT (subtitles), VTT, JSON, TSV
- **Word-Level Timestamps**: Precise word timing information
- **Segment Analysis**: Identify word-dense and time-dense segments
- **Document Generation**: Export analysis reports to Word documents
- **Custom Output Paths**: Choose where to save transcriptions

### User Interface
- **Dark Theme**: Modern, easy-on-the-eyes interface
- **Drag & Drop**: Simple file addition to queue
- **Real-time Logs**: Monitor transcription progress
- **Dual View**: Separate preprocessing and transcription panels
- **Status Tracking**: Visual progress bars and status indicators

## Requirements

### System Requirements
- **Operating System**: Windows 10/11
- **Python**: 3.9 - 3.12 (Python 3.14 may have compatibility issues)
- **RAM**: Minimum 8GB (16GB+ recommended for large files)
- **Disk Space**: 2-10GB depending on model size

### For GPU Acceleration (Optional)
- **NVIDIA GPU**: CUDA-compatible graphics card
- **CUDA Toolkit**: 11.8
- **cuDNN**: For CUDA 11.x
- Without GPU support, the app runs in CPU mode (slower but functional)

## Installation

### Option 1: From Source

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/Faster-Whisper_GUI_APP.git
   cd Faster-Whisper_GUI_APP
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

### Option 2: Standalone Executable

Download the latest release from the [Releases](https://github.com/yourusername/Faster-Whisper_GUI_APP/releases) page and run `FasterWhisperGUI.exe`.

## Usage

### Basic Transcription

1. **Launch the application**
   - Run `python app.py` or double-click the executable

2. **Add files to queue**
   - Click "Add Files" or drag & drop media files
   - Supported formats: MP3, WAV, M4A, FLAC, OGG, MP4, MKV, WEBM

3. **Configure settings**
   - Select model size (larger = more accurate, slower)
   - Choose device (CPU/GPU)
   - Pick language or use auto-detect
   - Enable word timestamps if needed

4. **Start transcription**
   - Click "Start Batch"
   - Monitor progress in real-time
   - Find output files in the same directory as source files

### Audio Preprocessing

1. **Switch to Preprocessing tab**
   - Click "Preprocessing" in the sidebar

2. **Add files and enable processing**
   - Add audio/video files
   - Check desired preprocessing options:
     - **Noise Reduction**: Remove background noise
     - **Music Removal**: Extract vocals only
     - **Normalization**: Standardize audio levels
     - **VAD**: Remove silence
     - **WAV Conversion**: Convert to WAV format

3. **Configure each option**
   - Click "Configure" button next to each option
   - Adjust settings based on your audio

4. **Process files**
   - Click "Start Processing"
   - Send to transcription or save separately

### Session Recovery

If transcription is interrupted:

1. **Restart the application**
2. **Resume prompt appears** if incomplete sessions exist
3. **Choose to resume or start fresh**
4. **Completed files are skipped** automatically

## Configuration Options

### Transcription Settings

| Setting | Options | Description |
|---------|---------|-------------|
| Model | tiny, base, small, medium, large-v2, large-v3 | Accuracy vs speed tradeoff |
| Device | CPU, CUDA | Processing device |
| Language | Auto, English, Hindi, Japanese, etc. | Target language |
| Compute Type | int8, float16, float32 | Precision level |
| Beam Size | 1-10 | Search breadth (higher = slower, more accurate) |
| Temperature | 0.0-1.0 | Sampling randomness |
| VAD Filter | On/Off | Voice activity detection |

### Output Settings

- **Output Format**: Text, SRT, VTT, JSON, TSV
- **Word Timestamps**: Include precise word timing
- **Custom Output Directory**: Choose save location
- **Segment Analysis**: Identify dense segments

### Preprocessing Options

- **Noise Reduction**: Strength levels (0-1.0)
- **Music Removal**: Vocal isolation quality
- **Normalization**: Target level and method
- **VAD**: Threshold and padding
- **WAV**: Sample rate and bit depth

## Advanced Features

### Batch Processing

Queue multiple files and let them process sequentially:
- Automatic memory cleanup between files
- Skip already-processed files
- Resume failed files
- Export batch results

### Memory Management

The app automatically:
- Monitors memory usage
- Cleans up after each file
- Performs aggressive cleanup on errors
- Clears GPU CUDA cache (if applicable)

### Word Analysis

Identify interesting segments:
- **Word-Dense**: Rapid speech sections
- **Time-Dense**: Slow speech sections
- Configurable thresholds
- Export to Word documents

## Troubleshooting

### Common Issues

**App crashes with MemoryError**
- Use a smaller model (tiny/base instead of large)
- Process files individually instead of batch
- Close other memory-intensive applications
- Upgrade RAM if possible

**GPU not detected**
- Install CUDA Toolkit 11.8
- Install cuDNN for CUDA 11.x
- Verify NVIDIA drivers are up-to-date
- Check GPU compatibility

**Transcription is inaccurate**
- Use a larger model (large-v3 recommended)
- Specify language instead of auto-detect
- Apply noise reduction preprocessing
- Check audio quality

**Slow transcription speed**
- Enable GPU acceleration
- Use smaller model for faster results
- Reduce beam size
- Disable word timestamps if not needed

**Preprocessing fails**
- Check disk space availability
- Verify input file isn't corrupted
- Try disabling specific preprocessing steps
- Check logs for specific errors

## Building from Source

### Create Executable

```bash
python build_exe.py
```

The executable will be created in the `dist/` directory.

### Requirements for Building
- PyInstaller
- All runtime dependencies
- Visual C++ Redistributable (included)

## Project Structure

```
Faster-Whisper_GUI_APP/
├── app.py                          # Application entry point
├── main_window.py                  # Main window with sidebar navigation
├── gui.py                          # Transcription view and UI
├── preprocessing_gui.py            # Preprocessing view and UI
├── transcriber.py                  # Core transcription logic
├── audio_processor.py              # Audio preprocessing utilities
├── workers.py                      # Background worker threads
├── session_manager.py              # Session persistence and recovery
├── memory_manager.py               # Memory monitoring and cleanup
├── resume_dialog.py                # Resume session dialog
├── preprocessing_worker.py         # Preprocessing background worker
├── preprocessing_config_dialogs.py # Configuration dialogs
├── styles.py                       # Dark theme and styling
├── requirements.txt                # Python dependencies
├── assets/                         # Icons and resources
│   └── silero_vad.onnx            # VAD model
└── build_exe.py                    # Build script for executable
```

## Technical Details

### Dependencies

**Core Libraries:**
- `PyQt5` - GUI framework
- `faster-whisper` - Whisper implementation
- `ctranslate2` - Efficient inference engine
- `huggingface-hub` - Model downloads

**Preprocessing:**
- `deepfilternet` - Noise reduction
- `torch` / `torchaudio` - Audio processing
- `librosa` - Audio analysis
- `soundfile` - Audio I/O

**Utilities:**
- `psutil` - Memory monitoring
- `python-docx` - Document generation
- `onnxruntime` - VAD model inference

### Architecture

- **Multi-threaded**: Background workers for non-blocking UI
- **Signal-based**: Qt signals for thread-safe communication
- **Persistent sessions**: JSON-based state management
- **Memory-conscious**: Automatic garbage collection and cleanup
- **Modular design**: Separation of concerns across components

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- **OpenAI Whisper**: Original speech recognition model
- **faster-whisper**: Efficient Whisper implementation
- **Silero VAD**: Voice activity detection model
- **DeepFilterNet**: Noise reduction model
- **Demucs**: Music source separation

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review the troubleshooting section

## Version History

### v2.1.3 (Current)
- Session resume and crash recovery
- Automatic memory management
- Unified window with sidebar navigation
- Enhanced preprocessing options
- Improved error handling

### Previous Versions
- See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for detailed changes
- See [FIXES_APPLIED.md](FIXES_APPLIED.md) for bug fixes

---

**Made with Faster-Whisper and PyQt5**
