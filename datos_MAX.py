#!/usr/bin/env python3
"""
datos_MAX.py

Lectura y procesamiento básico del MAX30102 / MAX30105.

Este programa:
1. Lee señales ópticas crudas RED e IR por I2C.
2. Guarda una ventana temporal de muestras.
3. Estima frecuencia cardíaca a partir de picos en IR.
4. Estima SpO2 usando la relación AC/DC de RED e IR.
5. Muestra RED, IR, FC y SpO2 en consola.

Advertencia:
Los valores de FC y SpO2 son aproximados y experimentales.
No deben usarse como medición médica certificada.
"""

from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from smbus2 import SMBus


# ============================================================
# Registros principales del MAX30102 / MAX30105
# ============================================================

MAX3010X_ADDRESS = 0x57

REG_INTR_STATUS_1 = 0x00
REG_INTR_STATUS_2 = 0x01

REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07

REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A

REG_LED1_PA = 0x0C   # LED rojo
REG_LED2_PA = 0x0D   # LED infrarrojo

REG_PART_ID = 0xFF

EXPECTED_PART_ID = 0x15


# ============================================================
# Parámetros de adquisición y procesamiento
# ============================================================

SAMPLE_RATE_HZ = 50.0
DEFAULT_WINDOW_SECONDS = 8.0

MIN_VALID_BPM = 40.0
MAX_VALID_BPM = 180.0


@dataclass
class RawOpticalSample:
    """Muestra cruda RED/IR leída desde la FIFO del sensor."""

    red: int
    ir: int


@dataclass
class ProcessedMAXData:
    """Resultado procesado del MAX30102 / MAX30105."""

    red_raw: int
    ir_raw: int
    heart_rate_bpm: Optional[float]
    spo2_percent: Optional[float]
    ratio_r: Optional[float]
    signal_quality: float
    finger_detected: bool


class MAX3010X:
    """
    Driver mínimo para MAX30102 / MAX30105.

    Esta clase solo se encarga de:
    - escribir registros,
    - leer registros,
    - configurar el sensor,
    - leer muestras RED/IR desde la FIFO.

    No calcula frecuencia cardíaca ni SpO2.
    """

    def __init__(self, bus: SMBus, address: int = MAX3010X_ADDRESS) -> None:
        self.bus = bus
        self.address = address

    def write_register(self, register: int, value: int) -> None:
        """Escribe un byte en un registro del sensor."""
        self.bus.write_byte_data(self.address, register, value)

    def read_register(self, register: int) -> int:
        """Lee un byte desde un registro del sensor."""
        return self.bus.read_byte_data(self.address, register)

    def read_block(self, register: int, length: int) -> list[int]:
        """Lee varios bytes consecutivos desde un registro."""
        return self.bus.read_i2c_block_data(self.address, register, length)

    def check_identity(self) -> int:
        """Lee el PART_ID del sensor."""
        return self.read_register(REG_PART_ID)

    def clear_interrupts(self) -> None:
        """Limpia banderas internas de interrupción leyendo los registros de estado."""
        _ = self.read_register(REG_INTR_STATUS_1)
        _ = self.read_register(REG_INTR_STATUS_2)

    def reset(self) -> None:
        """Reinicia internamente el sensor."""
        self.write_register(REG_MODE_CONFIG, 0x40)
        time.sleep(0.100)

    def reset_fifo(self) -> None:
        """Reinicia los punteros de la FIFO."""
        self.write_register(REG_FIFO_WR_PTR, 0x00)
        self.write_register(REG_OVF_COUNTER, 0x00)
        self.write_register(REG_FIFO_RD_PTR, 0x00)

    def initialize(self, led_current: int = 0x24) -> None:
        """
        Inicializa el MAX30102 / MAX30105 en modo SpO2.

        Modo SpO2:
        - LED rojo
        - LED infrarrojo

        Esta configuración permite obtener RED e IR, que son las señales
        necesarias para frecuencia cardíaca y estimación de SpO2.
        """

        self.reset()
        self.clear_interrupts()
        self.reset_fifo()

        # FIFO_CONFIG:
        # bit 4 = 1 -> rollover activado.
        # Esto evita bloqueo si la FIFO se llena.
        # Sin promedio interno; el filtrado lo haremos en software.
        self.write_register(REG_FIFO_CONFIG, 0x10)

        # SPO2_CONFIG:
        # ADC range moderado.
        # Sample rate aproximado: 50 muestras/s.
        # Pulse width alto para mayor resolución.
        self.write_register(REG_SPO2_CONFIG, 0x23)

        # Corriente de LEDs.
        # Si los valores son muy bajos, puedes subir a 0x3F.
        # Si se saturan, baja a 0x1F o menos.
        self.write_register(REG_LED1_PA, led_current)  # RED
        self.write_register(REG_LED2_PA, led_current)  # IR

        # MODE_CONFIG = 0x03 -> modo SpO2: RED + IR.
        self.write_register(REG_MODE_CONFIG, 0x03)

        time.sleep(0.100)

    def available_samples(self) -> int:
        """
        Calcula cuántas muestras completas hay disponibles en la FIFO.

        La FIFO usa punteros de 5 bits, por eso su profundidad es 32.
        """

        write_ptr = self.read_register(REG_FIFO_WR_PTR)
        read_ptr = self.read_register(REG_FIFO_RD_PTR)

        samples = write_ptr - read_ptr

        if samples < 0:
            samples += 32

        return samples

    @staticmethod
    def parse_18_bit_value(b1: int, b2: int, b3: int) -> int:
        """
        Convierte tres bytes de la FIFO en un valor de 18 bits.

        Cada canal óptico se entrega en 3 bytes.
        Solo los 18 bits menos significativos son válidos.
        """

        return ((b1 << 16) | (b2 << 8) | b3) & 0x3FFFF

    def read_sample(self) -> RawOpticalSample:
        """
        Lee una muestra RED + IR desde la FIFO.

        En modo SpO2:
        - RED usa 3 bytes.
        - IR usa 3 bytes.
        Total: 6 bytes por muestra.
        """

        data = self.read_block(REG_FIFO_DATA, 6)

        red = self.parse_18_bit_value(data[0], data[1], data[2])
        ir = self.parse_18_bit_value(data[3], data[4], data[5])

        return RawOpticalSample(red=red, ir=ir)

    def read_available_samples(self) -> list[RawOpticalSample]:
        """Lee todas las muestras pendientes en la FIFO."""

        count = self.available_samples()
        samples: list[RawOpticalSample] = []

        for _ in range(count):
            samples.append(self.read_sample())

        return samples


class MAXDataProcessor:
    """
    Procesador de datos RED/IR.

    Este módulo recibe muestras crudas y calcula:
    - frecuencia cardíaca aproximada,
    - saturación de oxígeno aproximada,
    - calidad básica de señal.
    """

    def __init__(
        self,
        sample_rate_hz: float = SAMPLE_RATE_HZ,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        finger_threshold: int = 10000,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.window_seconds = window_seconds
        self.finger_threshold = finger_threshold

        max_samples = int(sample_rate_hz * window_seconds)

        self.red_window: deque[int] = deque(maxlen=max_samples)
        self.ir_window: deque[int] = deque(maxlen=max_samples)

        self.latest_red = 0
        self.latest_ir = 0

    def add_sample(self, sample: RawOpticalSample) -> None:
        """Agrega una muestra cruda a la ventana temporal."""

        self.latest_red = sample.red
        self.latest_ir = sample.ir

        self.red_window.append(sample.red)
        self.ir_window.append(sample.ir)

    @staticmethod
    def mean(values: list[float]) -> float:
        """Calcula promedio evitando errores con listas vacías."""

        if not values:
            return 0.0

        return sum(values) / len(values)

    @staticmethod
    def rms(values: list[float]) -> float:
        """Calcula valor RMS de una señal."""

        if not values:
            return 0.0

        return math.sqrt(sum(v * v for v in values) / len(values))

    @staticmethod
    def moving_average(values: list[float], radius: int = 2) -> list[float]:
        """
        Aplica un promedio móvil simple.

        radius = 2 significa que cada punto se suaviza usando hasta:
        - 2 muestras anteriores,
        - la muestra actual,
        - 2 muestras siguientes.
        """

        if not values:
            return []

        filtered: list[float] = []

        for i in range(len(values)):
            start = max(0, i - radius)
            end = min(len(values), i + radius + 1)
            window = values[start:end]
            filtered.append(sum(window) / len(window))

        return filtered

    def remove_dc(self, values: list[int]) -> tuple[list[float], float]:
        """
        Separa la señal en:
        - DC: promedio de la ventana.
        - AC: señal menos su promedio.

        Para PPG, la componente DC representa el nivel óptico promedio.
        La componente AC representa la variación pulsátil.
        """

        values_float = [float(v) for v in values]
        dc = self.mean(values_float)
        ac = [v - dc for v in values_float]

        return ac, dc

    def detect_peaks(self, signal: list[float]) -> list[int]:
        """
        Detecta picos en una señal filtrada.

        Usa:
        - umbral dinámico basado en desviación estándar,
        - distancia mínima entre picos para evitar dobles detecciones.
        """

        if len(signal) < 3:
            return []

        try:
            std_value = statistics.stdev(signal)
        except statistics.StatisticsError:
            return []

        if std_value <= 1e-6:
            return []

        threshold = 0.35 * std_value

        min_distance_samples = int(self.sample_rate_hz * 60.0 / MAX_VALID_BPM)
        max_distance_samples = int(self.sample_rate_hz * 60.0 / MIN_VALID_BPM)

        peaks: list[int] = []
        last_peak_index = -10_000

        for i in range(1, len(signal) - 1):
            is_local_peak = signal[i - 1] < signal[i] >= signal[i + 1]
            is_above_threshold = signal[i] > threshold
            is_far_enough = (i - last_peak_index) >= min_distance_samples

            if is_local_peak and is_above_threshold and is_far_enough:
                # Si el intervalo es demasiado largo, igual se acepta;
                # luego se filtran intervalos no fisiológicos.
                peaks.append(i)
                last_peak_index = i

        # Filtro adicional: elimina picos que generen intervalos excesivos
        # no se hace aquí directamente para conservar el detector simple.
        _ = max_distance_samples

        return peaks

    def estimate_heart_rate(self, ir_ac_smoothed: list[float]) -> tuple[Optional[float], float]:
        """
        Estima frecuencia cardíaca usando picos en IR.

        Para hacerlo robusto ante inversión de señal, prueba:
        - picos positivos,
        - picos negativos,
        y usa el caso que produzca más picos válidos.
        """

        positive_peaks = self.detect_peaks(ir_ac_smoothed)
        negative_signal = [-v for v in ir_ac_smoothed]
        negative_peaks = self.detect_peaks(negative_signal)

        if len(negative_peaks) > len(positive_peaks):
            peaks = negative_peaks
        else:
            peaks = positive_peaks

        if len(peaks) < 2:
            return None, 0.0

        intervals_s: list[float] = []

        for a, b in zip(peaks, peaks[1:]):
            interval_s = (b - a) / self.sample_rate_hz

            bpm = 60.0 / interval_s

            if MIN_VALID_BPM <= bpm <= MAX_VALID_BPM:
                intervals_s.append(interval_s)

        if len(intervals_s) < 2:
            return None, 20.0

        median_interval_s = statistics.median(intervals_s)
        heart_rate_bpm = 60.0 / median_interval_s

        if len(intervals_s) >= 2:
            mean_interval = self.mean(intervals_s)
            interval_std = statistics.stdev(intervals_s) if len(intervals_s) >= 2 else 0.0
            coefficient_variation = interval_std / mean_interval if mean_interval > 0 else 1.0
        else:
            coefficient_variation = 1.0

        # Calidad simple:
        # Si los intervalos entre picos son constantes, la calidad sube.
        quality = 100.0 * max(0.0, min(1.0, 1.0 - 2.0 * coefficient_variation))

        return heart_rate_bpm, quality

    def estimate_spo2(
        self,
        red_ac: list[float],
        ir_ac: list[float],
        red_dc: float,
        ir_dc: float,
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Estima SpO2 usando la relación de razones:

            R = (AC_RED / DC_RED) / (AC_IR / DC_IR)

        Luego se usa una aproximación lineal común:

            SpO2 ≈ 104 - 17R

        Esta ecuación es aproximada y requiere calibración para uso real.
        """

        if red_dc <= 0 or ir_dc <= 0:
            return None, None

        red_ac_rms = self.rms(red_ac)
        ir_ac_rms = self.rms(ir_ac)

        if red_ac_rms <= 0 or ir_ac_rms <= 0:
            return None, None

        ratio_r = (red_ac_rms / red_dc) / (ir_ac_rms / ir_dc)

        spo2 = 104.0 - 17.0 * ratio_r

        # Limitamos el rango para evitar mostrar resultados absurdos
        # durante ruido, ausencia de dedo o movimiento.
        if spo2 < 50.0 or spo2 > 100.0:
            return None, ratio_r

        return spo2, ratio_r

    def process(self) -> ProcessedMAXData:
        """
        Procesa la ventana actual y devuelve los valores estimados.

        Si aún no hay suficientes datos, devuelve FC y SpO2 como None.
        """

        if len(self.ir_window) < int(self.sample_rate_hz * 4):
            return ProcessedMAXData(
                red_raw=self.latest_red,
                ir_raw=self.latest_ir,
                heart_rate_bpm=None,
                spo2_percent=None,
                ratio_r=None,
                signal_quality=0.0,
                finger_detected=False,
            )

        red_values = list(self.red_window)
        ir_values = list(self.ir_window)

        finger_detected = self.mean([float(v) for v in ir_values]) > self.finger_threshold

        red_ac, red_dc = self.remove_dc(red_values)
        ir_ac, ir_dc = self.remove_dc(ir_values)

        ir_ac_smoothed = self.moving_average(ir_ac, radius=2)

        heart_rate_bpm, quality = self.estimate_heart_rate(ir_ac_smoothed)
        spo2_percent, ratio_r = self.estimate_spo2(
            red_ac=red_ac,
            ir_ac=ir_ac,
            red_dc=red_dc,
            ir_dc=ir_dc,
        )

        if not finger_detected:
            heart_rate_bpm = None
            spo2_percent = None
            quality = 0.0

        return ProcessedMAXData(
            red_raw=self.latest_red,
            ir_raw=self.latest_ir,
            heart_rate_bpm=heart_rate_bpm,
            spo2_percent=spo2_percent,
            ratio_r=ratio_r,
            signal_quality=quality,
            finger_detected=finger_detected,
        )


def format_optional_float(value: Optional[float], width: int, decimals: int = 1) -> str:
    """Formatea valores opcionales para imprimir en consola."""

    if value is None:
        return f"{'--':>{width}}"

    return f"{value:{width}.{decimals}f}"


def parse_arguments() -> argparse.Namespace:
    """Procesa argumentos de línea de comandos."""

    parser = argparse.ArgumentParser(
        description="Procesamiento de RED/IR para estimar FC y SpO2."
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
        default=MAX3010X_ADDRESS,
        help="Dirección I2C del sensor. Normalmente 0x57.",
    )

    parser.add_argument(
        "--led-current",
        type=lambda value: int(value, 0),
        default=0x24,
        help="Corriente de LEDs. Ejemplos: 0x1F, 0x24, 0x3F.",
    )

    parser.add_argument(
        "--window",
        type=float,
        default=DEFAULT_WINDOW_SECONDS,
        help="Tamaño de ventana temporal en segundos.",
    )

    parser.add_argument(
        "--print-rate",
        type=float,
        default=1.0,
        help="Frecuencia de impresión en consola en Hz.",
    )

    parser.add_argument(
        "--finger-threshold",
        type=int,
        default=10000,
        help="Umbral mínimo de IR promedio para considerar que hay dedo.",
    )

    return parser.parse_args()


def main() -> None:
    """Función principal de prueba."""

    args = parse_arguments()

    if not 0x00 <= args.led_current <= 0xFF:
        raise ValueError("El valor --led-current debe estar entre 0x00 y 0xFF.")

    if args.window < 4.0:
        raise ValueError("La ventana debe ser de al menos 4 segundos.")

    if args.print_rate <= 0:
        raise ValueError("--print-rate debe ser mayor que cero.")

    print("Iniciando procesamiento MAX30102 / MAX30105")
    print(f"Bus I2C: /dev/i2c-{args.bus}")
    print(f"Dirección I2C: 0x{args.address:02X}")
    print(f"Corriente LED: 0x{args.led_current:02X}")
    print(f"Ventana de procesamiento: {args.window:.1f} s")
    print("Presiona Ctrl+C para detener.\n")

    print(
        "Tiempo[s] | "
        "RED      IR       | "
        "FC[bpm]  SpO2[%]  R       Calidad[%]  Dedo"
    )
    print("-" * 82)

    print_period_s = 1.0 / args.print_rate
    last_print_time = 0.0
    start_time = time.monotonic()

    try:
        with SMBus(args.bus) as bus:
            sensor = MAX3010X(bus=bus, address=args.address)

            part_id = sensor.check_identity()

            if part_id != EXPECTED_PART_ID:
                print(
                    f"Advertencia: PART_ID leído = 0x{part_id:02X}. "
                    "El valor típico esperado es 0x15."
                )

            sensor.initialize(led_current=args.led_current)

            processor = MAXDataProcessor(
                sample_rate_hz=SAMPLE_RATE_HZ,
                window_seconds=args.window,
                finger_threshold=args.finger_threshold,
            )

            while True:
                new_samples = sensor.read_available_samples()

                for sample in new_samples:
                    processor.add_sample(sample)

                now = time.monotonic()
                elapsed_s = now - start_time

                if now - last_print_time >= print_period_s:
                    processed = processor.process()

                    fc_text = format_optional_float(processed.heart_rate_bpm, width=7, decimals=1)
                    spo2_text = format_optional_float(processed.spo2_percent, width=7, decimals=1)
                    r_text = format_optional_float(processed.ratio_r, width=6, decimals=3)

                    finger_text = "SI" if processed.finger_detected else "NO"

                    print(
                        f"{elapsed_s:8.2f} | "
                        f"{processed.red_raw:7d} {processed.ir_raw:7d} | "
                        f"{fc_text}  {spo2_text}  {r_text}  "
                        f"{processed.signal_quality:10.1f}  {finger_text}"
                    )

                    last_print_time = now

                # Polling suficientemente rápido para no perder datos a 50 Hz.
                time.sleep(0.020)

    except FileNotFoundError:
        print(
            f"Error: no existe /dev/i2c-{args.bus}. "
            "Habilita I2C con sudo raspi-config y reinicia la Raspberry Pi."
        )

    except OSError as error:
        print("Error de comunicación I2C.")
        print("Posibles causas:")
        print("- El MAX30102/MAX30105 no está conectado correctamente.")
        print("- SDA y SCL están invertidos.")
        print("- I2C no está habilitado.")
        print("- La dirección I2C no es 0x57.")
        print("- El sensor no está alimentado.")
        print(f"Detalle técnico: {error}")

    except KeyboardInterrupt:
        print("\nPrueba detenida por el usuario.")


if __name__ == "__main__":
    main()