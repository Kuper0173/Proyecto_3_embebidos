#!/usr/bin/env python3
"""
mpu6050_test.py

Prueba básica del sensor MPU6050 usando una Raspberry Pi por I2C.

El programa:
1. Abre el bus I2C de la Raspberry Pi.
2. Verifica el registro WHO_AM_I del MPU6050.
3. Inicializa acelerómetro y giroscopio.
4. Lee aceleración, velocidad angular y temperatura.
5. Muestra los datos en consola en tiempo real.

Conexión típica:
MPU6050 VCC -> Raspberry Pi 3.3 V
MPU6050 GND -> Raspberry Pi GND
MPU6050 SDA -> GPIO2 / SDA1
MPU6050 SCL -> GPIO3 / SCL1
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from smbus2 import SMBus


# Dirección I2C típica del MPU6050.
# Si AD0 está conectado a GND, la dirección suele ser 0x68.
# Si AD0 está conectado a 3.3 V, la dirección suele ser 0x69.
MPU6050_DEFAULT_ADDRESS = 0x68

# Registros principales del MPU6050.
REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_PWR_MGMT_1 = 0x6B
REG_WHO_AM_I = 0x75

# Factores de escala para la configuración elegida:
# Acelerómetro en ±2 g  -> 16384 LSB/g
# Giroscopio en ±250 °/s -> 131 LSB/(°/s)
ACCEL_SCALE_2G = 16384.0
GYRO_SCALE_250_DPS = 131.0


@dataclass
class MPU6050Sample:
    """Estructura para almacenar una muestra del MPU6050."""

    ax_g: float
    ay_g: float
    az_g: float
    gx_dps: float
    gy_dps: float
    gz_dps: float
    temp_c: float


def combine_signed_16(msb: int, lsb: int) -> int:
    """
    Combina dos bytes en un entero de 16 bits con signo.

    El MPU6050 entrega cada medición en dos registros:
    - Byte alto: bits [15:8]
    - Byte bajo: bits [7:0]

    Los datos vienen en complemento a dos.
    """

    value = (msb << 8) | lsb

    if value & 0x8000:
        value -= 0x10000

    return value


class MPU6050:
    """Driver mínimo para inicializar y leer el MPU6050 por I2C."""

    def __init__(self, bus: SMBus, address: int = MPU6050_DEFAULT_ADDRESS) -> None:
        self.bus = bus
        self.address = address

    def write_register(self, register: int, value: int) -> None:
        """Escribe un byte en un registro del MPU6050."""
        self.bus.write_byte_data(self.address, register, value)

    def read_register(self, register: int) -> int:
        """Lee un byte desde un registro del MPU6050."""
        return self.bus.read_byte_data(self.address, register)

    def read_block(self, start_register: int, length: int) -> list[int]:
        """Lee varios bytes consecutivos desde el MPU6050."""
        return self.bus.read_i2c_block_data(self.address, start_register, length)

    def check_identity(self) -> int:
        """
        Lee el registro WHO_AM_I.

        En un MPU6050 típico debe devolver 0x68.
        """
        return self.read_register(REG_WHO_AM_I)

    def initialize(self) -> None:
        """
        Inicializa el MPU6050 con una configuración simple y estable.

        Configuración:
        - Despierta el sensor.
        - Usa el giroscopio X como referencia de reloj.
        - Activa filtro digital pasa-bajas.
        - Configura frecuencia de muestreo aproximada de 100 Hz.
        - Acelerómetro en ±2 g.
        - Giroscopio en ±250 °/s.
        """

        # Reset del dispositivo.
        self.write_register(REG_PWR_MGMT_1, 0x80)
        time.sleep(0.100)

        # Despertar el sensor y seleccionar reloj basado en giroscopio X.
        # Bit SLEEP = 0, CLKSEL = 001.
        self.write_register(REG_PWR_MGMT_1, 0x01)
        time.sleep(0.100)

        # Filtro digital pasa-bajas.
        # 0x03 es una configuración razonable para reducir ruido.
        self.write_register(REG_CONFIG, 0x03)

        # Frecuencia de muestreo:
        # Con DLPF activo, base aproximada de 1 kHz.
        # sample_rate = 1000 / (1 + SMPLRT_DIV)
        # Para 100 Hz: SMPLRT_DIV = 9.
        self.write_register(REG_SMPLRT_DIV, 9)

        # Giroscopio ±250 °/s.
        # FS_SEL = 0.
        self.write_register(REG_GYRO_CONFIG, 0x00)

        # Acelerómetro ±2 g.
        # AFS_SEL = 0.
        self.write_register(REG_ACCEL_CONFIG, 0x00)

        time.sleep(0.100)

    def read_sample(self) -> MPU6050Sample:
        """
        Lee acelerómetro, temperatura y giroscopio.

        Desde ACCEL_XOUT_H se leen 14 bytes:
        0-1: aceleración X
        2-3: aceleración Y
        4-5: aceleración Z
        6-7: temperatura
        8-9: giroscopio X
        10-11: giroscopio Y
        12-13: giroscopio Z
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


def parse_arguments() -> argparse.Namespace:
    """Procesa argumentos de línea de comandos."""

    parser = argparse.ArgumentParser(
        description="Prueba del MPU6050 en Raspberry Pi usando I2C."
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
        default=MPU6050_DEFAULT_ADDRESS,
        help="Dirección I2C del MPU6050. Ejemplo: 0x68 o 0x69.",
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

    return parser.parse_args()


def main() -> None:
    """Función principal del programa."""

    args = parse_arguments()

    if args.rate <= 0:
        raise ValueError("La frecuencia --rate debe ser mayor que cero.")

    period_s = 1.0 / args.rate

    print("Iniciando prueba del MPU6050")
    print(f"Bus I2C: /dev/i2c-{args.bus}")
    print(f"Dirección I2C: 0x{args.address:02X}")
    print("Presiona Ctrl+C para detener.\n")

    try:
        with SMBus(args.bus) as bus:
            mpu = MPU6050(bus=bus, address=args.address)

            who_am_i = mpu.check_identity()
            print(f"WHO_AM_I leído: 0x{who_am_i:02X}")

            if who_am_i != 0x68:
                print(
                    "Advertencia: WHO_AM_I no devolvió 0x68. "
                    "Verifica dirección I2C, cableado y alimentación."
                )

            mpu.initialize()
            print("MPU6050 inicializado correctamente.\n")

            print(
                "Tiempo[s] | "
                "Ax[g]     Ay[g]     Az[g]     | "
                "Gx[°/s]   Gy[°/s]   Gz[°/s]   | "
                "Temp[°C]"
            )
            print("-" * 86)

            start_time = time.monotonic()

            while True:
                elapsed_s = time.monotonic() - start_time

                if args.duration > 0 and elapsed_s >= args.duration:
                    break

                sample = mpu.read_sample()

                print(
                    f"{elapsed_s:8.2f} | "
                    f"{sample.ax_g:8.3f} {sample.ay_g:8.3f} {sample.az_g:8.3f} | "
                    f"{sample.gx_dps:8.3f} {sample.gy_dps:8.3f} {sample.gz_dps:8.3f} | "
                    f"{sample.temp_c:8.2f}"
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
        print("- El MPU6050 no está conectado correctamente.")
        print("- I2C no está habilitado.")
        print("- La dirección I2C no es 0x68 sino 0x69.")
        print("- SDA o SCL están invertidos.")
        print("- El sensor no está alimentado.")
        print(f"Detalle técnico: {error}")

    except KeyboardInterrupt:
        print("\nPrueba detenida por el usuario.")


if __name__ == "__main__":
    main()