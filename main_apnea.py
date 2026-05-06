import time
import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
from pyswip import Prolog
import RPi.GPIO as GPIO
import math
from smbus2 import SMBus

# ---------------------------------------------------------
# Constantes de sensores
# ---------------------------------------------------------
I2C_BUS = 1

MAX3010X_ADDRESS = 0x57
MPU6050_DEFAULT_ADDRESS = 0x68


# =========================================================
# REGISTROS MAX30105 / MAX3010X
# =========================================================

REG_INTR_STATUS_1 = 0x00
REG_INTR_STATUS_2 = 0x01
REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C      # RED LED
REG_LED2_PA = 0x0D      # IR LED
REG_PART_ID = 0xFF

EXPECTED_PART_ID = 0x15


# =========================================================
# REGISTROS MPU6050
# =========================================================

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_PWR_MGMT_1 = 0x6B
REG_WHO_AM_I = 0x75

ACCEL_SCALE_2G = 16384.0
GYRO_SCALE_250_DPS = 131.0
G_TO_MS2 = 9.80665

# =========================================================
# CLASE MINIMA PARA MAX30105
# =========================================================

class MAX30105:
    def __init__(self, bus: SMBus, address: int = MAX3010X_ADDRESS):
        self.bus = bus
        self.address = address
        self.inicializar()

    def write_reg(self, reg: int, value: int) -> None:
        self.bus.write_byte_data(self.address, reg, value)

    def read_reg(self, reg: int) -> int:
        return self.bus.read_byte_data(self.address, reg)

    def inicializar(self) -> None:
        part_id = self.read_reg(REG_PART_ID)
        if part_id != EXPECTED_PART_ID:
            raise RuntimeError(f"MAX30105 no detectado. PART_ID=0x{part_id:02X}")

        # Reset
        self.write_reg(REG_MODE_CONFIG, 0x40)
        time.sleep(0.1)

        # Limpiar FIFO
        self.write_reg(REG_FIFO_WR_PTR, 0x00)
        self.write_reg(REG_OVF_COUNTER, 0x00)
        self.write_reg(REG_FIFO_RD_PTR, 0x00)

        # FIFO: promedio 4 muestras, rollover activo
        self.write_reg(REG_FIFO_CONFIG, 0x5F)

        # Modo SpO2: RED + IR
        self.write_reg(REG_MODE_CONFIG, 0x03)

        # ADC range + sample rate + pulse width
        # Configuracion practica para PPG basica
        self.write_reg(REG_SPO2_CONFIG, 0x2F)

        # Corriente de LEDs. Ajustable segun distancia/piel/luz ambiente.
        self.write_reg(REG_LED1_PA, 0x24)  # RED
        self.write_reg(REG_LED2_PA, 0x24)  # IR

        # Limpiar interrupciones
        _ = self.read_reg(REG_INTR_STATUS_1)
        _ = self.read_reg(REG_INTR_STATUS_2)

    def muestras_disponibles(self) -> int:
        wr = self.read_reg(REG_FIFO_WR_PTR) & 0x1F
        rd = self.read_reg(REG_FIFO_RD_PTR) & 0x1F
        return (wr - rd) & 0x1F

    def read_red_ir(self):
        """
        Lee una muestra RED e IR desde FIFO.
        Retorna:
            red, ir
        """

        if self.muestras_disponibles() == 0:
            return None, None

        data = self.bus.read_i2c_block_data(self.address, REG_FIFO_DATA, 6)

        red = ((data[0] << 16) | (data[1] << 8) | data[2]) & 0x03FFFF
        ir = ((data[3] << 16) | (data[4] << 8) | data[5]) & 0x03FFFF

        return float(red), float(ir)


# =========================================================
# CLASE MINIMA PARA MPU6050
# =========================================================

class MPU6050:
    def __init__(self, bus: SMBus, address: int = MPU6050_DEFAULT_ADDRESS):
        self.bus = bus
        self.address = address
        self.inicializar()

    def write_reg(self, reg: int, value: int) -> None:
        self.bus.write_byte_data(self.address, reg, value)

    def read_reg(self, reg: int) -> int:
        return self.bus.read_byte_data(self.address, reg)

    @staticmethod
    def _to_signed(high: int, low: int) -> int:
        value = (high << 8) | low
        return value - 65536 if value & 0x8000 else value

    def inicializar(self) -> None:
        who_am_i = self.read_reg(REG_WHO_AM_I)

        if who_am_i not in (0x68, 0x69, 0x72):
            raise RuntimeError(f"IMU no detectada o no compatible. WHO_AM_I=0x{who_am_i:02X}")

        if who_am_i != 0x68:
            print(
            f"[ADVERTENCIA] IMU detectada en 0x{self.address:02X} "
            f"con WHO_AM_I=0x{who_am_i:02X}. "
            "Se intentara usar como compatible con MPU6050."
        )

    # Despertar MPU/IMU
        self.write_reg(REG_PWR_MGMT_1, 0x00)
        time.sleep(0.1)

    # Filtro digital y tasa de muestreo
        self.write_reg(REG_SMPLRT_DIV, 0x07)
        self.write_reg(REG_CONFIG, 0x03)

    # Acelerometro ±2 g
        self.write_reg(REG_ACCEL_CONFIG, 0x00)

    # Giroscopio ±250 °/s
        self.write_reg(REG_GYRO_CONFIG, 0x00)

        # Despertar MPU6050
        self.write_reg(REG_PWR_MGMT_1, 0x00)
        time.sleep(0.1)

        # Filtro digital y tasa de muestreo
        self.write_reg(REG_SMPLRT_DIV, 0x07)
        self.write_reg(REG_CONFIG, 0x03)

        # Acelerometro ±2 g
        self.write_reg(REG_ACCEL_CONFIG, 0x00)

        # Giroscopio ±250 °/s
        self.write_reg(REG_GYRO_CONFIG, 0x00)

    def read_accel_gyro(self):
        """
        Retorna:
            aceleracion en m/s^2: ax, ay, az
            giroscopio en rad/s: gx, gy, gz
        """

        data = self.bus.read_i2c_block_data(self.address, REG_ACCEL_XOUT_H, 14)

        ax_raw = self._to_signed(data[0], data[1])
        ay_raw = self._to_signed(data[2], data[3])
        az_raw = self._to_signed(data[4], data[5])

        gx_raw = self._to_signed(data[8], data[9])
        gy_raw = self._to_signed(data[10], data[11])
        gz_raw = self._to_signed(data[12], data[13])

        ax = (ax_raw / ACCEL_SCALE_2G) * G_TO_MS2
        ay = (ay_raw / ACCEL_SCALE_2G) * G_TO_MS2
        az = (az_raw / ACCEL_SCALE_2G) * G_TO_MS2

        gx = math.radians(gx_raw / GYRO_SCALE_250_DPS)
        gy = math.radians(gy_raw / GYRO_SCALE_250_DPS)
        gz = math.radians(gz_raw / GYRO_SCALE_250_DPS)

        return (ax, ay, az), (gx, gy, gz)
    
# =========================================================
# INICIALIZACION GLOBAL DE SENSORES
# =========================================================

bus = SMBus(I2C_BUS)
max_sensor = MAX30105(bus)
mpu_sensor = MPU6050(bus)

# =========================================================
# ULTIMA LECTURA VALIDA
# =========================================================

ultima_lectura = {
    'spo2': 95.0,
    'hr': 60.0,
    'movimiento': 0.0
}


# =========================================================
# FUNCIONES DE PROCESAMIENTO
# =========================================================

def estimar_spo2(red_vals, ir_vals):
    """
    Estimacion aproximada de SpO2 usando relacion de razones:
        R = (AC_red / DC_red) / (AC_ir / DC_ir)
        SpO2 ≈ 110 - 25R
    """

    red = np.asarray(red_vals, dtype=float)
    ir = np.asarray(ir_vals, dtype=float)

    red_dc = np.mean(red)
    ir_dc = np.mean(ir)

    if red_dc <= 0 or ir_dc <= 0:
        return None

    red_ac = np.std(red)
    ir_ac = np.std(ir)

    if red_ac < 1e-6 or ir_ac < 1e-6:
        return None

    ratio = (red_ac / red_dc) / (ir_ac / ir_dc)
    spo2 = 110.0 - 25.0 * ratio

    return float(np.clip(spo2, 75, 100))


def estimar_hr(ir_vals, fs):
    """
    Estima HR desde la señal IR mediante deteccion simple de picos.
    """

    ir = np.asarray(ir_vals, dtype=float)
    ir = ir - np.mean(ir)

    if np.std(ir) < 1e-6:
        return None

    umbral = 0.5 * np.std(ir)
    distancia_min = int(0.5 * fs)   # 120 BPM maximo

    picos = []
    ultimo_pico = -distancia_min

    for i in range(1, len(ir) - 1):
        if ir[i] > umbral and ir[i] > ir[i - 1] and ir[i] > ir[i + 1]:
            if i - ultimo_pico >= distancia_min:
                picos.append(i)
                ultimo_pico = i

    if len(picos) < 2:
        return None

    periodos = np.diff(picos) / fs
    periodos = periodos[(periodos >= 0.5) & (periodos <= 2.0)]

    if len(periodos) == 0:
        return None

    hr = 60.0 / np.mean(periodos)

    return float(np.clip(hr, 30, 120))


def estimar_movimiento(acc_vals, gyro_vals):
    """
    Convierte acelerometro y giroscopio en una escala de movimiento 0-10.
    """

    acc = np.asarray(acc_vals, dtype=float)
    gyro = np.asarray(gyro_vals, dtype=float)

    acc_mag = np.linalg.norm(acc, axis=1)
    gyro_mag = np.linalg.norm(gyro, axis=1)

    acc_var = np.std(acc_mag)
    gyro_avg = np.mean(gyro_mag)

    acc_norm = np.clip(acc_var / 3.0, 0, 1)
    gyro_norm = np.clip(gyro_avg / 3.0, 0, 1)

    movimiento = 10.0 * (0.6 * acc_norm + 0.4 * gyro_norm)

    return float(np.clip(movimiento, 0, 10))

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

# Reglas adicionales de cobertura
rule12 = ctrl.Rule(hr['bradicardia'], riesgo['moderado'])
rule13 = ctrl.Rule(hr['taquicardia'] & movimiento['nulo'], riesgo['moderado'])
rule14 = ctrl.Rule(hr['taquicardia'] & movimiento['leve'], riesgo['leve'])
rule15 = ctrl.Rule(hr['elevada'], riesgo['leve'])
rule16 = ctrl.Rule(spo2['peligroso'], riesgo['moderado'])
rule17 = ctrl.Rule(spo2['normal'] & movimiento['normal'], riesgo['leve'])

riesgo_ctrl = ctrl.ControlSystem([
    rule1, rule2, rule3, rule4, rule5,
    rule6, rule7, rule8, rule9, rule10, rule11,
    rule12, rule13, rule14, rule15, rule16, rule17
])
riesgo_simulador = ctrl.ControlSystemSimulation(riesgo_ctrl)

# ---------------------------------------------------------
# 2. CONEXIÓN CON PROLOG (Sistema Experto)
# ---------------------------------------------------------
prolog = Prolog()
prolog.consult("reglas_apnea.pl")

# ---------------------------------------------------------
# 3. RUTINAS DE HARDWARE - Raspberry Pi
# ---------------------------------------------------------

GPIO.setwarnings(False)

# Limpia configuraciones previas de GPIO de este proceso.
# Debe hacerse ANTES de GPIO.setmode().
try:
    GPIO.cleanup()
except Exception:
    pass

# Usamos numeración BCM: GPIO17, GPIO27, GPIO22, GPIO23, etc.
GPIO.setmode(GPIO.BCM)

# LED RGB de cátodo común:
# 1 = canal encendido
# 0 = canal apagado
PINES_LED = {
    'R': 17,
    'G': 27,
    'B': 22
}

# Buzzer de dos pines.
# Cambia a 24 si GPIO23 sigue ocupado.
PIN_BUZZER = 25

for pin in PINES_LED.values():
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)

# =========================================================
# FUNCION PRINCIPAL DE LECTURA DE SENSORES
# =========================================================

def leer_sensores(ventana_s=8, fs=50):
    """
    Lee MAX30105 y MPU6050 durante una ventana temporal.

    Retorna:
        spo2        -> 75 a 100 %
        hr          -> 30 a 120 BPM
        movimiento  -> 0 a 10
    """

    global ultima_lectura

    red_vals = []
    ir_vals = []
    acc_vals = []
    gyro_vals = []

    muestras = int(ventana_s * fs)

    try:
        for _ in range(muestras):
            red, ir = max_sensor.read_red_ir()

            # Filtro basico contra muestras falsas o sin dedo.
            if red is not None and ir is not None:
                if 10000 < red < 262143 and 10000 < ir < 262143:
                    red_vals.append(red)
                    ir_vals.append(ir)

            acc, gyro = mpu_sensor.read_accel_gyro()
            acc_vals.append(acc)
            gyro_vals.append(gyro)

            time.sleep(1.0 / fs)

        # Se exige al menos 3 segundos de muestras validas PPG.
        if len(ir_vals) < 3 * fs:
            raise ValueError("Datos insuficientes del MAX30105")

        spo2 = estimar_spo2(red_vals, ir_vals)
        hr = estimar_hr(ir_vals, fs)
        movimiento = estimar_movimiento(acc_vals, gyro_vals)

        if spo2 is None or hr is None:
            raise ValueError("No fue posible estimar SpO2 o HR")

        lectura = {
            'spo2': float(np.clip(spo2, 75, 100)),
            'hr': float(np.clip(hr, 30, 120)),
            'movimiento': float(np.clip(movimiento, 0, 10))
        }

        ultima_lectura = lectura
        return lectura

    except Exception as error:
        print(f"[ADVERTENCIA] Falla de lectura de sensores: {error}")
        return ultima_lectura

def actualizar_hardware(r, g, b, buzzer):
    """
    Actualiza LED RGB de cátodo común y buzzer activo en alto.
    """

    GPIO.output(PINES_LED['R'], GPIO.HIGH if r else GPIO.LOW)
    GPIO.output(PINES_LED['G'], GPIO.HIGH if g else GPIO.LOW)
    GPIO.output(PINES_LED['B'], GPIO.HIGH if b else GPIO.LOW)
    GPIO.output(PIN_BUZZER, GPIO.HIGH if buzzer else GPIO.LOW)

# ---------------------------------------------------------
# 4. BUCLE PRINCIPAL
# ---------------------------------------------------------
if __name__ == '__main__':
    print("Iniciando Sistema de Detección de Apnea...")

    bus = None

    try:
        bus = SMBus(I2C_BUS)
        max_sensor = MAX30105(bus)
        mpu_sensor = MPU6050(bus)

        while True:
            datos = leer_sensores()

            riesgo_simulador.input['spo2'] = datos['spo2']
            riesgo_simulador.input['hr'] = datos['hr']
            riesgo_simulador.input['movimiento'] = datos['movimiento']
            riesgo_simulador.compute()

            nivel_riesgo = riesgo_simulador.output['riesgo']

            query = f"accion(Color, {nivel_riesgo:.2f}, Mensaje, R, G, B, Buzzer)"
            resultados = list(prolog.query(query))

            if resultados:
                res = resultados[0]

                color = res['Color'].decode('utf-8') if isinstance(res['Color'], bytes) else res['Color']
                mensaje = res['Mensaje'].decode('utf-8') if isinstance(res['Mensaje'], bytes) else res['Mensaje']

                r = int(res['R'])
                g = int(res['G'])
                b = int(res['B'])
                buzzer = int(res['Buzzer'])

                actualizar_hardware(r, g, b, buzzer)

                if color == 'emergencia':
                    print(
                        f"[!] {mensaje} | Riesgo: {nivel_riesgo:.1f} | "
                        f"SpO2: {datos['spo2']:.1f}% | HR: {datos['hr']:.1f} | Buzzer: ON"
                    )
                else:
                    print(
                        f"[{str(color).upper()}] {mensaje} | Riesgo: {nivel_riesgo:.1f} | "
                        f"SpO2: {datos['spo2']:.1f}% | HR: {datos['hr']:.1f} | "
                        f"Mov: {datos['movimiento']:.1f}"
                    )

            riesgo_simulador.reset()
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("Deteniendo sistema...")

    except Exception as error:
        print(f"[ERROR CRITICO] {error}")

    finally:
        try:
            actualizar_hardware(0, 0, 0, 0)
        except Exception:
            pass

        GPIO.cleanup()

        if bus is not None:
            bus.close()