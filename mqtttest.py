import json
import base64
import websockets
import asyncio
import paho.mqtt.client as mqtt
from datetime import datetime
import os
from dotenv import load_dotenv
import csv
import re
from typing import Dict, List, Optional, Union, Any

load_dotenv()  # Load .env file

# MQTT setup
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # Fix deprecation warning
if MQTT_USER and MQTT_PASS:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.connect(MQTT_HOST, MQTT_PORT)
mqtt_client.loop_start()

VINS = {
    "LRW3F7EK3RC076464": 1,  # car 1
    "LRW3F7ET5RC298707": 2   # car 2
}


TESLA_WSS_TLS_ACCEPT_INVALID_CERTS = os.getenv("TESLA_WSS_TLS_ACCEPT_INVALID_CERTS", "true")
TESLA_WSS_USE_VIN = os.getenv("TESLA_WSS_USE_VIN", "true")

# Conversion functions
def miles_to_km(miles: Optional[Union[float, int, str]]) -> Optional[float]:
    """Convert miles to kilometers"""
    if miles is None or miles == "":
        return None
    try:
        return round(float(miles) * 1.60934, 2)
    except (ValueError, TypeError):
        return None

def fahrenheit_to_celsius(f: Optional[Union[float, int, str]]) -> Optional[float]:
    """Convert Fahrenheit to Celsius"""
    if f is None or f == "":
        return None
    try:
        return round((float(f) - 32) * 5/9, 2)
    except (ValueError, TypeError):
        return None

def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case"""
    # Handle acronyms first (e.g., ACChargingPower -> ac_charging_power)
    s1 = re.sub(r'([A-Z][A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    # Then handle normal camelCase
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

# Define field categories that need conversion
DISTANCE_FIELDS = {
    "EstBatteryRange": "battery_range_estimated_km",
    "IdealBatteryRange": "battery_range_ideal_km",
    "RatedRange": "battery_range_rated_km",
    "RangeDisplay": "battery_range_display_km",
    "MilesToArrival": "navigation_distance_remaining_km",
    "MilesRemaining": "navigation_distance_remaining_km",
    "Odometer": "odometer_km",
    "ChargeRateMilePerHour": "charge_rate_kmh",
    "DistanceToArrival": "navigation_distance_remaining_km"
}

SPEED_FIELDS = {
    "VehicleSpeed": "speed_kmh",
    "CruiseSetSpeed": "cruise_speed_kmh",
    "CurrentLimitMph": "speed_limit_kmh",
    "SpeedLimit": "speed_limit_kmh",
    "SpeedLimitDisplay": "speed_limit_display_kmh",
    "SpeedLimitMode": "speed_limit_mode_kmh"
}

TEMPERATURE_FIELDS = ["OutsideTemp", "InsideTemp"]
LOCATION_FIELDS = ["Location", "DestinationLocation", "OriginLocation"]

class TeslaMetricConverter:
    """Class for handling Tesla metric conversions"""
    
    def __init__(self, csv_file: str = 'fleet_streaming_fields.csv'):
        self.field_mappings = {}
        self.field_types = {}
        self.field_categories = {}
        self._load_field_metadata(csv_file)
    
    def _load_field_metadata(self, csv_file: str) -> None:
        """Load field metadata from CSV file"""
        try:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    field_name = row['Field'].strip('"')
                    vehicle_equiv = row['Vehicle Data Equivalent'].strip('"')
                    field_type = row['Type'].strip('"').lower()
                    category = row['Category'].strip('"').lower()
                    
                    # Determine MQTT topic name
                    if field_name in DISTANCE_FIELDS:
                        # Use predefined mapping for distance fields
                        self.field_mappings[field_name] = DISTANCE_FIELDS[field_name]
                    elif field_name in SPEED_FIELDS:
                        # Use predefined mapping for speed fields
                        self.field_mappings[field_name] = SPEED_FIELDS[field_name]
                    elif field_name in LOCATION_FIELDS:
                        # Keep location fields as single topics
                        self.field_mappings[field_name] = camel_to_snake(field_name)
                    else:
                        # Use vehicle equivalent if available, otherwise convert field name
                        if vehicle_equiv:
                            base_name = vehicle_equiv.split('.')[-1]
                            self.field_mappings[field_name] = camel_to_snake(base_name)
                        else:
                            self.field_mappings[field_name] = camel_to_snake(field_name)
                    
                    # Store the data type
                    self.field_types[field_name] = field_type
                    
                    # Store the category
                    self.field_categories[field_name] = category
        except Exception as e:
            print(f"Error loading CSV: {e}")
            # Set up basic mappings even if CSV load fails
            for field in DISTANCE_FIELDS:
                self.field_mappings[field] = DISTANCE_FIELDS[field]
            for field in SPEED_FIELDS:
                self.field_mappings[field] = SPEED_FIELDS[field]
            for field in LOCATION_FIELDS:
                self.field_mappings[field] = camel_to_snake(field)
    
    def get_mqtt_topic(self, field_name: str) -> str:
        """Get MQTT topic for a field"""
        return self.field_mappings.get(field_name, camel_to_snake(field_name))
    
    def convert_value(self, field_name: str, value: Any) -> Any:
        """Convert raw value to appropriate type based on field metadata"""
        if value is None or value == "":
            return None
            
        if field_name not in self.field_types:
            # Default conversion for unknown fields
            try:
                float_val = float(value) if '.' in str(value) else int(value)
                # Round to 2 decimal places for float values
                if isinstance(float_val, float) and field_name not in LOCATION_FIELDS:
                    return round(float_val, 2)
                return float_val
            except (ValueError, TypeError):
                return value
                
        field_type = self.field_types[field_name]
        
        if field_type == "real":
            try:
                float_val = float(value)
                # Round to 2 decimal places for most values except location
                if field_name not in LOCATION_FIELDS:
                    return round(float_val, 2)
                return float_val
            except (ValueError, TypeError):
                return None
        elif field_type == "integer":
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return None
        elif field_type == "boolean":
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ["true", "1", "yes"]
            return bool(value)
        else:
            # For enum, string, etc.
            return str(value) if value is not None else None
    
    def convert_to_metric(self, field_name: str, value: Any) -> Any:
        """Apply metric conversions to a value"""
        if value is None or value == "":
            return None
            
        # Apply unit conversions
        if field_name in DISTANCE_FIELDS:
            return miles_to_km(value)
        elif field_name in SPEED_FIELDS:
            return miles_to_km(value)  # mph to kmh is same conversion
        elif field_name in TEMPERATURE_FIELDS:
            # Likely Fahrenheit if above 50
            if isinstance(value, (int, float)) and value > 50:
                return fahrenheit_to_celsius(value)
        
        # No conversion needed but ensure consistent rounding for numeric values
        if isinstance(value, float) and field_name not in LOCATION_FIELDS:
            return round(value, 2)
        return value
    
    def format_value(self, field_name: str, value: Any) -> str:
        """Format value for MQTT publishing"""
        if value is None:
            return ""
        
        if field_name in LOCATION_FIELDS and isinstance(value, dict):
            return json.dumps(value)
        
        if isinstance(value, float):
            return f"{value:.2f}"
        
        return str(value)
    
    def process_field(self, field_name: str, value_obj: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single field and return information for MQTT publishing"""
        mqtt_topic = self.get_mqtt_topic(field_name)
        result = {
            "topic": mqtt_topic,
            "value": None,
            "formatted_value": ""
        }
        
        # Handle different value types
        if "locationValue" in value_obj and field_name in LOCATION_FIELDS:
            # Keep location as a single entity with its original structure
            result["value"] = value_obj["locationValue"]
            result["formatted_value"] = json.dumps(value_obj["locationValue"])
        elif "stringValue" in value_obj:
            # Convert according to expected type
            raw_value = self.convert_value(field_name, value_obj["stringValue"])
            
            # Check if this string value needs conversion (can happen for odometer)
            if field_name in DISTANCE_FIELDS:
                # Convert miles to km for distance values coming as strings
                converted_value = miles_to_km(raw_value)
                result["topic"] = DISTANCE_FIELDS[field_name]  # Use the predefined km topic
                result["value"] = converted_value
            else:
                result["value"] = raw_value
            
            result["formatted_value"] = self.format_value(field_name, result["value"])
        elif "numberValue" in value_obj:
            # First convert to appropriate type
            raw_value = self.convert_value(field_name, value_obj["numberValue"])
            
            # Apply metric conversion
            if field_name in DISTANCE_FIELDS:
                # Convert miles to km
                converted_value = miles_to_km(raw_value)
                result["topic"] = DISTANCE_FIELDS[field_name]  # Use the predefined km topic
                result["value"] = converted_value
            elif field_name in SPEED_FIELDS:
                # Convert mph to km/h
                converted_value = miles_to_km(raw_value)
                result["topic"] = SPEED_FIELDS[field_name]  # Use the predefined km/h topic
                result["value"] = converted_value
            elif field_name in TEMPERATURE_FIELDS and isinstance(raw_value, (int, float)) and raw_value > 50:
                # Convert F to C for temps over 50
                result["value"] = fahrenheit_to_celsius(raw_value)
            else:
                result["value"] = raw_value
                
            result["formatted_value"] = self.format_value(field_name, result["value"])
        
        return result

# Initialize the converter
tesla_converter = TeslaMetricConverter()

async def handle_single_vin(id_or_vin, car_num):
    while True:
        try:
            # Use the exact endpoint from Postman collection
            uri = "wss://streaming.myteslamate.com/streaming/"
            
            print(f"Connecting to {uri} for car {car_num}")
            
            # SSL context for invalid certs
            ssl_context = None
            if TESLA_WSS_TLS_ACCEPT_INVALID_CERTS.lower() == "true":
                import ssl
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            async with websockets.connect(
                uri,
                ssl=ssl_context,
                ping_timeout=30,
                ping_interval=10
            ) as websocket:
                # Use data:subscribe_all and VIN as tag
                sub_message = {
                    "msg_type": "data:subscribe_all",
                    "tag": id_or_vin
                }
                
                print(f"Sending subscription for car {car_num}: {sub_message}")
                await websocket.send(json.dumps(sub_message))
                
                # Wait for subscription confirmation
                response = await websocket.recv()
                print(f"Subscription response for car {car_num}: {response}")
                
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        # Print raw message for debugging
                        print(f"Received for car {car_num}: {message}")
                        
                        # Handle TeslaMate-specific error responses
                        if "error" in data:
                            error_type = data.get("error", {}).get("type")
                            if error_type in ["vehicle_disconnected", "vehicle_offline"]:
                                print(f"Vehicle {id_or_vin} is {error_type}")
                                mqtt_client.publish(f"myteslamate/cars/{car_num}/state", error_type)
                                await asyncio.sleep(30)  # Wait before retry
                                break
                            else:
                                print(f"Unknown error for car {car_num}: {data}")
                                continue

                        # Handle control messages
                        if "msg_type" in data and data["msg_type"].startswith("control:hello"):
                            # Just a keepalive - publish status but don't process data
                            mqtt_client.publish(f"myteslamate/cars/{car_num}/state", "online")
                            
                        # Handle direct JSON data format
                        elif "data" in data and isinstance(data["data"], list):
                            # Set online status first
                            mqtt_client.publish(f"myteslamate/cars/{car_num}/state", "online")
                            
                            # Process each field in the data
                            for item in data["data"]:
                                if "key" in item and "value" in item:
                                    key = item["key"]
                                    value_obj = item["value"]
                                    
                                    # Process the field
                                    result = tesla_converter.process_field(key, value_obj)
                                    
                                    # Publish to MQTT
                                    mqtt_client.publish(
                                        f"myteslamate/cars/{car_num}/{result['topic']}", 
                                        result['formatted_value']
                                    )
                            
                            # Handle metadata
                            if "vin" in data:
                                mqtt_client.publish(f"myteslamate/cars/{car_num}/vin", data["vin"])
                            
                    except websockets.ConnectionClosed:
                        print(f"Connection closed for car {car_num}, reconnecting...")
                        mqtt_client.publish(f"myteslamate/cars/{car_num}/state", "disconnected")
                        break
                        
        except Exception as e:
            print(f"Error for car {car_num}: {e}")
            mqtt_client.publish(f"myteslamate/cars/{car_num}/state", "error")
            await asyncio.sleep(5)

async def main():
    # Get VINs from environment or use defaults
    vins = {}
    use_vin = TESLA_WSS_USE_VIN.lower() == "true"
    
    if use_vin:
        vins = VINS
    else:
        # If not using VIN, just use car numbers directly
        vins = {1: 1, 2: 2}
    
    tasks = []
    for id_or_vin, car_num in vins.items():
        tasks.append(handle_single_vin(id_or_vin, car_num))
    
    # Run connections concurrently
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
