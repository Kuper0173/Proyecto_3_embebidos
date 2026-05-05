# -*- coding: utf-8 -*-
"""
graficas.py
===========
Visualiza las funciones de membresía de la lógica difusa del sistema
de detección de apnea del sueño.

Estilo basado en la fuente: python_fuzzy.py (UNAL - SISTEMAS EMBEBIDOS)
Ejecutar: python graficas.py
"""

import numpy as np
import skfuzzy as fuzz
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ─────────────────────────────────────────────────────────────────────────────
# 1. UNIVERSOS DE DISCURSO (idénticos a main_apnea.py)
# ─────────────────────────────────────────────────────────────────────────────
x_spo2       = np.arange(50, 101, 1)   # SpO2 (%)
x_hr         = np.arange(30, 151, 1)   # Frecuencia Cardíaca (BPM)
x_movimiento = np.arange(0, 11, 1)     # Movimiento (escala 0-10)
x_riesgo     = np.arange(0, 101, 1)    # Riesgo (salida, 0-100)

# ─────────────────────────────────────────────────────────────────────────────
# 2. FUNCIONES DE MEMBRESÍA
# ─────────────────────────────────────────────────────────────────────────────

# SpO2 (%)
spo2_critico   = fuzz.trapmf(x_spo2, [50, 50, 83, 86])
spo2_peligroso = fuzz.trimf (x_spo2, [83, 87, 91])
spo2_moderado  = fuzz.trimf (x_spo2, [89, 92, 95])
spo2_normal    = fuzz.trapmf(x_spo2, [93, 95, 100, 100])

# Frecuencia Cardíaca (BPM)
hr_bradicardia = fuzz.trapmf(x_hr, [30, 30, 38, 45])
hr_normal      = fuzz.trapmf(x_hr, [40, 50, 65, 72])
hr_elevada     = fuzz.trimf (x_hr, [68, 80, 92])
hr_taquicardia = fuzz.trapmf(x_hr, [88, 98, 150, 150])

# Movimiento
mov_nulo   = fuzz.trimf(x_movimiento, [0, 0, 3])
mov_leve   = fuzz.trimf(x_movimiento, [2, 5, 8])
mov_normal = fuzz.trimf(x_movimiento, [7, 10, 10])

# Riesgo (salida)
riesgo_normal   = fuzz.trapmf(x_riesgo, [0,  0,  15, 25])
riesgo_leve     = fuzz.trimf (x_riesgo, [15, 35, 55])
riesgo_moderado = fuzz.trimf (x_riesgo, [45, 62, 78])
riesgo_critico  = fuzz.trapmf(x_riesgo, [70, 85, 100, 100])

# ─────────────────────────────────────────────────────────────────────────────
# 3. COLORES (paleta consistente por nivel)
# ─────────────────────────────────────────────────────────────────────────────
COLOR_NORMAL    = '#2ecc71'   # verde
COLOR_LEVE      = '#f1c40f'   # amarillo
COLOR_MODERADO  = '#e67e22'   # naranja
COLOR_CRITICO   = '#e74c3c'   # rojo

# ─────────────────────────────────────────────────────────────────────────────
# 4. FUNCIÓN AUXILIAR: quitar ejes superior y derecho (estilo fuente)
# ─────────────────────────────────────────────────────────────────────────────
def estilo_ax(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.get_xaxis().tick_bottom()
    ax.get_yaxis().tick_left()
    ax.set_ylim(-0.05, 1.15)
    ax.set_ylabel('Membresía μ(x)', fontsize=9)
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, linestyle='--', alpha=0.35)

# ─────────────────────────────────────────────────────────────────────────────
# 5. FIGURA PRINCIPAL — 4 subgráficas (una por variable)
# ─────────────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(12, 11))
fig.suptitle(
    'Sistema de Detección de Apnea del Sueño\nFunciones de Membresía — Lógica Difusa',
    fontsize=14, fontweight='bold', y=0.98
)

gs = gridspec.GridSpec(4, 1, hspace=0.55)

# ── 5.1 SpO2 ──────────────────────────────────────────────────────────────────
ax0 = fig.add_subplot(gs[0])
ax0.fill_between(x_spo2, 0, spo2_critico,   facecolor=COLOR_CRITICO,   alpha=0.25)
ax0.fill_between(x_spo2, 0, spo2_peligroso, facecolor=COLOR_MODERADO,  alpha=0.25)
ax0.fill_between(x_spo2, 0, spo2_moderado,  facecolor=COLOR_LEVE,      alpha=0.25)
ax0.fill_between(x_spo2, 0, spo2_normal,    facecolor=COLOR_NORMAL,    alpha=0.25)

ax0.plot(x_spo2, spo2_critico,   color=COLOR_CRITICO,  linewidth=2, label='Crítico   (< 85%)')
ax0.plot(x_spo2, spo2_peligroso, color=COLOR_MODERADO, linewidth=2, label='Peligroso (85–90%)')
ax0.plot(x_spo2, spo2_moderado,  color=COLOR_LEVE,     linewidth=2, label='Moderado  (90–94%)')
ax0.plot(x_spo2, spo2_normal,    color=COLOR_NORMAL,   linewidth=2, label='Normal    (≥ 95%)')

ax0.set_title('SpO₂ — Saturación de Oxígeno (%)', fontsize=11, fontweight='bold')
ax0.set_xlabel('SpO₂ (%)', fontsize=9)
ax0.set_xlim(50, 100)
estilo_ax(ax0)

# Anotaciones de umbrales clínicos
for x_val, label in [(85, '85%'), (90, '90%'), (95, '95%')]:
    ax0.axvline(x=x_val, color='gray', linewidth=0.8, linestyle=':')
    ax0.text(x_val + 0.3, 1.05, label, fontsize=7, color='gray')

# ── 5.2 Frecuencia Cardíaca ────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[1])
ax1.fill_between(x_hr, 0, hr_bradicardia, facecolor=COLOR_CRITICO,  alpha=0.25)
ax1.fill_between(x_hr, 0, hr_normal,      facecolor=COLOR_NORMAL,   alpha=0.25)
ax1.fill_between(x_hr, 0, hr_elevada,     facecolor=COLOR_LEVE,     alpha=0.25)
ax1.fill_between(x_hr, 0, hr_taquicardia, facecolor=COLOR_MODERADO, alpha=0.25)

ax1.plot(x_hr, hr_bradicardia, color=COLOR_CRITICO,  linewidth=2, label='Bradicardia (< 40 BPM)')
ax1.plot(x_hr, hr_normal,      color=COLOR_NORMAL,   linewidth=2, label='Normal      (40–70 BPM)')
ax1.plot(x_hr, hr_elevada,     color=COLOR_LEVE,     linewidth=2, label='Elevada     (70–90 BPM)')
ax1.plot(x_hr, hr_taquicardia, color=COLOR_MODERADO, linewidth=2, label='Taquicardia (> 88 BPM)')

ax1.set_title('Frecuencia Cardíaca (BPM) — contexto sueño', fontsize=11, fontweight='bold')
ax1.set_xlabel('Frecuencia Cardíaca (BPM)', fontsize=9)
ax1.set_xlim(30, 150)
estilo_ax(ax1)

for x_val, label in [(40, '40'), (70, '70'), (88, '88')]:
    ax1.axvline(x=x_val, color='gray', linewidth=0.8, linestyle=':')
    ax1.text(x_val + 0.5, 1.05, f'{label} BPM', fontsize=7, color='gray')

# ── 5.3 Movimiento ────────────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[2])
ax2.fill_between(x_movimiento, 0, mov_nulo,   facecolor=COLOR_NORMAL,   alpha=0.25)
ax2.fill_between(x_movimiento, 0, mov_leve,   facecolor=COLOR_LEVE,     alpha=0.25)
ax2.fill_between(x_movimiento, 0, mov_normal, facecolor=COLOR_MODERADO, alpha=0.25)

ax2.plot(x_movimiento, mov_nulo,   color=COLOR_NORMAL,   linewidth=2, label='Nulo   (0–3)')
ax2.plot(x_movimiento, mov_leve,   color=COLOR_LEVE,     linewidth=2, label='Leve   (2–8)')
ax2.plot(x_movimiento, mov_normal, color=COLOR_MODERADO, linewidth=2, label='Normal (7–10)')

ax2.set_title('Movimiento Corporal (escala 0–10)', fontsize=11, fontweight='bold')
ax2.set_xlabel('Movimiento', fontsize=9)
ax2.set_xlim(0, 10)
estilo_ax(ax2)

# ── 5.4 Riesgo (salida / Consequent) ─────────────────────────────────────────
ax3 = fig.add_subplot(gs[3])
ax3.fill_between(x_riesgo, 0, riesgo_normal,   facecolor=COLOR_NORMAL,   alpha=0.25)
ax3.fill_between(x_riesgo, 0, riesgo_leve,     facecolor=COLOR_LEVE,     alpha=0.25)
ax3.fill_between(x_riesgo, 0, riesgo_moderado, facecolor=COLOR_MODERADO, alpha=0.25)
ax3.fill_between(x_riesgo, 0, riesgo_critico,  facecolor=COLOR_CRITICO,  alpha=0.25)

ax3.plot(x_riesgo, riesgo_normal,   color=COLOR_NORMAL,   linewidth=2, label='Normal   (0–25)')
ax3.plot(x_riesgo, riesgo_leve,     color=COLOR_LEVE,     linewidth=2, label='Leve     (15–55)')
ax3.plot(x_riesgo, riesgo_moderado, color=COLOR_MODERADO, linewidth=2, label='Moderado (45–78)')
ax3.plot(x_riesgo, riesgo_critico,  color=COLOR_CRITICO,  linewidth=2, label='Crítico  (70–100)')

ax3.set_title('Riesgo de Apnea — Variable de Salida (0–100)', fontsize=11, fontweight='bold')
ax3.set_xlabel('Nivel de Riesgo', fontsize=9)
ax3.set_xlim(0, 100)
estilo_ax(ax3)

for x_val, label in [(25, '25'), (55, '55'), (70, '70')]:
    ax3.axvline(x=x_val, color='gray', linewidth=0.8, linestyle=':')
    ax3.text(x_val + 0.5, 1.05, label, fontsize=7, color='gray')

# ─────────────────────────────────────────────────────────────────────────────
# 6. GUARDAR Y MOSTRAR
# ─────────────────────────────────────────────────────────────────────────────
plt.savefig('graficas_fuzzy_apnea.png', dpi=150, bbox_inches='tight')
print("[OK] Grafica guardada como: graficas_fuzzy_apnea.png")
plt.show()
