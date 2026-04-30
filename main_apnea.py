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

# Funciones de membresía para SpO2 (%)
spo2['peligroso'] = fuzz.trapmf(spo2.universe, [50, 50, 85, 90])
spo2['moderado'] = fuzz.trimf(spo2.universe, [85, 92, 95])
spo2['normal'] = fuzz.trapmf(spo2.universe, [92, 95, 100, 100])

# Funciones de membresía para Frecuencia Cardíaca (BPM)
hr['bajo'] = fuzz.trapmf(hr.universe, [30, 30, 50, 60])
hr['normal'] = fuzz.trapmf(hr.universe, [55, 65, 90, 100])
hr['alto'] = fuzz.trapmf(hr.universe, [95, 110, 150, 150])

# Funciones de membresía para Movimiento
movimiento['nulo'] = fuzz.trimf(movimiento.universe, [0, 0, 3])
movimiento['leve'] = fuzz.trimf(movimiento.universe, [2, 5, 8])
movimiento['normal'] = fuzz.trimf(movimiento.universe, [7, 10, 10])

# Funciones de membresía para el Riesgo
riesgo['bajo'] = fuzz.trimf(riesgo.universe, [0, 0, 35])
riesgo['medio'] = fuzz.trimf(riesgo.universe, [20, 50, 80])
riesgo['alto'] = fuzz.trapmf(riesgo.universe, [65, 85, 100, 100])

# Reglas difusas
rule1 = ctrl.Rule(spo2['normal'] & hr['normal'] & movimiento['normal'], riesgo['bajo'])
rule2 = ctrl.Rule(spo2['moderado'] | hr['bajo'], riesgo['medio'])
rule3 = ctrl.Rule(spo2['peligroso'] & hr['alto'] & movimiento['nulo'], riesgo['alto'])
rule4 = ctrl.Rule(spo2['peligroso'] & movimiento['nulo'], riesgo['alto'])
rule5 = ctrl.Rule(spo2['peligroso'] & hr['bajo'], riesgo['alto'])

riesgo_ctrl = ctrl.ControlSystem([rule1, rule2, rule3, rule4, rule5])
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
        'spo2': np.random.uniform(80, 99),
        'hr': np.random.uniform(45, 110),
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