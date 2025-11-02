"""components.py — Helper utilities for UI transitions and effects.

Provides cross-fade animation helpers using QGraphicsOpacityEffect.
"""

from typing import List, Tuple
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect


def fade_widget(widget: QWidget, start: float, end: float, duration: int) -> QPropertyAnimation:
    """Create and start an opacity animation on widget and return the QPropertyAnimation.

    Caller MUST keep a reference to the returned animation while it runs.
    """
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
    anim.start()
    return anim


def cross_fade(current: QWidget, next_w: QWidget, duration: int = 360) -> List[QPropertyAnimation]:
    """Cross-fade between two widgets.

    Returns the list of animations (out, in). Caller should keep them referenced until finished.
    """
    # Ensure both widgets have opacity effects
    if current is not None:
        out = fade_widget(current, 1.0, 0.0, duration)
    else:
        out = None
    inn = fade_widget(next_w, 0.0, 1.0, duration)
    # Return both animations (filter out None)
    return [a for a in (out, inn) if a is not None]
