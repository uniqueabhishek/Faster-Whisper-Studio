"""Configuration dialogs for preprocessing features in Faster-Whisper GUI."""

from __future__ import annotations

import logging
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QComboBox,
    QRadioButton,
    QButtonGroup,
)

LOGGER = logging.getLogger(__name__)


class ConfigDialogBase(QDialog):
    """Base class for configuration dialogs."""

    def __init__(self, parent=None, title="Configuration"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(550)

        # Will be populated by subclasses
        self.main_layout = QVBoxLayout(self)
        self._build_ui()
        self._add_buttons()

    def _build_ui(self):
        """Override in subclasses to build specific UI."""
        raise NotImplementedError

    def _add_buttons(self):
        """Add Cancel/Apply buttons."""
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.accept)
        self.apply_btn.setDefault(True)
        button_layout.addWidget(self.apply_btn)

        self.main_layout.addLayout(button_layout)

    def get_values(self) -> Dict:
        """Override to return configuration values."""
        raise NotImplementedError


class NoiseReductionConfigDialog(ConfigDialogBase):
    """Configuration dialog for noise reduction settings."""

    def __init__(self, parent=None, current_nr=12.0, current_nf=-25.0, current_gs=3):
        self.nr_value = current_nr
        self.nf_value = current_nf
        self.gs_value = current_gs
        super().__init__(parent, "Noise Reduction Settings")

    def _build_ui(self):
        # Preset dropdown
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Light", "Medium", "Heavy", "Custom"])
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()

        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_defaults)
        preset_layout.addWidget(reset_btn)
        self.main_layout.addLayout(preset_layout)

        # Noise Reduction Strength slider
        self.nr_slider, self.nr_label = self._create_slider_with_label(
            "Noise Reduction Strength:",
            min_val=5, max_val=30, default=int(self.nr_value),
            unit=" dB",
            left_label="Light", right_label="Heavy"
        )

        # Noise Floor slider
        self.nf_slider, self.nf_label = self._create_slider_with_label(
            "Noise Floor:",
            min_val=-50, max_val=-20, default=int(self.nf_value),
            unit=" dB",
            left_label="Conservative", right_label="Aggressive"
        )

        # Gain Smoothing slider
        self.gs_slider, self.gs_label = self._create_slider_with_label(
            "Artifact Reduction:",
            min_val=0, max_val=10, default=self.gs_value,
            unit="",
            left_label="None", right_label="Heavy"
        )

        # Preview command
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-family: monospace; background-color: #2d2d2d; color: #f0f0f0; padding: 8px; border-radius: 4px;")
        self.main_layout.addWidget(QLabel("Preview FFmpeg Command:"))
        self.main_layout.addWidget(self.preview_label)

        # Update preview on slider changes
        for slider in [self.nr_slider, self.nf_slider, self.gs_slider]:
            slider.valueChanged.connect(self._update_preview)
            slider.valueChanged.connect(lambda: self.preset_combo.setCurrentText("Custom"))

        # Set initial preset
        self._update_preview()
        self.preset_combo.setCurrentText("Medium")

    def _create_slider_with_label(self, title, min_val, max_val, default, unit, left_label, right_label):
        """Helper to create labeled slider."""
        self.main_layout.addWidget(QLabel(title))

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(left_label))

        slider = QSlider(Qt.Horizontal)  # type: ignore[attr-defined]
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        range_layout.addWidget(slider)

        range_layout.addWidget(QLabel(right_label))
        self.main_layout.addLayout(range_layout)

        value_label = QLabel(f"{default}{unit}")
        value_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        value_label.setStyleSheet("color: #3b82f6; font-weight: bold;")
        slider.valueChanged.connect(lambda v: value_label.setText(f"{v}{unit}"))
        self.main_layout.addWidget(value_label)

        return slider, value_label

    def _on_preset_changed(self, preset_name):
        """Load preset values."""
        presets = {
            "Light": (8, -35, 0),
            "Medium": (12, -25, 3),
            "Heavy": (18, -20, 5),
        }
        if preset_name in presets:
            nr, nf, gs = presets[preset_name]
            self.nr_slider.setValue(nr)
            self.nf_slider.setValue(nf)
            self.gs_slider.setValue(gs)

    def _reset_defaults(self):
        """Reset to default values."""
        self.preset_combo.setCurrentText("Medium")

    def _update_preview(self):
        """Update preview command text."""
        nr = self.nr_slider.value()
        nf = self.nf_slider.value()
        gs = self.gs_slider.value()
        cmd = f"afftdn=nr={nr}:nf={nf}:gs={gs}"
        self.preview_label.setText(cmd)

    def get_values(self) -> Dict:
        """Return selected values as dict."""
        return {
            'noise_reduction_nr': float(self.nr_slider.value()),
            'noise_reduction_nf': float(self.nf_slider.value()),
            'noise_reduction_gs': self.gs_slider.value(),
        }


class MusicRemovalConfigDialog(ConfigDialogBase):
    """Configuration dialog for music removal settings."""

    def __init__(self, parent=None, current_highpass=200, current_lowpass=3500):
        self.highpass_value = current_highpass
        self.lowpass_value = current_lowpass
        super().__init__(parent, "Background Music Removal Settings")

    def _build_ui(self):
        # Header
        header = QLabel("Speech Frequency Range Configuration")
        header.setStyleSheet("font-weight: bold; font-size: 12pt;")
        self.main_layout.addWidget(header)

        # High-Pass Filter slider
        self.highpass_slider, self.highpass_label = self._create_slider_with_label(
            "High-Pass Filter (Remove Bass/Music):",
            min_val=80, max_val=300, default=self.highpass_value,
            unit=" Hz",
            left_label="Keep Bass", right_label="Remove More"
        )

        # Low-Pass Filter slider
        self.lowpass_slider, self.lowpass_label = self._create_slider_with_label(
            "Low-Pass Filter (Remove High Frequencies):",
            min_val=3000, max_val=4000, default=self.lowpass_value,
            unit=" Hz",
            left_label="Narrow", right_label="Wide"
        )

        # Preview command
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-family: monospace; background-color: #2d2d2d; color: #f0f0f0; padding: 8px; border-radius: 4px;")
        self.main_layout.addWidget(QLabel("Preview FFmpeg Command:"))
        self.main_layout.addWidget(self.preview_label)

        # Update preview on slider changes
        for slider in [self.highpass_slider, self.lowpass_slider]:
            slider.valueChanged.connect(self._update_preview)

        self._update_preview()

    def _create_slider_with_label(self, title, min_val, max_val, default, unit, left_label, right_label):
        """Helper to create labeled slider."""
        self.main_layout.addWidget(QLabel(title))

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(left_label))

        slider = QSlider(Qt.Horizontal)  # type: ignore[attr-defined]
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        range_layout.addWidget(slider)

        range_layout.addWidget(QLabel(right_label))
        self.main_layout.addLayout(range_layout)

        value_label = QLabel(f"{default}{unit}")
        value_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        value_label.setStyleSheet("color: #3b82f6; font-weight: bold;")
        slider.valueChanged.connect(lambda v: value_label.setText(f"{v}{unit}"))
        self.main_layout.addWidget(value_label)

        return slider, value_label

    def _update_preview(self):
        """Update preview command text."""
        hp = self.highpass_slider.value()
        lp = self.lowpass_slider.value()
        cmd = f"highpass=f={hp},lowpass=f={lp}"
        self.preview_label.setText(cmd)

    def get_values(self) -> Dict:
        """Return selected values as dict."""
        return {
            'music_highpass_freq': self.highpass_slider.value(),
            'music_lowpass_freq': self.lowpass_slider.value(),
        }


class NormalizationConfigDialog(ConfigDialogBase):
    """Configuration dialog for audio normalization settings."""

    def __init__(self, parent=None, current_target=-20.0, current_tp=-1.5, current_lra=11):
        self.target_value = current_target
        self.tp_value = current_tp
        self.lra_value = current_lra
        super().__init__(parent, "Audio Normalization Settings (EBU R128)")

    def _build_ui(self):
        # Target Loudness slider
        self.target_slider, self.target_label = self._create_slider_with_label(
            "Target Loudness (LUFS):",
            min_val=-30, max_val=-10, default=int(self.target_value),
            unit=" LUFS",
            left_label="Quiet", right_label="Loud"
        )

        # True Peak slider
        self.tp_slider, self.tp_label = self._create_slider_with_label(
            "True Peak Limit:",
            min_val=-30, max_val=-5, default=int(self.tp_value * 10),  # Scale to int
            unit="",  # Will be formatted in update function
            left_label="Safe", right_label="Maximum"
        )

        # Loudness Range slider
        self.lra_slider, self.lra_label = self._create_slider_with_label(
            "Loudness Range:",
            min_val=7, max_val=20, default=self.lra_value,
            unit="",
            left_label="Compressed", right_label="Dynamic"
        )

        # Preview command
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-family: monospace; background-color: #2d2d2d; color: #f0f0f0; padding: 8px; border-radius: 4px;")
        self.main_layout.addWidget(QLabel("Preview FFmpeg Command:"))
        self.main_layout.addWidget(self.preview_label)

        # Update preview on slider changes
        for slider in [self.target_slider, self.tp_slider, self.lra_slider]:
            slider.valueChanged.connect(self._update_preview)

        self._update_preview()

    def _create_slider_with_label(self, title, min_val, max_val, default, unit, left_label, right_label):
        """Helper to create labeled slider."""
        self.main_layout.addWidget(QLabel(title))

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(left_label))

        slider = QSlider(Qt.Horizontal)  # type: ignore[attr-defined]
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        range_layout.addWidget(slider)

        range_layout.addWidget(QLabel(right_label))
        self.main_layout.addLayout(range_layout)

        value_label = QLabel(f"{default}{unit}")
        value_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        value_label.setStyleSheet("color: #3b82f6; font-weight: bold;")

        # Special handling for TP slider (decimal formatting)
        if "True Peak" in title:
            slider.valueChanged.connect(lambda v: value_label.setText(f"{v / 10.0:.1f} dB"))
        else:
            slider.valueChanged.connect(lambda v: value_label.setText(f"{v}{unit}"))

        self.main_layout.addWidget(value_label)

        return slider, value_label

    def _update_preview(self):
        """Update preview command text."""
        target = self.target_slider.value()
        tp = self.tp_slider.value() / 10.0
        lra = self.lra_slider.value()
        cmd = f"loudnorm=I={target}:TP={tp:.1f}:LRA={lra}"
        self.preview_label.setText(cmd)

    def get_values(self) -> Dict:
        """Return selected values as dict."""
        return {
            'normalize_target_db': float(self.target_slider.value()),
            'normalize_true_peak': float(self.tp_slider.value() / 10.0),
            'normalize_loudness_range': self.lra_slider.value(),
        }


class VADConfigDialog(ConfigDialogBase):
    """Configuration dialog for VAD silence trimming settings."""

    def __init__(self, parent=None, current_min_silence=3000, current_speech_pad=1000, current_threshold=0.1):
        self.min_silence_value = current_min_silence
        self.speech_pad_value = current_speech_pad
        self.threshold_value = current_threshold
        super().__init__(parent, "VAD Silence Trimming Settings")

    def _build_ui(self):
        # Minimum Silence Duration slider
        self.min_silence_slider, self.min_silence_label = self._create_slider_with_label(
            "Minimum Silence Duration to Remove:",
            min_val=1000, max_val=5000, default=self.min_silence_value,
            unit=" ms",
            left_label="Aggressive (1s)", right_label="Conservative (5s)"
        )

        # Speech Padding slider
        self.speech_pad_slider, self.speech_pad_label = self._create_slider_with_label(
            "Speech Padding (Safety Buffer):",
            min_val=0, max_val=2000, default=self.speech_pad_value,
            unit=" ms",
            left_label="None", right_label="Extra Safe (2s)"
        )

        # Detection Threshold slider (scaled by 100 for integer slider)
        self.threshold_slider, self.threshold_label = self._create_slider_with_label(
            "Speech Detection Threshold:",
            min_val=5, max_val=50, default=int(self.threshold_value * 100),
            unit="",  # Will be formatted in update function
            left_label="Very Sensitive", right_label="Less Sensitive"
        )

        # Preview config
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-family: monospace; background-color: #2d2d2d; color: #f0f0f0; padding: 8px; border-radius: 4px;")
        self.main_layout.addWidget(QLabel("Preview VAD Config:"))
        self.main_layout.addWidget(self.preview_label)

        # Update preview on slider changes
        for slider in [self.min_silence_slider, self.speech_pad_slider, self.threshold_slider]:
            slider.valueChanged.connect(self._update_preview)

        self._update_preview()

    def _create_slider_with_label(self, title, min_val, max_val, default, unit, left_label, right_label):
        """Helper to create labeled slider."""
        self.main_layout.addWidget(QLabel(title))

        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel(left_label))

        slider = QSlider(Qt.Horizontal)  # type: ignore[attr-defined]
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default)
        range_layout.addWidget(slider)

        range_layout.addWidget(QLabel(right_label))
        self.main_layout.addLayout(range_layout)

        value_label = QLabel(f"{default}{unit}")
        value_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        value_label.setStyleSheet("color: #3b82f6; font-weight: bold;")

        # Special handling for threshold slider (decimal formatting)
        if "Threshold" in title:
            slider.valueChanged.connect(lambda v: value_label.setText(f"{v / 100.0:.2f}"))
        else:
            slider.valueChanged.connect(lambda v: value_label.setText(f"{v}{unit}"))

        self.main_layout.addWidget(value_label)

        return slider, value_label

    def _update_preview(self):
        """Update preview config text."""
        min_sil = self.min_silence_slider.value()
        pad = self.speech_pad_slider.value()
        thresh = self.threshold_slider.value() / 100.0
        lines = [
            f"min_silence_duration_ms={min_sil}",
            f"speech_pad_ms={pad}",
            f"threshold={thresh:.2f}"
        ]
        self.preview_label.setText("\n".join(lines))

    def get_values(self) -> Dict:
        """Return selected values as dict."""
        return {
            'vad_min_silence_ms': self.min_silence_slider.value(),
            'vad_speech_pad_ms': self.speech_pad_slider.value(),
            'vad_threshold': float(self.threshold_slider.value() / 100.0),
        }


class WAVConfigDialog(ConfigDialogBase):
    """Configuration dialog for WAV conversion settings."""

    def __init__(self, parent=None, current_sample_rate=16000, current_channels=1, current_bit_depth=16):
        self.sample_rate_value = current_sample_rate
        self.channels_value = current_channels
        self.bit_depth_value = current_bit_depth
        super().__init__(parent, "WAV Conversion Settings")

    def _build_ui(self):
        # Sample Rate
        self.main_layout.addWidget(QLabel("Sample Rate:"))
        sr_layout = QHBoxLayout()

        self.sr_group = QButtonGroup(self)
        sample_rates = [16000, 22050, 44100, 48000]
        for i, sr in enumerate(sample_rates):
            radio = QRadioButton(f"{sr} Hz")
            radio.setProperty("sample_rate", sr)
            if sr == self.sample_rate_value:
                radio.setChecked(True)
            self.sr_group.addButton(radio, i)
            sr_layout.addWidget(radio)

        sr_layout.addStretch()
        self.main_layout.addLayout(sr_layout)

        # Channels
        self.main_layout.addWidget(QLabel("Channels:"))
        ch_layout = QHBoxLayout()

        self.ch_group = QButtonGroup(self)
        self.mono_radio = QRadioButton("Mono")
        self.stereo_radio = QRadioButton("Stereo")
        self.mono_radio.setProperty("channels", 1)
        self.stereo_radio.setProperty("channels", 2)

        if self.channels_value == 1:
            self.mono_radio.setChecked(True)
        else:
            self.stereo_radio.setChecked(True)

        self.ch_group.addButton(self.mono_radio, 0)
        self.ch_group.addButton(self.stereo_radio, 1)

        ch_layout.addWidget(self.mono_radio)
        ch_layout.addWidget(self.stereo_radio)
        ch_layout.addStretch()
        self.main_layout.addLayout(ch_layout)

        # Bit Depth
        self.main_layout.addWidget(QLabel("Bit Depth:"))
        bd_layout = QHBoxLayout()

        self.bd_group = QButtonGroup(self)
        bit_depths = [16, 24, 32]
        for i, bd in enumerate(bit_depths):
            radio = QRadioButton(f"{bd}-bit")
            radio.setProperty("bit_depth", bd)
            if bd == self.bit_depth_value:
                radio.setChecked(True)
            self.bd_group.addButton(radio, i)
            bd_layout.addWidget(radio)

        bd_layout.addStretch()
        self.main_layout.addLayout(bd_layout)

        # Preview command
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-family: monospace; background-color: #2d2d2d; color: #f0f0f0; padding: 8px; border-radius: 4px;")
        self.main_layout.addWidget(QLabel("Preview FFmpeg Command:"))
        self.main_layout.addWidget(self.preview_label)

        # Update preview on changes
        for btn in self.sr_group.buttons():
            btn.toggled.connect(self._update_preview)
        for btn in self.ch_group.buttons():
            btn.toggled.connect(self._update_preview)
        for btn in self.bd_group.buttons():
            btn.toggled.connect(self._update_preview)

        self._update_preview()

    def _update_preview(self):
        """Update preview command text."""
        sr = self.sr_group.checkedButton().property("sample_rate")  # type: ignore[union-attr]
        ch = self.ch_group.checkedButton().property("channels")  # type: ignore[union-attr]
        bd = self.bd_group.checkedButton().property("bit_depth")  # type: ignore[union-attr]

        codec_map = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
        codec = codec_map.get(bd, "pcm_s16le")

        cmd = f"-ar {sr} -ac {ch} -c:a {codec}"
        self.preview_label.setText(cmd)

    def get_values(self) -> Dict:
        """Return selected values as dict."""
        return {
            'wav_sample_rate': self.sr_group.checkedButton().property("sample_rate"),  # type: ignore[union-attr]
            'wav_channels': self.ch_group.checkedButton().property("channels"),  # type: ignore[union-attr]
            'wav_bit_depth': self.bd_group.checkedButton().property("bit_depth"),  # type: ignore[union-attr]
        }
