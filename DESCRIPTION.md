# Faster-Whisper AI Transcriber

**Professional Audio-to-Text Solution**

## Overview

A powerful desktop application for converting audio and video files into accurate text transcriptions using state-of-the-art AI technology powered by OpenAI's Whisper model.

## Key Features

### ✓ Modern User Interface
*   Sleek dark-themed GUI with intuitive sidebar navigation
*   Seamless workflow between Preprocessing and Transcription views
*   Drag-and-drop file support for effortless operation
*   Real-time progress tracking and live logs
*   Independent preprocessing windows for multi-tasking

### ✓ Advanced Audio Preprocessing
*   Intelligent Noise Reduction - Remove background noise with customizable strength and noise floor settings
*   Music Removal - Filter out background music while preserving speech clarity
*   Audio Normalization - Automatically balance audio levels for consistent quality
*   Voice Activity Detection (VAD) - Trim silence and detect speech segments automatically
*   Format Conversion - Convert any audio format to optimized WAV with configurable sample rates (16kHz, 22kHz, 44.1kHz, 48kHz)
*   Flexible Audio Settings - Choose mono/stereo output and bit depth (16/24/32-bit)

### ✓ Powerful Transcription Engine
*   Multi-Language Support - Auto-detect or manually select from multiple languages (English, Hindi, Japanese, Chinese, German, and more)
*   Precision Control - Two analysis modes:
    *   Precise Analysis (beam size 5) for balanced speed and accuracy
    *   Deep Analysis (beam size 10) for maximum accuracy
*   Advanced Options:
    *   Word-level timestamps for precise timing
    *   Language detection for automatic identification
    *   Custom initial prompts for context-aware transcription
    *   Batch processing for multiple files

### ✓ Professional Output Formats
*   Text Files (.txt) - Clean, readable transcripts
*   SRT Subtitles (.srt) - Perfect for video captioning
*   VTT Subtitles (.vtt) - Web-compatible subtitle format
*   JSON (.json) - Structured data with detailed metadata

### ✓ Performance & Efficiency
*   GPU Acceleration - Automatic CUDA detection for faster processing
*   Multi-threaded Architecture - Utilize all CPU cores for optimal performance
*   Lazy Model Loading - Only loads AI models when needed to save memory
*   Batch Processing - Process multiple files in queue automatically
*   Smart Caching - Efficient resource management

### ✓ User-Friendly Features
*   Persistent Settings - Remembers your preferences between sessions
*   Queue Management - Add, remove, and organize files easily
*   Real-time Status Updates - Track progress with detailed logging
*   Error Handling - Graceful error recovery with detailed error messages
*   Output Organization - Automatic file naming and directory management
*   One-Click Folder Access - Instantly open output directories

### ✓ Format Compatibility
*   Audio: MP3, WAV, M4A, FLAC, OGG
*   Video: MP4, MKV, WEBM (extracts audio automatically)

### ✓ Professional Quality
*   Offline operation (no internet required after setup)
*   Bundled VAD model for reliable speech detection
*   Exception handling and crash recovery
*   Detailed debug logging for troubleshooting
*   Clean, maintainable codebase

## Ideal For
*   Content creators and podcasters
*   Journalists and researchers
*   Students and educators
*   Business professionals
*   Video producers and editors
*   Accessibility services
*   Anyone needing fast, accurate transcriptions

## Whisper Model Capacities

The application supports all OpenAI Whisper model sizes, allowing you to choose the right balance between speed and accuracy for your needs:

| Model | Parameters | RAM | Description |
| :--- | :--- | :--- | :--- |
| **TINY** | 39 M parameters | ~1 GB RAM | Fastest, basic accuracy - Good for quick drafts |
| **BASE** | 74 M parameters | ~1 GB RAM | Fast, improved accuracy - Good for simple audio |
| **SMALL** | 244 M parameters | ~2 GB RAM | Balanced speed/accuracy - Recommended for most users |
| **MEDIUM** | 769 M parameters | ~5 GB RAM | High accuracy - Professional quality |
| **LARGE-V1/V2** | 1550 M parameters | ~10 GB RAM | Highest accuracy - Best for critical work |
| **LARGE-V3** | 1550 M parameters | ~10 GB RAM | Latest & most accurate - Cutting-edge performance |

### Performance Notes:
*   GPU Acceleration: With CUDA-capable GPU, even large models run 5-10x faster
*   CPU Performance: All models work on CPU, though larger models are slower
*   Memory: Requirements decrease with GPU acceleration
*   Recommended: "small" model for most users, "medium" or "large" for professional work
*   Model Selection: Choose based on your hardware, accuracy needs, and speed requirements

## Technical Highlights
*   Built with PyQt5 for cross-platform compatibility
*   Powered by Faster-Whisper (optimized implementation of OpenAI Whisper)
*   FFmpeg integration for robust audio processing
*   Thread-safe architecture with concurrent processing
*   Modular design for easy maintenance and extension

---
*Version 2.1.3*
*Developed by Abhishek's AI Labs*
