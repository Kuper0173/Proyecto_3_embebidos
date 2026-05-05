import time
import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
from pyswip import Prolog

# ---------------------------------------------------------
# 1. DEFINICIÓN DEL MOTOR DE LÓGICA DIFUSA (skfuzzy)
# ---------------------------------------------------------
# Universos de discurso
spo2 = ctrl.Antecedent(np.arange(50, 101, 1), 'spo2')
hr = ctrl.Antecedent(np.arange(30, 151, 1), 'hr')
movimiento = ctrl.Antecedent(np.arange(0, 11, 1), 'movimiento')

riesgo = ctrl.Consequent(np.arange(0, 101, 1), 'riesgo')

# ── SpO2 (%) ────────────────────────────────────────────────────────────────
# Referencia clínica durante el sueño:
#   critico   : < 85%  → hipoxia severa, emergencia inmediata
#   peligroso : 85–90% → desaturación moderada (apnea significativa)
#   moderado  : 90–94% → desaturación leve (apnea leve / hipopnea)
#   normal    : ≥ 95%  → saturación saludable
spo2['critico']   = fuzz.trapmf(spo2.universe, [50, 50, 83, 86])
spo2['peligroso'] = fuzz.trimf (spo2.universe, [83, 87, 91])
spo2['moderado']  = fuzz.trimf (spo2.universe, [89, 92, 95])
spo2['normal']    = fuzz.trapmf(spo2.universe, [93, 95, 100, 100])

# ── Frecuencia Cardíaca (BPM) ────────────────────────────────────────────────
# Referencia clínica durante el sueño:
#   bradicardia : < 40 BPM  → peligroso (bloqueo o hipoxia profunda)
#   normal      : 40–70 BPM → fisiológico en sueño (incluso en atletas)
#   elevada     : 70–90 BPM → posible arousal o estrés respiratorio
#   taquicardia : > 88 BPM  → respuesta simpática a apnea
hr['bradicardia'] = fuzz.trapmf(hr.universe, [30, 30, 38, 45])
hr['normal']      = fuzz.trapmf(hr.universe, [40, 50, 65, 72])
hr['elevada']     = fuzz.trimf (hr.universe, [68, 80, 92])
hr['taquicardia'] = fuzz.trapmf(hr.universe, [88, 98, 150, 150])

# ── Movimiento ───────────────────────────────────────────────────────────────
# Escala 0-10 (0 = sin movimiento, 10 = movimiento intenso)
# Durante sueño normal el movimiento es mínimo; agitación indica despertar o apnea
movimiento['nulo']   = fuzz.trimf(movimiento.universe, [0, 0, 3])
movimiento['leve']   = fuzz.trimf(movimiento.universe, [2, 5, 8])
movimiento['normal'] = fuzz.trimf(movimiento.universe, [7, 10, 10])

# ── Riesgo (salida) — 4 niveles de alerta ────────────────────────────────────
#   normal   : 0–25   → sin eventos detectados
#   leve     : 15–55  → hipopnea o desaturación leve
#   moderado : 45–80  → apnea moderada, requiere atención
#   critico  : 70–100 → apnea severa / emergencia
riesgo['normal']   = fuzz.trapmf(riesgo.universe, [0,  0,  15, 25])
riesgo['leve']     = fuzz.trimf (riesgo.universe, [15, 35, 55])
riesgo['moderado'] = fuzz.trimf (riesgo.universe, [45, 62, 78])
riesgo['critico']  = fuzz.trapmf(riesgo.universe, [70, 85, 100, 100])

# ── Reglas difusas (10 reglas para cubrir los 4 niveles) ─────────────────────
# Nivel NORMAL — todo dentro de rangos de sueño saludable
rule1 = ctrl.Rule(spo2['normal']    & hr['normal']      & movimiento['nulo'],   riesgo['normal'])
rule2 = ctrl.Rule(spo2['normal']    & hr['normal']      & movimiento['leve'],   riesgo['normal'])

# Nivel LEVE — desaturación leve o HR ligeramente elevada
rule3 = ctrl.Rule(spo2['moderado']  & hr['normal'],                             riesgo['leve'])
rule4 = ctrl.Rule(spo2['normal']    & hr['elevada']     & movimiento['leve'],   riesgo['leve'])
rule5 = ctrl.Rule(spo2['moderado']  & movimiento['normal'],                     riesgo['leve'])

# Nivel MODERADO — desaturación significativa o bradicardia
rule6 = ctrl.Rule(spo2['peligroso'] & hr['normal'],                             riesgo['moderado'])
rule7 = ctrl.Rule(spo2['moderado']  & hr['bradicardia'],                        riesgo['moderado'])
rule8 = ctrl.Rule(spo2['peligroso'] & hr['elevada']     & movimiento['nulo'],   riesgo['moderado'])

# Nivel CRÍTICO — hipoxia severa, taquicardia refleja o bradicardia extrema
rule9  = ctrl.Rule(spo2['critico'],                                              riesgo['critico'])
rule10 = ctrl.Rule(spo2['peligroso'] & hr['taquicardia'] & movimiento['nulo'],  riesgo['critico'])
rule11 = ctrl.Rule(spo2['peligroso'] & hr['bradicardia'],                       riesgo['critico'])

riesgo_ctrl = ctrl.ControlSystem([
    rule1, rule2, rule3, rule4, rule5,
    rule6, rule7, rule8, rule9, rule10, rule11
])
riesgo_simulador = ctrl.ControlSystemSimulation(riesgo_ctrl)

# ---------------------------------------------------------
# 2. CONEXIÓN CON PROLOG (Sistema Experto)
# ---------------------------------------------------------
prolog = Prolog()
prolog.consult("reglas_apnea.pl")

# ---------------------------------------------------------
# 3. RUTINAS DE HARDWARE (Mocks / Setup Raspberry Pi)
# ---------------------------------------------------------
# Descomentar en entorno real de RPi
# import RPi.GPIO as GPIO
# GPIO.setwarnings(False)
# GPIO.setmode(GPIO.BCM)
# PINES_LED = {'R': 17, 'G': 27, 'B': 22}
# PIN_BUZZER = 23
# for pin in PINES_LED.values():
#     GPIO.setup(pin, GPIO.OUT)
# GPIO.setup(PIN_BUZZER, GPIO.OUT)

def leer_sensores():
    # Retorna datos de los sensores I2C. Para el desarrollo se usan datos simulados.
    return {
        'spo2':       np.random.uniform(75, 100),  # Rango realista incluyendo desaturaciones
        'hr':         np.random.uniform(30, 120),   # Rango realista sueño: bradicardia a taquicardia
        'movimiento': np.random.uniform(0, 10)
    }

def actualizar_hardware(r, g, b, buzzer):
    # Lógica física de encendido
    # GPIO.output(PINES_LED['R'], r)
    # GPIO.output(PINES_LED['G'], g)
    # GPIO.output(PINES_LED['B'], b)
    # GPIO.output(PIN_BUZZER, buzzer)
    pass

# ---------------------------------------------------------
# 4. BUCLE PRINCIPAL
# ---------------------------------------------------------
if __name__ == '__main__':
    print("Iniciando Sistema de Detección de Apnea...")
    try:
        while True:
            datos = leer_sensores()
            
            # Evaluar el riesgo con el simulador difuso
            riesgo_simulador.input['spo2'] = datos['spo2']
            riesgo_simulador.input['hr'] = datos['hr']
            riesgo_simulador.input['movimiento'] = datos['movimiento']
            riesgo_simulador.compute()
            
            nivel_riesgo = riesgo_simulador.output['riesgo']
            
            # Consulta a la base de hechos en Prolog
            query = f"accion(Color, {nivel_riesgo}, Mensaje, R, G, B, Buzzer)"
            resultados = list(prolog.query(query))
            
            if resultados:
                res = resultados[0]
                color = res['Color'].decode('utf-8') if isinstance(res['Color'], bytes) else res['Color']
                mensaje = res['Mensaje'].decode('utf-8') if isinstance(res['Mensaje'], bytes) else res['Mensaje']
                r, g, b = res['R'], res['G'], res['B']
                buzzer = res['Buzzer']
                
                actualizar_hardware(r, g, b, buzzer)
                
                # Consola iterativa
                if color == 'emergencia':
                    print(f"[!] {mensaje} | Riesgo: {nivel_riesgo:.1f} | SpO2: {datos['spo2']:.1f}% | HR: {datos['hr']:.1f} | Buzzer: ON")
                else:
                    print(f"[{color.upper()}] {mensaje} | Riesgo: {nivel_riesgo:.1f}")
                    
            # Control de muestreo (clk interno)
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        print("Deteniendo sistema...")
        # GPIO.cleanup()