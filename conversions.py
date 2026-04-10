# conversions.py

def celsius_to_fahrenheit(c):
    """Convert a temperature from Celsius to Fahrenheit."""
    return (c * 9/5) + 32

def fahrenheit_to_celsius(f):
    """Convert a temperature from Fahrenheit to Celsius."""
    return (f - 32) * 5/9

def celsius_to_kelvin(c):
    """Convert a temperature from Celsius to Kelvin."""
    return c + 273.15

def kelvin_to_celsius(k):
    """Convert a temperature from Kelvin to Celsius."""
    return k - 273.15

def fahrenheit_to_kelvin(f):
    """Convert a temperature from Fahrenheit to Kelvin."""
    return celsius_to_kelvin(fahrenheit_to_celsius(f))

def kelvin_to_fahrenheit(k):
    """Convert a temperature from Kelvin to Fahrenheit."""
    return celsius_to_fahrenheit(kelvin_to_celsius(k))
