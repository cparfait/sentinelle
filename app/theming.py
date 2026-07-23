"""Couleur principale personnalisable de l'interface.

Comme dans SimCity : une couleur hex stockee en config (UI_PRIMARY_COLOR,
vide = palette d'origine indigo). Quand elle est definie, un bloc <style>
surcharge les variables CSS --primary* (avec une declinaison eclaircie pour
le theme sombre). Selecteurs doublles (:root:root) pour primer sur style.css
quel que soit l'ordre d'inclusion.
"""
import re

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def normalize_color(value):
    """Retourne la couleur hex normalisee ('' si invalide/vide)."""
    value = (value or '').strip()
    return value.lower() if _HEX_RE.match(value) else ''


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def color_mix(hex_color, ratio):
    """Melange avec du blanc (ratio > 0) ou du noir (ratio < 0)."""
    target = 255 if ratio >= 0 else 0
    amount = abs(ratio)
    parts = (round(v + (target - v) * amount) for v in _rgb(hex_color))
    return '#' + ''.join(f'{int(v):02x}' for v in parts)


def primary_css_override(hex_color):
    """Bloc <style> de surcharge des variables primaires ('' si defaut)."""
    c = normalize_color(hex_color)
    if not c:
        return ''
    dark = color_mix(c, -0.22)
    rgb = ','.join(str(v) for v in _rgb(c))
    # Theme sombre : version eclaircie pour rester lisible sur fond fonce.
    l1 = color_mix(c, 0.45)
    l2 = color_mix(c, 0.25)
    lrgb = ','.join(str(v) for v in _rgb(l1))
    # Fond de la page de connexion : degrade sombre derive de la couleur
    # (remplace le bleu nuit d'origine). Injecte apres style.css -> prime.
    login_bg = (f'linear-gradient(135deg,{color_mix(c, -0.85)} 0%,'
                f'{color_mix(c, -0.7)} 55%,{color_mix(c, -0.45)} 100%)')
    return (
        '<style>'
        f':root:root{{--primary:{c};--primary-dark:{dark};--primary-rgb:{rgb};'
        f'--ring:0 0 0 3px rgba({rgb},.35);}}'
        f':root:root[data-theme="dark"]{{--primary:{l1};--primary-dark:{l2};'
        f'--primary-rgb:{lrgb};--ring:0 0 0 3px rgba({lrgb},.35);}}'
        f'.login-container{{background:{login_bg};}}'
        '</style>'
    )


# Couleurs du degrade du logo SVG d'origine (static/img/logo.svg).
_LOGO_COLORS = ('#6366f1', '#3b82f6')


def tinted_logo_svg(svg, hex_color):
    """Recolore le degrade du logo avec la couleur du site (si definie)."""
    c = normalize_color(hex_color)
    if not c:
        return svg
    return svg.replace(_LOGO_COLORS[0], c).replace(_LOGO_COLORS[1], color_mix(c, 0.3))
