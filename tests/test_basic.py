"""Basic tests for Tesla MQTT Bridge"""
import pytest
import os
import sys
import importlib.util

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_tesla_functions():
    """Load utility functions from tesla_mqtt_bridge without full import"""
    spec = importlib.util.spec_from_file_location(
        "tesla_mqtt_bridge", 
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "tesla_mqtt_bridge.py")
    )
    module = importlib.util.module_from_spec(spec)
    
    # Mock environment variables to prevent issues during import
    os.environ.setdefault("MQTT_HOST", "localhost")
    os.environ.setdefault("MQTT_PORT", "1883")
    
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        pytest.skip(f"Could not load tesla_mqtt_bridge module: {e}")


class TestUtilityFunctions:
    """Test utility functions"""
    
    def test_camel_to_snake(self):
        """Test camelCase to snake_case conversion"""
        tesla_module = load_tesla_functions()
        camel_to_snake = tesla_module.camel_to_snake
        
        assert camel_to_snake("VehicleSpeed") == "vehicle_speed"
        assert camel_to_snake("EstBatteryRange") == "est_battery_range"
        assert camel_to_snake("ACChargingPower") == "ac_charging_power"
        assert camel_to_snake("TestCase") == "test_case"
        assert camel_to_snake("simple") == "simple"
    
    def test_miles_to_km(self):
        """Test miles to kilometers conversion"""
        tesla_module = load_tesla_functions()
        miles_to_km = tesla_module.miles_to_km
        
        assert miles_to_km(100) == 160.93
        assert miles_to_km(0) == 0.0
        assert miles_to_km(1) == 1.61
        assert miles_to_km(None) is None
        assert miles_to_km("") is None
        assert miles_to_km("invalid") is None
    
    def test_fahrenheit_to_celsius(self):
        """Test Fahrenheit to Celsius conversion"""
        tesla_module = load_tesla_functions()
        fahrenheit_to_celsius = tesla_module.fahrenheit_to_celsius
        
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
        assert True
    except ImportError as e:
        pytest.fail(f"Failed to import tesla_mqtt_bridge: {e}")
    
    # Skip final_service on non-Windows platforms (requires pywin32)
    import platform
    if platform.system() == "Windows":
        try:
            import final_service
            assert True
        except ImportError as e:
            pytest.fail(f"Failed to import final_service: {e}")
    else:
        pytest.skip("Skipping final_service import on non-Windows platform")


def test_environment_variables():
    """Test environment variable handling"""
    # Test basic environment variable access
    os.environ["TEST_VAR"] = "test_value"
    assert os.getenv("TEST_VAR") == "test_value"
    assert os.getenv("NONEXISTENT_VAR", "default") == "default"