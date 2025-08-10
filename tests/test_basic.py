"""Basic tests for Tesla MQTT Bridge"""
import pytest
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tesla_mqtt_bridge import camel_to_snake, miles_to_km, fahrenheit_to_celsius


class TestUtilityFunctions:
    """Test utility functions"""
    
    def test_camel_to_snake(self):
        """Test camelCase to snake_case conversion"""
        assert camel_to_snake("VehicleSpeed") == "vehicle_speed"
        assert camel_to_snake("EstBatteryRange") == "est_battery_range"
        assert camel_to_snake("ACChargingPower") == "ac_charging_power"
        assert camel_to_snake("TestCase") == "test_case"
        assert camel_to_snake("simple") == "simple"
    
    def test_miles_to_km(self):
        """Test miles to kilometers conversion"""
        assert miles_to_km(100) == 160.93
        assert miles_to_km(0) == 0.0
        assert miles_to_km(1) == 1.61
        assert miles_to_km(None) is None
        assert miles_to_km("") is None
        assert miles_to_km("invalid") is None
    
    def test_fahrenheit_to_celsius(self):
        """Test Fahrenheit to Celsius conversion"""
        assert fahrenheit_to_celsius(32) == 0.0
        assert fahrenheit_to_celsius(100) == 37.78
        assert fahrenheit_to_celsius(212) == 100.0
        assert fahrenheit_to_celsius(None) is None
        assert fahrenheit_to_celsius("") is None
        assert fahrenheit_to_celsius("invalid") is None


def test_imports():
    """Test that main modules can be imported"""
    try:
        import tesla_mqtt_bridge
        import final_service
        assert True
    except ImportError as e:
        pytest.fail(f"Failed to import modules: {e}")


def test_environment_variables():
    """Test environment variable handling"""
    # Test that the script can handle missing environment variables
    from tesla_mqtt_bridge import MQTT_HOST, MQTT_PORT, RECONNECT_DELAY
    
    # These should have defaults
    assert MQTT_HOST == "localhost"
    assert MQTT_PORT == 1883
    assert RECONNECT_DELAY >= 1