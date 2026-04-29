#!/usr/bin/env python3
"""
pueba_sensores.py

Prueba básica del sensor MAX30105 con Raspberry Pi Zero 2 W usando I2C.

El programa:
1. Abre el bus I2C de la Raspberry Pi.
2. Verifica que el MAX30105 responda leyendo PART_ID.
3. Inicializa el sensor en modo Multi-LED.
4. Lee datos crudos RED, IR y GREEN desde la FIFO.
5. Muestra los datos en consola.

Conexión:
MAX30105 VIN/VCC -> Raspberry Pi 3.3 V
MAX30105 GND     -> Raspberry Pi GND
MAX30105 SDA     -> GPIO2 / SDA1 / Pin físico 3
MAX30105 SCL     -> GPIO3 / SCL1 / Pin físico 5
MAX30105 INT     -> No conectar por ahora
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from smbus2 import SMBus


# Dirección I2C de 7 bits del MAX30105.
MAX30105_ADDRESS = 0x57

# Registros principales del MAX30105.
REG_INTR_STATUS_1 = 0x00
REG_INTR_STATUS_2 = 0x01
REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C      # LED rojo
REG_LED2_PA = 0x0D      # LED infrarrojo
REG_LED3_PA = 0x0E      # LED verde
REG_MULTI_LED_CTRL1 = 0x11
REG_MULTI_LED_CTRL2 = 0x12
REG_PART_ID = 0xFF

# Valor esperado del registro PART_ID para MAX30105.
MAX30105_EXPECTED_PART_ID = 0x15


@dataclass
class MAX30105Sample:
    """Muestra cruda del MAX30105."""

    red: int
    ir: int
    green: int


class MAX30105:
    """
    Driver mínimo para el MAX30105.

    Este driver no calcula frecuencia cardíaca ni SpO2.
    Solo prueba que el sensor responde y entrega muestras ópticas crudas.
    """

    def __init__(self, bus: SMBus, address: int = MAX30105_ADDRESS) -> None:
        self.bus = bus
        self.address = address

    def write_register(self, register: int, value: int) -> None:
        """Escribe un byte en un registro del MAX30105."""
        self.bus.write_byte_data(self.address, register, value)

    def read_register(self, register: int) -> int:
        """Lee un byte desde un registro del MAX30105."""
        return self.bus.read_byte_data(self.address, register)

    def read_block(self, register: int, length: int) -> list[int]:
        """Lee varios bytes consecutivos desde un registro."""
        return self.bus.read_i2c_block_data(self.address, register, length)

    def check_identity(self) -> int:
        """
        Lee el registro PART_ID.

        En el MAX30105 debe devolver 0x15.
        """
        return self.read_register(REG_PART_ID)

    def clear_interrupts(self) -> None:
        """
        Limpia banderas de interrupción leyendo los registros de estado.

        En este programa no usamos el pin INT, pero limpiar estos registros
        evita que queden banderas pendientes después del encendido.
        """
        _ = self.read_register(REG_INTR_STATUS_1)
        _ = self.read_register(REG_INTR_STATUS_2)

    def reset(self) -> None:
        """
        Reinicia internamente el MAX30105.

        El bit RESET está en el registro MODE_CONFIG.
        """
        self.write_register(REG_MODE_CONFIG, 0x40)
        time.sleep(0.100)

    def reset_fifo(self) -> None:
        """Reinicia punteros internos de la FIFO."""
        self.write_register(REG_FIFO_WR_PTR, 0x00)
        self.write_register(REG_OVF_COUNTER, 0x00)
        self.write_register(REG_FIFO_RD_PTR, 0x00)

    def initialize(self, led_current: int = 0x24) -> None:
        """
        Inicializa el MAX30105 para leer RED, IR y GREEN.

        Configuración usada:
        - FIFO con promedio de 4 muestras.
        - Modo Multi-LED.
        - RED en slot 1.
        - IR en slot 2.
        - GREEN en slot 3.
        - Corriente moderada en los LEDs.

        led_current:
        - Valor de 0x00 a 0xFF.
        - Para una primera prueba se usa 0x24, una corriente moderada.
        """

        self.reset()
        self.clear_interrupts()
        self.reset_fifo()

        # FIFO_CONFIG:
        # Bits [7:5] SMP_AVE = 010 -> promedio de 4 muestras.
        # Bit  [4]   FIFO_ROLLOVER_EN = 0 -> no sobrescribir si se llena.
        # Bits [3:0] FIFO_A_FULL = 0000.
        self.write_register(REG_FIFO_CONFIG, 0x40)

        # SPO2_CONFIG:
        # Bits [6:5] ADC range = 01.
        # Bits [4:2] sample rate = 001 -> 100 muestras/s.
        # Bits [1:0] pulse width = 11 -> mayor resolución.
        self.write_register(REG_SPO2_CONFIG, 0x27)

        # Corriente de los LEDs.
        self.write_register(REG_LED1_PA, led_current)  # Rojo
        self.write_register(REG_LED2_PA, led_current)  # Infrarrojo
        self.write_register(REG_LED3_PA, led_current)  # Verde

        # Multi-LED mode control:
        # SLOT1 = RED   -> 001
        # SLOT2 = IR    -> 010
        # SLOT3 = GREEN -> 011
        # SLOT4 = NONE  -> 000
        self.write_register(REG_MULTI_LED_CTRL1, 0x21)
        self.write_register(REG_MULTI_LED_CTRL2, 0x03)

        # MODE_CONFIG:
        # MODE = 111 -> Multi-LED mode.
        self.write_register(REG_MODE_CONFIG, 0x07)

        time.sleep(0.100)

    def available_samples(self) -> int:
        """
        Calcula cuántas muestras hay disponibles en la FIFO.

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
        Convierte tres bytes de la FIFO en una medición de 18 bits.

        Cada canal óptico del MAX30105 se almacena en 3 bytes.
        Solo los 18 bits menos significativos son datos válidos.
        """
        return ((b1 << 16) | (b2 << 8) | b3) & 0x3FFFF

    def read_sample(self) -> MAX30105Sample | None:
        """
        Lee una muestra RED, IR y GREEN desde la FIFO.

        En modo Multi-LED con 3 LEDs:
        - RED usa 3 bytes.
        - IR usa 3 bytes.
        - GREEN usa 3 bytes.

        Total: 9 bytes por muestra.
        """

        if self.available_samples() == 0:
            return None

        data = self.read_block(REG_FIFO_DATA, 9)

        red = self.parse_18_bit_value(data[0], data[1], data[2])
        ir = self.parse_18_bit_value(data[3], data[4], data[5])
        green = self.parse_18_bit_value(data[6], data[7], data[8])

        return MAX30105Sample(red=red, ir=ir, green=green)


def parse_arguments() -> argparse.Namespace:
    """Procesa argumentos de línea de comandos."""

    parser = argparse.ArgumentParser(
        description="Prueba del MAX30105 en Raspberry Pi usando I2C."
    )

    parser.add_argument(
        "--bus",
        type=int,
        default=1,
        help="Número del bus I2C. En Raspberry Pi normalmente es 1.",
    )

    parser.add_argument(
        "--address",
        type=lambda value: int(value, 0),
        default=MAX30105_ADDRESS,
        help="Dirección I2C del MAX30105. Normalmente es 0x57.",
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
        help="Duración de la prueba en segundos. 0 significa ejecución infinita.",
    )

    parser.add_argument(
        "--led-current",
        type=lambda value: int(value, 0),
        default=0x24,
        help="Corriente de LEDs como valor hexadecimal. Ejemplo: 0x1F, 0x24, 0x3F.",
    )

    return parser.parse_args()


def main() -> None:
    """Función principal del programa."""

    args = parse_arguments()

    if args.rate <= 0:
        raise ValueError("La frecuencia --rate debe ser mayor que cero.")

    if not 0x00 <= args.led_current <= 0xFF:
        raise ValueError("El valor --led-current debe estar entre 0x00 y 0xFF.")

    period_s = 1.0 / args.rate

    print("Iniciando prueba del MAX30105")
    print(f"Bus I2C: /dev/i2c-{args.bus}")
    print(f"Dirección I2C: 0x{args.address:02X}")
    print(f"Corriente LED configurada: 0x{args.led_current:02X}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        with SMBus(args.bus) as bus:
            sensor = MAX30105(bus=bus, address=args.address)

            part_id = sensor.check_identity()
            print(f"PART_ID leído: 0x{part_id:02X}")

            if part_id != MAX30105_EXPECTED_PART_ID:
                print(
                    "Advertencia: PART_ID no coincide con 0x15. "
                    "Verifica si el sensor es realmente MAX30105, "
                    "si la dirección I2C es correcta o si el cableado está bien."
                )

            sensor.initialize(led_current=args.led_current)
            print("MAX30105 inicializado correctamente.\n")

            print("Tiempo[s] | RED       IR        GREEN")
            print("-" * 44)

            start_time = time.monotonic()

            while True:
                elapsed_s = time.monotonic() - start_time

                if args.duration > 0 and elapsed_s >= args.duration:
                    break

                sample = sensor.read_sample()

                if sample is not None:
                    print(
                        f"{elapsed_s:8.2f} | "
                        f"{sample.red:8d} "
                        f"{sample.ir:8d} "
                        f"{sample.green:8d}"
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
        print("- El MAX30105 no está conectado correctamente.")
        print("- I2C no está habilitado.")
        print("- SDA y SCL están invertidos.")
        print("- El sensor no está alimentado.")
        print("- La dirección I2C no es 0x57.")
        print(f"Detalle técnico: {error}")

    except KeyboardInterrupt:
        print("\nPrueba detenida por el usuario.")


if __name__ == "__main__":
    main()