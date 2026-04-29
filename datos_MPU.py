#!/usr/bin/env python3
"""
datos_MPU.py

Lectura y procesamiento básico del MPU6050 usando Raspberry Pi Zero 2 W.

Este programa:
1. Lee acelerómetro y giroscopio por I2C.
2. Calcula acc_mag.
3. Calcula gyro_mag.
4. Detecta movimiento.
5. Estima una etiqueta de postura/orientación del sensor.
6. Determina si la ventana temporal reciente es estable.
7. Muestra los resultados en consola.

Salidas principales:
- acc_mag: magnitud de aceleración en g.
- gyro_mag: magnitud de velocidad angular en grados/s.
- motion_detected: indica si hubo movimiento relevante.
- posture_label: orientación dominante del sensor.
- stable_window: indica si la ventana reciente fue estable.

Nota:
La postura depende de cómo pegues físicamente el MPU6050 al cuerpo.
Por ahora se etiqueta la orientación del sensor, no una postura médica definitiva.
"""

from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List

from smbus2 import SMBus


# ============================================================
# Dirección I2C y registros del MPU6050
# ============================================================

MPU6050_DEFAULT_ADDRESS = 0x68

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_PWR_MGMT_1 = 0x6B
REG_WHO_AM_I = 0x75


# ============================================================
# Escalas físicas usadas
# ============================================================

# Configuración del acelerómetro: ±2 g
ACCEL_SCALE_2G = 16384.0

# Configuración del giroscopio: ±250 °/s
GYRO_SCALE_250_DPS = 131.0


# ============================================================
# Parámetros por defecto del procesamiento
# ============================================================

DEFAULT_SAMPLE_RATE_HZ = 50.0
DEFAULT_WINDOW_SECONDS = 3.0

DEFAULT_ACC_THRESHOLD_G = 0.10
DEFAULT_GYRO_THRESHOLD_DPS = 15.0

DEFAULT_STABLE_RATIO = 0.85


@dataclass
class MPU6050Sample:
    """Muestra física del MPU6050."""

    ax_g: float
    ay_g: float
    az_g: float
    gx_dps: float
    gy_dps: float
    gz_dps: float
    temp_c: float


@dataclass
class ProcessedMPUData:
    """Datos procesados del MPU6050."""

    acc_mag: float
    gyro_mag: float
    motion_detected: bool
    posture_label: str
    stable_window: bool


def combine_signed_16(msb: int, lsb: int) -> int:
    """
    Combina dos bytes en un entero de 16 bits con signo.

    El MPU6050 entrega cada medición como:
    - byte alto
    - byte bajo

    El valor resultante está en complemento a dos.
    """

    value = (msb << 8) | lsb

    if value & 0x8000:
        value -= 0x10000

    return value


class MPU6050:
    """
    Driver mínimo para el MPU6050.

    Esta clase solo se encarga de:
    - inicializar el sensor,
    - leer registros,
    - convertir datos crudos a unidades físicas.

    No decide si hay movimiento ni si la ventana es estable.
    Esa lógica está en MPUDataProcessor.
    """

    def __init__(self, bus: SMBus, address: int = MPU6050_DEFAULT_ADDRESS) -> None:
        self.bus = bus
        self.address = address

    def write_register(self, register: int, value: int) -> None:
        """Escribe un byte en un registro del MPU6050."""
        self.bus.write_byte_data(self.address, register, value)

    def read_register(self, register: int) -> int:
        """Lee un byte desde un registro del MPU6050."""
        return self.bus.read_byte_data(self.address, register)

    def read_block(self, start_register: int, length: int) -> List[int]:
        """Lee varios bytes consecutivos desde el MPU6050."""
        return self.bus.read_i2c_block_data(self.address, start_register, length)

    def check_identity(self) -> int:
        """
        Lee WHO_AM_I.

        En un MPU6050 típico debe devolver 0x68.
        """
        return self.read_register(REG_WHO_AM_I)

    def initialize(self, sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ) -> None:
        """
        Inicializa el MPU6050.

        Configuración:
        - Acelerómetro: ±2 g.
        - Giroscopio: ±250 °/s.
        - Filtro digital pasa-bajas activado.
        - Frecuencia de muestreo aproximada configurable.
        """

        # Reset del dispositivo.
        self.write_register(REG_PWR_MGMT_1, 0x80)
        time.sleep(0.100)

        # Despertar sensor y usar reloj basado en giroscopio X.
        self.write_register(REG_PWR_MGMT_1, 0x01)
        time.sleep(0.100)

        # Filtro digital pasa-bajas.
        self.write_register(REG_CONFIG, 0x03)

        # Con DLPF activo, la base interna aproximada es 1 kHz.
        # sample_rate = 1000 / (1 + SMPLRT_DIV)
        divider = int((1000.0 / sample_rate_hz) - 1)

        if divider < 0:
            divider = 0

        if divider > 255:
            divider = 255

        self.write_register(REG_SMPLRT_DIV, divider)

        # Giroscopio ±250 °/s.
        self.write_register(REG_GYRO_CONFIG, 0x00)

        # Acelerómetro ±2 g.
        self.write_register(REG_ACCEL_CONFIG, 0x00)

        time.sleep(0.100)

    def read_sample(self) -> MPU6050Sample:
        """
        Lee una muestra completa del MPU6050.

        Desde ACCEL_XOUT_H se leen 14 bytes:
        - aceleración X, Y, Z,
        - temperatura,
        - giroscopio X, Y, Z.
        """

        data = self.read_block(REG_ACCEL_XOUT_H, 14)

        ax_raw = combine_signed_16(data[0], data[1])
        ay_raw = combine_signed_16(data[2], data[3])
        az_raw = combine_signed_16(data[4], data[5])

        temp_raw = combine_signed_16(data[6], data[7])

        gx_raw = combine_signed_16(data[8], data[9])
        gy_raw = combine_signed_16(data[10], data[11])
        gz_raw = combine_signed_16(data[12], data[13])

        ax_g = ax_raw / ACCEL_SCALE_2G
        ay_g = ay_raw / ACCEL_SCALE_2G
        az_g = az_raw / ACCEL_SCALE_2G

        gx_dps = gx_raw / GYRO_SCALE_250_DPS
        gy_dps = gy_raw / GYRO_SCALE_250_DPS
        gz_dps = gz_raw / GYRO_SCALE_250_DPS

        temp_c = (temp_raw / 340.0) + 36.53

        return MPU6050Sample(
            ax_g=ax_g,
            ay_g=ay_g,
            az_g=az_g,
            gx_dps=gx_dps,
            gy_dps=gy_dps,
            gz_dps=gz_dps,
            temp_c=temp_c,
        )


class MPUDataProcessor:
    """
    Procesador de datos del MPU6050.

    Calcula:
    - acc_mag,
    - gyro_mag,
    - motion_detected,
    - posture_label,
    - stable_window.
    """

    def __init__(
        self,
        sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        acc_threshold_g: float = DEFAULT_ACC_THRESHOLD_G,
        gyro_threshold_dps: float = DEFAULT_GYRO_THRESHOLD_DPS,
        stable_ratio: float = DEFAULT_STABLE_RATIO,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.window_seconds = window_seconds

        self.acc_threshold_g = acc_threshold_g
        self.gyro_threshold_dps = gyro_threshold_dps
        self.stable_ratio = stable_ratio

        window_size = int(sample_rate_hz * window_seconds)

        self.acc_mag_window: Deque[float] = deque(maxlen=window_size)
        self.gyro_mag_window: Deque[float] = deque(maxlen=window_size)
        self.motion_window: Deque[bool] = deque(maxlen=window_size)

        # Offset del giroscopio.
        # Se calcula durante la calibración inicial.
        self.gx_offset = 0.0
        self.gy_offset = 0.0
        self.gz_offset = 0.0

        # Magnitud de aceleración de referencia cuando el sensor está quieto.
        # Normalmente debería ser cercana a 1 g.
        self.baseline_acc_mag = 1.0

    @staticmethod
    def vector_magnitude(x: float, y: float, z: float) -> float:
        """Calcula la magnitud euclidiana de un vector 3D."""
        return math.sqrt((x * x) + (y * y) + (z * z))

    def calibrate(
        self,
        sensor: MPU6050,
        calibration_samples: int = 100,
        delay_s: float = 0.02,
    ) -> None:
        """
        Calibra el giroscopio y la magnitud de aceleración base.

        Durante esta etapa el sensor debe estar quieto.

        El acelerómetro no se centra en cero, porque necesitamos conservar
        la gravedad para estimar orientación/postura.
        """

        gx_values: List[float] = []
        gy_values: List[float] = []
        gz_values: List[float] = []
        acc_mag_values: List[float] = []

        for _ in range(calibration_samples):
            sample = sensor.read_sample()

            gx_values.append(sample.gx_dps)
            gy_values.append(sample.gy_dps)
            gz_values.append(sample.gz_dps)

            acc_mag = self.vector_magnitude(
                sample.ax_g,
                sample.ay_g,
                sample.az_g,
            )

            acc_mag_values.append(acc_mag)

            time.sleep(delay_s)

        self.gx_offset = sum(gx_values) / len(gx_values)
        self.gy_offset = sum(gy_values) / len(gy_values)
        self.gz_offset = sum(gz_values) / len(gz_values)

        self.baseline_acc_mag = sum(acc_mag_values) / len(acc_mag_values)

    def classify_posture(self, ax_g: float, ay_g: float, az_g: float) -> str:
        """
        Clasifica la orientación dominante del sensor.

        Esta etiqueta depende de cómo montes el MPU6050 en el cuerpo.
        Por eso se reporta como orientación del sensor:

        - SENSOR_X_POS
        - SENSOR_X_NEG
        - SENSOR_Y_POS
        - SENSOR_Y_NEG
        - SENSOR_Z_POS
        - SENSOR_Z_NEG

        Luego, en main.py, puedes mapear estas etiquetas a:
        - boca arriba,
        - boca abajo,
        - lateral,
        - sentado,
        según la posición física real del sensor.
        """

        abs_x = abs(ax_g)
        abs_y = abs(ay_g)
        abs_z = abs(az_g)

        acc_mag = self.vector_magnitude(ax_g, ay_g, az_g)

        if acc_mag < 0.3:
            return "ORIENTACION_DESCONOCIDA"

        # Si ningún eje domina claramente, probablemente está inclinado.
        dominant_value = max(abs_x, abs_y, abs_z)
        dominance_ratio = dominant_value / acc_mag

        if dominance_ratio < 0.70:
            return "INCLINADO_MIXTO"

        if dominant_value == abs_x:
            return "SENSOR_X_POS" if ax_g >= 0 else "SENSOR_X_NEG"

        if dominant_value == abs_y:
            return "SENSOR_Y_POS" if ay_g >= 0 else "SENSOR_Y_NEG"

        return "SENSOR_Z_POS" if az_g >= 0 else "SENSOR_Z_NEG"

    def is_stable_window(self) -> bool:
        """
        Determina si la ventana temporal reciente fue estable.

        Criterios:
        - La mayoría de muestras no tuvo movimiento.
        - La desviación estándar de acc_mag no es excesiva.
        - El promedio de gyro_mag es bajo.
        """

        if len(self.motion_window) < self.motion_window.maxlen:
            return False

        total_samples = len(self.motion_window)
        stable_samples = sum(1 for motion in self.motion_window if not motion)

        stable_ratio = stable_samples / total_samples

        acc_values = list(self.acc_mag_window)
        gyro_values = list(self.gyro_mag_window)

        try:
            acc_std = statistics.stdev(acc_values)
        except statistics.StatisticsError:
            acc_std = 999.0

        gyro_avg = sum(gyro_values) / len(gyro_values)

        enough_stable_samples = stable_ratio >= self.stable_ratio
        low_acc_variation = acc_std < self.acc_threshold_g
        low_gyro_average = gyro_avg < (0.5 * self.gyro_threshold_dps)

        return enough_stable_samples and low_acc_variation and low_gyro_average

    def process_sample(self, sample: MPU6050Sample) -> ProcessedMPUData:
        """
        Procesa una muestra del MPU6050 y devuelve las variables principales.
        """

        # Magnitud de aceleración total.
        acc_mag = self.vector_magnitude(
            sample.ax_g,
            sample.ay_g,
            sample.az_g,
        )

        # Giroscopio corregido con offset.
        gx_corrected = sample.gx_dps - self.gx_offset
        gy_corrected = sample.gy_dps - self.gy_offset
        gz_corrected = sample.gz_dps - self.gz_offset

        gyro_mag = self.vector_magnitude(
            gx_corrected,
            gy_corrected,
            gz_corrected,
        )

        # Variación de aceleración respecto a la referencia quieta.
        acc_variation = abs(acc_mag - self.baseline_acc_mag)

        # Detección instantánea de movimiento.
        motion_detected = (
            acc_variation > self.acc_threshold_g
            or gyro_mag > self.gyro_threshold_dps
        )

        posture_label = self.classify_posture(
            sample.ax_g,
            sample.ay_g,
            sample.az_g,
        )

        self.acc_mag_window.append(acc_mag)
        self.gyro_mag_window.append(gyro_mag)
        self.motion_window.append(motion_detected)

        stable_window = self.is_stable_window()

        return ProcessedMPUData(
            acc_mag=acc_mag,
            gyro_mag=gyro_mag,
            motion_detected=motion_detected,
            posture_label=posture_label,
            stable_window=stable_window,
        )


def parse_arguments() -> argparse.Namespace:
    """Procesa argumentos de línea de comandos."""

    parser = argparse.ArgumentParser(
        description="Procesamiento del MPU6050: acc_mag, gyro_mag, movimiento, postura y estabilidad."
    )

    parser.add_argument(
        "--bus",
        type=int,
        default=1,
        help="Bus I2C. En Raspberry Pi normalmente es 1.",
    )

    parser.add_argument(
        "--address",
        type=lambda value: int(value, 0),
        default=MPU6050_DEFAULT_ADDRESS,
        help="Dirección I2C del MPU6050. Normalmente 0x68 o 0x69.",
    )

    parser.add_argument(
        "--sample-rate",
        type=float,
        default=DEFAULT_SAMPLE_RATE_HZ,
        help="Frecuencia de muestreo en Hz.",
    )

    parser.add_argument(
        "--print-rate",
        type=float,
        default=2.0,
        help="Frecuencia de impresión en consola en Hz.",
    )

    parser.add_argument(
        "--window",
        type=float,
        default=DEFAULT_WINDOW_SECONDS,
        help="Ventana temporal para stable_window, en segundos.",
    )

    parser.add_argument(
        "--acc-threshold",
        type=float,
        default=DEFAULT_ACC_THRESHOLD_G,
        help="Umbral de movimiento por aceleración en g.",
    )

    parser.add_argument(
        "--gyro-threshold",
        type=float,
        default=DEFAULT_GYRO_THRESHOLD_DPS,
        help="Umbral de movimiento por giroscopio en grados/s.",
    )

    parser.add_argument(
        "--calibration-samples",
        type=int,
        default=100,
        help="Número de muestras para calibración inicial.",
    )

    return parser.parse_args()


def main() -> None:
    """Función principal de prueba."""

    args = parse_arguments()

    if args.sample_rate <= 0:
        raise ValueError("--sample-rate debe ser mayor que cero.")

    if args.print_rate <= 0:
        raise ValueError("--print-rate debe ser mayor que cero.")

    if args.window <= 0:
        raise ValueError("--window debe ser mayor que cero.")

    sample_period_s = 1.0 / args.sample_rate
    print_period_s = 1.0 / args.print_rate

    print("Iniciando procesamiento MPU6050")
    print(f"Bus I2C: /dev/i2c-{args.bus}")
    print(f"Dirección I2C: 0x{args.address:02X}")
    print(f"Frecuencia de muestreo: {args.sample_rate:.1f} Hz")
    print(f"Ventana de estabilidad: {args.window:.1f} s")
    print("Mantén el sensor quieto durante la calibración inicial.\n")

    try:
        with SMBus(args.bus) as bus:
            sensor = MPU6050(bus=bus, address=args.address)

            who_am_i = sensor.check_identity()
            print(f"WHO_AM_I leído: 0x{who_am_i:02X}")

            if who_am_i != 0x68:
                print(
                    "Advertencia: WHO_AM_I no devolvió 0x68. "
                    "Verifica dirección, cableado o modelo exacto."
                )

            sensor.initialize(sample_rate_hz=args.sample_rate)

            processor = MPUDataProcessor(
                sample_rate_hz=args.sample_rate,
                window_seconds=args.window,
                acc_threshold_g=args.acc_threshold,
                gyro_threshold_dps=args.gyro_threshold,
            )

            print("Calibrando giroscopio y referencia de aceleración...")
            processor.calibrate(
                sensor=sensor,
                calibration_samples=args.calibration_samples,
                delay_s=sample_period_s,
            )

            print("Calibración terminada.")
            print(f"Offset gyro X: {processor.gx_offset:.3f} °/s")
            print(f"Offset gyro Y: {processor.gy_offset:.3f} °/s")
            print(f"Offset gyro Z: {processor.gz_offset:.3f} °/s")
            print(f"acc_mag base:  {processor.baseline_acc_mag:.3f} g\n")

            print(
                "Tiempo[s] | "
                "acc_mag[g]  gyro_mag[°/s]  Movimiento  Ventana_estable  posture_label"
            )
            print("-" * 88)

            start_time = time.monotonic()
            last_print_time = 0.0

            while True:
                loop_start = time.monotonic()

                sample = sensor.read_sample()
                processed = processor.process_sample(sample)

                now = time.monotonic()
                elapsed_s = now - start_time

                if now - last_print_time >= print_period_s:
                    motion_text = "SI" if processed.motion_detected else "NO"
                    stable_text = "SI" if processed.stable_window else "NO"

                    print(
                        f"{elapsed_s:8.2f} | "
                        f"{processed.acc_mag:10.3f}  "
                        f"{processed.gyro_mag:13.3f}  "
                        f"{motion_text:^10}  "
                        f"{stable_text:^15}  "
                        f"{processed.posture_label}"
                    )

                    last_print_time = now

                elapsed_loop = time.monotonic() - loop_start
                sleep_time = sample_period_s - elapsed_loop

                if sleep_time > 0:
                    time.sleep(sleep_time)

    except FileNotFoundError:
        print(
            f"Error: no existe /dev/i2c-{args.bus}. "
            "Habilita I2C con sudo raspi-config y reinicia la Raspberry Pi."
        )

    except OSError as error:
        print("Error de comunicación I2C.")
        print("Posibles causas:")
        print("- El MPU6050 no está conectado correctamente.")
        print("- SDA y SCL están invertidos.")
        print("- I2C no está habilitado.")
        print("- La dirección I2C no es 0x68 sino 0x69.")
        print("- El sensor no está alimentado.")
        print(f"Detalle técnico: {error}")

    except KeyboardInterrupt:
        print("\nPrueba detenida por el usuario.")


if __name__ == "__main__":
    main()