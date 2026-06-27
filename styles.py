"""
Modern Dark Theme for Faster-Whisper GUI.
Colors:
- Background: #1e1e1e (Dark Grey)
- Surface: #2d2d2d (Lighter Grey for cards/inputs)
- Primary: #3b82f6 (Bright Blue)
- Text: #e5e7eb (Off-white)
- Border: #404040
"""

import ctypes

def apply_dark_title_bar(window_handle):
    """
    Apply Windows Immersive Dark Mode to the title bar.
    Requires Windows 10 (Build 1903+) or Windows 11.
    """
    try:
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 2004+ / Windows 11)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        hwnd = window_handle

        # If it's a PyQt window, we might need the underlying HWND
        # But usually passing int(winId()) works.

        rendering_policy = DWMWA_USE_IMMERSIVE_DARK_MODE
        value = ctypes.c_int(2) # 2 = True (technically boolean, but 1 or non-zero)
        # Actually for this attribute, TRUE (1) is needed.
        value = ctypes.c_int(1)

        set_window_attribute(
            hwnd,
            rendering_policy,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
    except Exception:
        # Fail silently if not on Windows or older version
        pass

DARK_THEME_QSS = """
/* Main Window */
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e5e7eb;
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
}

/* Group Boxes / Cards */
QGroupBox {
    background-color: #252526;
    border: 1px solid #3f3f46;
    border-radius: 8px;
    margin-top: 1em;
    padding-top: 10px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #9ca3af;
}

/* Inputs */
QLineEdit {
    background-color: #2d2d2d;
    border: 1px solid #404040;
    border-radius: 6px;
    padding: 8px;
    color: #ffffff;
    selection-background-color: #3b82f6;
}
QLineEdit:focus {
    border: 1px solid #3b82f6;
    background-color: #333333;
}
QLineEdit:read-only {
    background-color: #262626;
    color: #9ca3af;
}

/* ComboBox */
QComboBox {
    background-color: #2d2d2d;
    border: 1px solid #404040;
    border-radius: 6px;
    padding: 8px;
    color: #ffffff;
}
QComboBox::drop-down {
    border: none;
}
QComboBox::down-arrow {
    image: url(assets/chevron_down.svg);
    width: 12px;
    height: 12px;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #ffffff;
    selection-background-color: #3b82f6;
    border: 1px solid #404040;
}

/* Primary Buttons — the main call-to-action (solid blue) */
QPushButton {
    background-color: #3b82f6;
    color: #ffffff;
    border: 1px solid #3b82f6;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #2563eb;
    border-color: #60a5fa;
}
QPushButton:pressed {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}
QPushButton:disabled {
    background-color: #262626;
    border-color: #333333;
    color: #6b7280;
}

/* Secondary Buttons (Browse, Add Files, …) — quiet outline style */
QPushButton#SecondaryBtn {
    background-color: transparent;
    color: #d1d5db;
    border: 1px solid #404040;
}
QPushButton#SecondaryBtn:hover {
    background-color: #2d2d2d;
    border-color: #3b82f6;
    color: #ffffff;
}
QPushButton#SecondaryBtn:pressed {
    background-color: #262626;
    border-color: #2563eb;
}
QPushButton#SecondaryBtn:disabled {
    background-color: transparent;
    border-color: #333333;
    color: #6b7280;
}

/* Settings (gear) buttons — circular icon button (fixed 30x30).
   padding:0 keeps the base 8px 16px padding from clipping the ⚙ glyph. */
QPushButton#SettingsBtn {
    background-color: #2d2d2d;
    color: #9ca3af;
    border: 1px solid #404040;
    border-radius: 15px;
    padding: 0;
    font-size: 16px;
    font-weight: bold;
}
QPushButton#SettingsBtn:hover {
    background-color: #374151;
    border-color: #3b82f6;
    color: #ffffff;
}
QPushButton#SettingsBtn:pressed {
    background-color: #1f2937;
    border-color: #2563eb;
}

/* Text Area (Logs/Output) */
QTextEdit {
    background-color: #111827; /* Very dark for code/logs */
    border: 1px solid #374151;
    border-radius: 6px;
    color: #10b981; /* Matrix green-ish for logs, or just white */
    font-family: 'Consolas', 'Monospace';
    font-size: 13px;
    padding: 8px;
}

/* Progress Bar */
QProgressBar {
    border: none;
    background-color: #374151;
    border-radius: 4px;
    text-align: center;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 4px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #1e1e1e;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #4b5563;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* List Widget */
QListWidget {
    background-color: #2d2d2d;
    border: 1px solid #404040;
    border-radius: 6px;
    padding: 5px;
}
QListWidget::item {
    padding: 5px;
    border-bottom: 1px solid #3f3f46;
}
QListWidget::item:selected {
    background-color: #374151;
    border-radius: 4px;
}

/* Checkboxes & Radio Buttons
   The broad `QWidget { background-color }` rule above puts every checkbox/radio
   into stylesheet-drawn mode, which disables the native indicator. Without an
   explicit ::indicator rule the checked/unchecked states render identically, so
   clicking looks like nothing happens. Re-supply a visible indicator here. */
QCheckBox, QRadioButton {
    background-color: transparent;
    color: #e5e7eb;
    spacing: 8px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #6b7280;
    background-color: #2d2d2d;
}
QCheckBox::indicator {
    border-radius: 4px;
}
QRadioButton::indicator {
    border-radius: 11px; /* circular */
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #3b82f6;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #3b82f6;
    border-color: #2563eb;
}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    border-color: #4b5563;
}
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {
    background-color: #3b82f6;
    border-color: #2563eb;
}
QCheckBox:disabled, QRadioButton:disabled {
    color: #9ca3af;
}

/* Labels */
QLabel {
    color: #d1d5db;
}
QLabel#Header {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 10px;
}
"""
