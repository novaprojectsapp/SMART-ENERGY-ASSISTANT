def validate_reading(reading) -> list[str]:
    errors = []

    if reading.voltage < 0 or reading.voltage > 500:
        errors.append(f"Voltage {reading.voltage}V out of range (0-500V)")

    if reading.current < 0 or reading.current > 100:
        errors.append(f"Current {reading.current}A out of range (0-100A)")

    if reading.power < 0 or reading.power > 50000:
        errors.append(f"Power {reading.power}W out of range (0-50000W)")

    if reading.energy < 0:
        errors.append(f"Energy {reading.energy}kWh must be non-negative")

    if reading.frequency < 0 or reading.frequency > 100:
        errors.append(f"Frequency {reading.frequency}Hz out of range (0-100Hz)")

    if reading.power_factor < 0 or reading.power_factor > 1.0:
        errors.append(f"Power factor {reading.power_factor} out of range (0-1.0)")

    return errors
