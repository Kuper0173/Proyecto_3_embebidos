# -*- coding: utf-8 -*-
"""
test_fuzzy.py
=============
Prueba interactiva de la logica difusa del sistema de apnea.
Permite ingresar valores manualmente (sin sensores ni Prolog).

Ejecutar: python test_fuzzy.py
"""

import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import matplotlib.pyplot as plt
import sys

# ─────────────────────────────────────────────────────────────────────────────
# 1. DEFINICION DEL SISTEMA DIFUSO (igual que main_apnea.py)
# ─────────────────────────────────────────────────────────────────────────────
spo2       = ctrl.Antecedent(np.arange(50, 101, 1), 'spo2')
hr         = ctrl.Antecedent(np.arange(30, 151, 1), 'hr')
movimiento = ctrl.Antecedent(np.arange(0, 11, 1),   'movimiento')
riesgo     = ctrl.Consequent(np.arange(0, 101, 1),  'riesgo')

# SpO2
spo2['critico']   = fuzz.trapmf(spo2.universe, [50, 50, 83, 86])
spo2['peligroso'] = fuzz.trimf (spo2.universe, [83, 87, 91])
spo2['moderado']  = fuzz.trimf (spo2.universe, [89, 92, 95])
spo2['normal']    = fuzz.trapmf(spo2.universe, [93, 95, 100, 100])

# HR
hr['bradicardia'] = fuzz.trapmf(hr.universe, [30, 30, 38, 45])
hr['normal']      = fuzz.trapmf(hr.universe, [40, 50, 65, 72])
hr['elevada']     = fuzz.trimf (hr.universe, [68, 80, 92])
hr['taquicardia'] = fuzz.trapmf(hr.universe, [88, 98, 150, 150])

# Movimiento
movimiento['nulo']   = fuzz.trimf(movimiento.universe, [0, 0, 3])
movimiento['leve']   = fuzz.trimf(movimiento.universe, [2, 5, 8])
movimiento['normal'] = fuzz.trimf(movimiento.universe, [7, 10, 10])

# Riesgo (salida)
riesgo['normal']   = fuzz.trapmf(riesgo.universe, [0,  0,  15, 25])
riesgo['leve']     = fuzz.trimf (riesgo.universe, [15, 35, 55])
riesgo['moderado'] = fuzz.trimf (riesgo.universe, [45, 62, 78])
riesgo['critico']  = fuzz.trapmf(riesgo.universe, [70, 85, 100, 100])

# Reglas
rule1  = ctrl.Rule(spo2['normal']    & hr['normal']      & movimiento['nulo'],   riesgo['normal'])
rule2  = ctrl.Rule(spo2['normal']    & hr['normal']      & movimiento['leve'],   riesgo['normal'])
rule3  = ctrl.Rule(spo2['moderado']  & hr['normal'],                             riesgo['leve'])
rule4  = ctrl.Rule(spo2['normal']    & hr['elevada']     & movimiento['leve'],   riesgo['leve'])
rule5  = ctrl.Rule(spo2['moderado']  & movimiento['normal'],                     riesgo['leve'])
rule6  = ctrl.Rule(spo2['peligroso'] & hr['normal'],                             riesgo['moderado'])
rule7  = ctrl.Rule(spo2['moderado']  & hr['bradicardia'],                        riesgo['moderado'])
rule8  = ctrl.Rule(spo2['peligroso'] & hr['elevada']     & movimiento['nulo'],   riesgo['moderado'])
rule9  = ctrl.Rule(spo2['critico'],                                              riesgo['critico'])
rule10 = ctrl.Rule(spo2['peligroso'] & hr['taquicardia'] & movimiento['nulo'],   riesgo['critico'])
rule11 = ctrl.Rule(spo2['peligroso'] & hr['bradicardia'],                        riesgo['critico'])

# Reglas adicionales de cobertura (evitan KeyError en zonas sin activacion)
# Sincronizdas con main_apnea.py rule12-rule17
rule12 = ctrl.Rule(hr['bradicardia'],                                            riesgo['moderado'])
rule13 = ctrl.Rule(hr['taquicardia'] & movimiento['nulo'],                       riesgo['moderado'])
rule14 = ctrl.Rule(hr['taquicardia'] & movimiento['leve'],                       riesgo['leve'])
rule15 = ctrl.Rule(hr['elevada'],                                                riesgo['leve'])
rule16 = ctrl.Rule(spo2['peligroso'],                                            riesgo['moderado'])
rule17 = ctrl.Rule(spo2['normal']    & movimiento['normal'],                     riesgo['leve'])

riesgo_ctrl      = ctrl.ControlSystem([
    rule1, rule2, rule3, rule4, rule5,
    rule6, rule7, rule8, rule9, rule10, rule11,
    rule12, rule13, rule14, rule15, rule16, rule17
])
riesgo_simulador = ctrl.ControlSystemSimulation(riesgo_ctrl)

# ─────────────────────────────────────────────────────────────────────────────
# 2. LOGICA DE ALERTA (replica reglas_apnea.pl en Python)
# ─────────────────────────────────────────────────────────────────────────────
def nivel_a_alerta(nivel):
    if nivel < 25:
        return 'VERDE',     'Paciente estable. No se detectan anomalias respiratorias.'
    elif nivel < 50:
        return 'AMARILLO',  'PRECAUCION: Apnea moderada. Alteracion en SpO2 y HR.'
    elif nivel < 75:
        return 'ROJO',      'PELIGRO: Apnea severa. Patrones anomalos prolongados.'
    else:
        return 'EMERGENCIA','CRITICO: Falla respiratoria aguda. URGENTE AL HOSPITAL.'

# ─────────────────────────────────────────────────────────────────────────────
# 3. GRADO DE MEMBRESÍA DE UN VALOR (para mostrar a qué categoría pertenece)
# ─────────────────────────────────────────────────────────────────────────────
def grados_spo2(v):
    u = spo2.universe
    return {
        'critico':   round(fuzz.interp_membership(u, spo2['critico'].mf,   v), 3),
        'peligroso': round(fuzz.interp_membership(u, spo2['peligroso'].mf, v), 3),
        'moderado':  round(fuzz.interp_membership(u, spo2['moderado'].mf,  v), 3),
        'normal':    round(fuzz.interp_membership(u, spo2['normal'].mf,    v), 3),
    }

def grados_hr(v):
    u = hr.universe
    return {
        'bradicardia': round(fuzz.interp_membership(u, hr['bradicardia'].mf, v), 3),
        'normal':      round(fuzz.interp_membership(u, hr['normal'].mf,      v), 3),
        'elevada':     round(fuzz.interp_membership(u, hr['elevada'].mf,     v), 3),
        'taquicardia': round(fuzz.interp_membership(u, hr['taquicardia'].mf, v), 3),
    }

def grados_mov(v):
    u = movimiento.universe
    return {
        'nulo':   round(fuzz.interp_membership(u, movimiento['nulo'].mf,   v), 3),
        'leve':   round(fuzz.interp_membership(u, movimiento['leve'].mf,   v), 3),
        'normal': round(fuzz.interp_membership(u, movimiento['normal'].mf, v), 3),
    }

# ─────────────────────────────────────────────────────────────────────────────
# 4. BARRA DE PROGRESO VISUAL EN CONSOLA
# ─────────────────────────────────────────────────────────────────────────────
def barra_riesgo(nivel):
    total  = 40
    llenos = int(round(nivel / 100 * total))
    barra  = '#' * llenos + '-' * (total - llenos)
    return f"[{barra}] {nivel:.1f}/100"

# ─────────────────────────────────────────────────────────────────────────────
# 5. GRAFICA DE RESULTADO (muestra el punto evaluado sobre las funciones)
# ─────────────────────────────────────────────────────────────────────────────
def mostrar_grafica(v_spo2, v_hr, v_mov, nivel_riesgo):
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    fig.suptitle(
        f"Resultado difuso | SpO2={v_spo2}%  HR={v_hr}BPM  Mov={v_mov}  ->  Riesgo={nivel_riesgo:.1f}",
        fontsize=12, fontweight='bold'
    )

    colores = {
        'critico':    '#e74c3c',
        'peligroso':  '#e67e22',
        'moderado':   '#f1c40f',
        'normal':     '#2ecc71',
        'bradicardia':'#e74c3c',
        'elevada':    '#f1c40f',
        'taquicardia':'#e67e22',
        'nulo':       '#2ecc71',
        'leve':       '#f1c40f',
    }

    def plot_var(ax, x, mfs, val, titulo, xlabel):
        for nombre, mf in mfs.items():
            c = colores.get(nombre, 'steelblue')
            ax.plot(x, mf, color=c, linewidth=2, label=nombre)
            ax.fill_between(x, 0, mf, facecolor=c, alpha=0.15)
        ax.axvline(x=val, color='black', linewidth=2, linestyle='--', label=f'Valor={val}')
        ax.set_title(titulo, fontsize=10, fontweight='bold')
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel('Membresia', fontsize=9)
        ax.set_ylim(-0.05, 1.2)
        ax.legend(fontsize=7)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, linestyle='--', alpha=0.3)

    # SpO2
    plot_var(axes[0,0], spo2.universe,
             {k: spo2[k].mf for k in ['critico','peligroso','moderado','normal']},
             v_spo2, 'SpO2 (%)', 'SpO2 (%)')

    # HR
    plot_var(axes[0,1], hr.universe,
             {k: hr[k].mf for k in ['bradicardia','normal','elevada','taquicardia']},
             v_hr, 'Frecuencia Cardiaca (BPM)', 'BPM')

    # Movimiento
    plot_var(axes[1,0], movimiento.universe,
             {k: movimiento[k].mf for k in ['nulo','leve','normal']},
             v_mov, 'Movimiento (0-10)', 'Movimiento')

    # Riesgo (salida)
    ax3 = axes[1,1]
    nombres_riesgo = ['normal','leve','moderado','critico']
    cols_riesgo    = ['#2ecc71','#f1c40f','#e67e22','#e74c3c']
    for nombre, c in zip(nombres_riesgo, cols_riesgo):
        ax3.plot(riesgo.universe, riesgo[nombre].mf, color=c, linewidth=2, label=nombre)
        ax3.fill_between(riesgo.universe, 0, riesgo[nombre].mf, facecolor=c, alpha=0.15)
    ax3.axvline(x=nivel_riesgo, color='black', linewidth=2.5, linestyle='--',
                label=f'Resultado={nivel_riesgo:.1f}')
    ax3.set_title('Riesgo — Salida Difusa', fontsize=10, fontweight='bold')
    ax3.set_xlabel('Nivel de Riesgo (0-100)', fontsize=9)
    ax3.set_ylabel('Membresia', fontsize=9)
    ax3.set_ylim(-0.05, 1.2)
    ax3.legend(fontsize=7)
    ax3.spines['top'].set_visible(False)
    ax3.spines['right'].set_visible(False)
    ax3.grid(True, linestyle='--', alpha=0.3)

    plt.tight_layout()
    plt.show()

# ─────────────────────────────────────────────────────────────────────────────
# 6. BUCLE PRINCIPAL DE PRUEBA MANUAL
# ─────────────────────────────────────────────────────────────────────────────
SEPARADOR = "=" * 60

print(SEPARADOR)
print("  PRUEBA MANUAL - LOGICA DIFUSA - DETECCION DE APNEA")
print(SEPARADOR)
print("  Rangos validos:")
print("    SpO2       : 50 - 100 (%)")
print("    HR         : 30 - 150 (BPM)")
print("    Movimiento :  0 - 10")
print("  Escribe 'salir' para terminar.")
print(SEPARADOR)

CASOS_EJEMPLO = [
    ("Caso normal (durmiendo bien)",          97.0, 58.0, 1.0),
    ("Caso leve (desaturacion leve)",          91.5, 62.0, 0.5),
    ("Caso moderado (peligroso + bradicardia)",87.0, 43.0, 0.0),
    ("Caso critico (hipoxia severa)",          80.0, 105.0, 0.0),
]

print("\n  Casos de ejemplo disponibles:")
for i, (desc, s, h, m) in enumerate(CASOS_EJEMPLO, 1):
    print(f"    [{i}] {desc}  (SpO2={s}  HR={h}  Mov={m})")
print("    [0] Ingresar valores manualmente")
print()

while True:
    try:
        opcion = input("Selecciona una opcion (0-4) o 'salir': ").strip().lower()

        if opcion == 'salir':
            print("Saliendo del tester.")
            break

        if opcion in ('1','2','3','4'):
            idx = int(opcion) - 1
            desc, v_spo2, v_hr, v_mov = CASOS_EJEMPLO[idx]
            print(f"\n  >> Usando: {desc}")
        else:
            print()
            v_spo2 = float(input("  Ingresa SpO2 (50-100): "))
            v_hr   = float(input("  Ingresa HR   (30-150): "))
            v_mov  = float(input("  Ingresa Mov  (0-10)  : "))

        # Validaciones
        if not (50 <= v_spo2 <= 100):
            print("  [ERROR] SpO2 fuera de rango (50-100). Intenta de nuevo.\n")
            continue
        if not (30 <= v_hr <= 150):
            print("  [ERROR] HR fuera de rango (30-150). Intenta de nuevo.\n")
            continue
        if not (0 <= v_mov <= 10):
            print("  [ERROR] Movimiento fuera de rango (0-10). Intenta de nuevo.\n")
            continue

        # Fuzzificacion y calculo
        riesgo_simulador.input['spo2']       = v_spo2
        riesgo_simulador.input['hr']         = v_hr
        riesgo_simulador.input['movimiento'] = v_mov
        try:
            riesgo_simulador.compute()
            nivel = riesgo_simulador.output['riesgo']
        except KeyError:
            print("  [ADVERTENCIA] Combinacion de valores fuera de cobertura de reglas.")
            print("  Ninguna regla se activo con suficiente fuerza. Riesgo asumido: 50.0")
            nivel = 50.0

        # Nivel de alerta (replica Prolog)
        color, mensaje = nivel_a_alerta(nivel)

        # Grados de membresía de cada entrada
        g_spo2 = grados_spo2(v_spo2)
        g_hr   = grados_hr(v_hr)
        g_mov  = grados_mov(v_mov)

        # Imprimir resultado
        print()
        print(SEPARADOR)
        print(f"  ENTRADAS:")
        print(f"    SpO2       : {v_spo2}%   -> {g_spo2}")
        print(f"    HR         : {v_hr} BPM  -> {g_hr}")
        print(f"    Movimiento : {v_mov}      -> {g_mov}")
        print()
        print(f"  SALIDA DIFUSA:")
        print(f"    Riesgo     : {barra_riesgo(nivel)}")
        print()
        print(f"  ALERTA [{color}]: {mensaje}")
        print(SEPARADOR)

        # Mostrar grafica
        resp = input("\n  Mostrar grafica? (s/n): ").strip().lower()
        if resp == 's':
            mostrar_grafica(v_spo2, v_hr, v_mov, nivel)

        print()

    except ValueError:
        print("  [ERROR] Ingresa un numero valido.\n")
    except KeyboardInterrupt:
        print("\n  Interrumpido por el usuario.")
        sys.exit(0)
