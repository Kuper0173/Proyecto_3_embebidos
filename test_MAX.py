#!/usr/bin/env python3
"""
pueba_sensores.py

Prueba estable para sensores MAX30102 / MAX30105 usando Raspberry Pi Zero 2 W.

Este programa:
1. Abre el bus I2C.
2. Verifica el PART_ID del sensor.
3. Configura el sensor en modo SpO2: RED + IR.
4. Lee datos crudos desde la FIFO.
5. Muestra RED e IR en consola.

Conexión:
VIN/VCC -> 3.3 V
GND     -> GND
SDA     -> GPIO2 / Pin físico 3
SCL     -> GPIO3 / Pin físico 5
INT     -> No conectar por ahora

"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from smbus2 import SMBus


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
REG_LED1_PA = 0x0C      # RED LED
REG_LED2_PA = 0x0D      # IR LED
REG_PART_ID = 0xFF

EXPECTED_PART_ID = 0x15


@dataclass
class OpticalSample:
    """Muestra óptica cruda del sensor."""

    red: int
    ir: int


class MAX3010X:
    """
    Driver mínimo para MAX30102 / MAX30105.

    Este código no calcula frecuencia cardíaca ni SpO2.
    Solo verifica comunicación I2C y lectura de señales RED/IR.
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
        """Lee varios bytes consecutivos desde el sensor."""
        return self.bus.read_i2c_block_data(self.address, register, length)

    def check_identity(self) -> int:
        """Lee el registro PART_ID."""
        return self.read_register(REG_PART_ID)

    def clear_interrupts(self) -> None:
        """
        Limpia banderas internas de interrupción.

        Aunque no usamos el pin INT, leer estos registros limpia estados pendientes.
        """
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
        Inicializa el sensor en modo RED + IR.

        Configuración:
        - FIFO con promedio de 4 muestras.
        - FIFO rollover activado para evitar bloqueo si se llena.
        - Modo SpO2: RED + IR.
        - Frecuencia de muestreo aproximada: 50 muestras/s.
        - Ancho de pulso alto para mayor resolución.
        """

        self.reset()
        self.clear_interrupts()
        self.reset_fifo()

        # FIFO_CONFIG:
        # Bits [7:5] = 010 -> promedio de 4 muestras.
        # Bit  [4]   = 1   -> FIFO rollover habilitado.
        # Bits [3:0] = 0000.
        self.write_register(REG_FIFO_CONFIG, 0x50)

        # SPO2_CONFIG:
        # Bits [6:5] = 01  -> rango ADC moderado.
        # Bits [4:2] = 000 -> 50 muestras/s.
        # Bits [1:0] = 11  -> ancho de pulso alto.
        self.write_register(REG_SPO2_CONFIG, 0x23)

        # Corriente de LEDs.
        self.write_register(REG_LED1_PA, led_current)  # RED
        self.write_register(REG_LED2_PA, led_current)  # IR

        # MODE_CONFIG:
        # 0x03 -> modo SpO2, usa RED + IR.
        self.write_register(REG_MODE_CONFIG, 0x03)

        time.sleep(0.100)

    def available_samples(self) -> int:
        """
        Calcula cuántas muestras completas hay disponibles en FIFO.

        La FIFO tiene 32 posiciones. Los punteros son de 5 bits.
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
        Convierte tres bytes en un valor de 18 bits.

        Cada canal óptico se entrega como 3 bytes.
        Solo los 18 bits menos significativos son válidos.
        """
        return ((b1 << 16) | (b2 << 8) | b3) & 0x3FFFF

    def read_sample(self) -> OpticalSample:
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

        return OpticalSample(red=red, ir=ir)

    def read_latest_sample(self) -> OpticalSample | None:
        """
        Lee todas las muestras pendientes y devuelve la más reciente.

        Esto evita que la FIFO se llene si el sensor mide más rápido
        que la velocidad de impresión en consola.
        """
        samples_available = self.available_samples()

        if samples_available == 0:
            return None

        latest_sample = None

        for _ in range(samples_available):
            latest_sample = self.read_sample()

        return latest_sample


def parse_arguments() -> argparse.Namespace:
    """Procesa argumentos de línea de comandos."""

    parser = argparse.ArgumentParser(
        description="Prueba estable del MAX30102 / MAX30105 por I2C."
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
        "--rate",
        type=float,
        default=10.0,
        help="Frecuencia de impresión en consola, en Hz.",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Duración en segundos. 0 significa ejecución infinita.",
    )

    parser.add_argument(
        "--led-current",
        type=lambda value: int(value, 0),
        default=0x24,
        help="Corriente de LEDs. Ejemplos: 0x1F, 0x24, 0x3F.",
    )

    return parser.parse_args()


def main() -> None:
    """Función principal."""

    args = parse_arguments()

    if args.rate <= 0:
        raise ValueError("La frecuencia --rate debe ser mayor que cero.")

    if not 0x00 <= args.led_current <= 0xFF:
        raise ValueError("El valor --led-current debe estar entre 0x00 y 0xFF.")

    period_s = 1.0 / args.rate

    print("Iniciando prueba MAX30102 / MAX30105")
    print(f"Bus I2C: /dev/i2c-{args.bus}")
    print(f"Dirección I2C: 0x{args.address:02X}")
    print(f"Corriente LED: 0x{args.led_current:02X}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        with SMBus(args.bus) as bus:
            sensor = MAX3010X(bus=bus, address=args.address)

            part_id = sensor.check_identity()
            print(f"PART_ID leído: 0x{part_id:02X}")

            if part_id != EXPECTED_PART_ID:
                print(
                    "Advertencia: PART_ID no coincide con 0x15. "
                    "Revisa el modelo exacto del sensor o la conexión I2C."
                )

            sensor.initialize(led_current=args.led_current)
            print("Sensor inicializado correctamente.\n")

            print("Tiempo[s] | RED        IR")
            print("-" * 34)

            start_time = time.monotonic()

            while True:
                elapsed_s = time.monotonic() - start_time

                if args.duration > 0 and elapsed_s >= args.duration:
                    break

                sample = sensor.read_latest_sample()

                if sample is not None:
                    print(
                        f"{elapsed_s:8.2f} | "
                        f"{sample.red:8d} "
                        f"{sample.ir:8d}"
                    )

                time.sleep(period_s)

    except FileNotFoundError:
        print(
            f"Error: no existe /dev/i2c-{args.bus}. "
            "Habilita I2C con sudo raspi-config y reinicia la Raspberry Pi."
        )

    except OSError as error:
        print("Error de comunicación I2C.")
        print("Posibles causas:")
        print("- El sensor no está conectado correctamente.")
        print("- SDA y SCL están invertidos.")
        print("- I2C no está habilitado.")
        print("- El sensor no está alimentado.")
        print("- La dirección I2C no es 0x57.")
        print(f"Detalle técnico: {error}")

    except KeyboardInterrupt:
        print("\nPrueba detenida por el usuario.")


if __name__ == "__main__":
    main()