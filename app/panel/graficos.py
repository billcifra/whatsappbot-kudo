"""Gráficos SVG generados en el servidor (sin JavaScript: compatibles con la CSP del panel).

Una sola serie por gráfico, en un solo color; el título de la tarjeta la nombra (sin leyenda).
Cada barra lleva un <title> que el navegador muestra al pasar el mouse, y una zona de toque más
grande que la barra. Los colores y textos se definen en panel.css (clases g-*).
"""

from __future__ import annotations

import math
from datetime import date

from markupsafe import Markup, escape

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _tope_redondo(maximo: int) -> int:
    """Máximo 'redondo' del eje (1, 2, 5, 10, 20, 50…) mayor o igual al dato."""
    if maximo <= 4:
        return max(maximo, 1)
    base = 10 ** math.floor(math.log10(maximo))
    for paso in (1, 2, 5, 10):
        if paso * base >= maximo:
            return paso * base
    return 10 * base


def _barra_vertical(x: float, base: float, ancho: float, alto: float) -> str:
    """Columna con el extremo de datos redondeado (4px) y cuadrada sobre la línea base."""
    r = min(4.0, ancho / 2, alto)
    y = base - alto
    return (f'<path class="g-barra" d="M{x:.1f},{base:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}'
            f'H{x + ancho - r:.1f}Q{x + ancho:.1f},{y:.1f} {x + ancho:.1f},{y + r:.1f}V{base:.1f}Z"/>')


def _barra_horizontal(x: float, y: float, largo: float, grosor: float) -> str:
    r = min(4.0, grosor / 2, largo)
    return (f'<path class="g-barra" d="M{x:.1f},{y:.1f}H{x + largo - r:.1f}Q{x + largo:.1f},{y:.1f} '
            f'{x + largo:.1f},{y + r:.1f}V{y + grosor - r:.1f}Q{x + largo:.1f},{y + grosor:.1f} '
            f'{x + largo - r:.1f},{y + grosor:.1f}H{x:.1f}Z"/>')


def fecha_corta(d: date) -> str:
    return f"{d.day} {MESES[d.month - 1]}"


def columnas(serie: list[tuple[date, int]], unidad: str, titulo: str) -> Markup:
    """Columnas por día. Etiqueta de valor solo en el máximo y en el último día."""
    if not serie or not any(v for _, v in serie):
        return Markup('<p class="suave">Sin datos en este período.</p>')
    ancho, alto = 480, 190
    izq, der, arriba, abajo = 30, 10, 18, 24
    base = alto - abajo
    area = base - arriba
    tope = _tope_redondo(max(v for _, v in serie))
    ranura = (ancho - izq - der) / len(serie)
    grosor = min(24.0, ranura - 2)
    paso = 7 if len(serie) <= 45 else 14
    i_max = max(range(len(serie)), key=lambda i: (serie[i][1], i))
    partes = [f'<svg class="grafico" viewBox="0 0 {ancho} {alto}" role="img" aria-label="{escape(titulo)}">']
    for valor in sorted({0, tope // 2 if tope % 2 == 0 else 0, tope}):
        y = base - area * valor / tope
        partes.append(f'<line class="g-grilla" x1="{izq}" x2="{ancho - der}" y1="{y:.1f}" y2="{y:.1f}"/>')
        partes.append(f'<text class="g-eje" x="{izq - 6}" y="{y + 4:.1f}" text-anchor="end">{valor}</text>')
    for i, (dia, valor) in enumerate(serie):
        x = izq + i * ranura + (ranura - grosor) / 2
        h = area * valor / tope
        etiqueta = f"{fecha_corta(dia)}: {valor} {unidad}"
        partes.append(f'<g class="g-marca"><title>{escape(etiqueta)}</title>'
                      f'<rect class="g-toque" x="{izq + i * ranura:.1f}" y="{arriba}" width="{ranura:.1f}" height="{area}"/>')
        if valor:
            partes.append(_barra_vertical(x, base, grosor, h))
        if valor and (i == i_max or i == len(serie) - 1):
            partes.append(f'<text class="g-valor" x="{x + grosor / 2:.1f}" y="{base - h - 5:.1f}" '
                          f'text-anchor="middle">{valor}</text>')
        partes.append("</g>")
        # Marcas del eje cada 7 (o 14) días contando desde hoy: el último día siempre tiene etiqueta.
        if (len(serie) - 1 - i) % paso == 0:
            ultimo = i == len(serie) - 1
            partes.append(f'<text class="g-eje" x="{x + (grosor if ultimo else grosor / 2):.1f}" y="{alto - 8}" '
                          f'text-anchor="{"end" if ultimo else "middle"}">{escape(fecha_corta(dia))}</text>')
    partes.append(f'<line class="g-base" x1="{izq}" x2="{ancho - der}" y1="{base}" y2="{base}"/></svg>')
    return Markup("".join(partes))


def barras(items: list[tuple[str, int]], unidad: str, titulo: str) -> Markup:
    """Barras horizontales por categoría, con el valor al final de cada barra."""
    if not items:
        return Markup('<p class="suave">Sin datos todavía.</p>')
    ancho, fila, grosor, etiqueta_ancho, margen_valor = 480, 30, 18, 130, 44
    alto = fila * len(items) + 4
    largo_max = ancho - etiqueta_ancho - margen_valor
    tope = max(v for _, v in items) or 1
    partes = [f'<svg class="grafico grafico-barras" viewBox="0 0 {ancho} {alto}" role="img" '
              f'aria-label="{escape(titulo)}">']
    for i, (nombre, valor) in enumerate(items):
        y = 2 + i * fila + (fila - grosor) / 2
        largo = max(largo_max * valor / tope, 2.0)
        partes.append(f'<g class="g-marca"><title>{escape(f"{nombre}: {valor} {unidad}")}</title>'
                      f'<rect class="g-toque" x="0" y="{2 + i * fila}" width="{ancho}" height="{fila}"/>'
                      f'<text class="g-etiqueta" x="0" y="{y + grosor / 2 + 4:.1f}">{escape(nombre)}</text>'
                      f'{_barra_horizontal(etiqueta_ancho, y, largo, grosor)}'
                      f'<text class="g-valor" x="{etiqueta_ancho + largo + 6:.1f}" y="{y + grosor / 2 + 4:.1f}">'
                      f'{valor}</text></g>')
    partes.append(f'<line class="g-base" x1="{etiqueta_ancho}" x2="{etiqueta_ancho}" y1="0" y2="{alto}"/></svg>')
    return Markup("".join(partes))
