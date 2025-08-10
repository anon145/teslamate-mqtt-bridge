import json
import websockets
import asyncio
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv
import csv
import re
import sys
import ssl
import logging
from typing import Dict, List, Optional, Union, Any
import random
import time
import signal
import argparse

# Global connections dictionary
connections: Dict[str, Any] = {}

# Set up logging
def setup_logging(debug=False):
    """Configure logging based on debug flag"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('tesla_mqtt_bridge')

# Add this line right after the function
logger = logging.getLogger('tesla_mqtt_bridge')

# Track discovered fields for new sensor logging
discovered_fields = set()

# Load environment variables
load_dotenv()  # Load .env file

# MQTT setup
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "myteslamate/cars")

# Connection settings
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", 5))
PING_INTERVAL = int(os.getenv("PING_INTERVAL", 10))
PING_TIMEOUT = int(os.getenv("PING_TIMEOUT", 30))

# Add this near your other environment variables
TESLA_API_TOKEN = os.getenv("TESLA_API_TOKEN", "")

# Load VINs from environment variables
VINS = {}
for i in range(1, 10):  # Support up to 10 cars
    vin_key = f"VIN_CAR_{i}"
    if vin_value := os.getenv(vin_key):
        VINS[vin_value] = i
        logger.info(f"Loaded VIN for car {i}")

# Check if we have any VINs configured
# Skip VIN requirement during testing (GitHub Actions, pytest, etc.)
TESTING = any([
    "PYTEST_CURRENT_TEST" in os.environ,
    "GITHUB_ACTIONS" in os.environ,
    "CI" in os.environ
])

if not VINS and not TESTING:
    logger.error("No VINs configured. Please add VIN_CAR_1, VIN_CAR_2, etc. to your .env file")
    sys.exit(1)
elif not VINS and TESTING:
    # Use dummy VINs for testing
    VINS = {"TESTVIN123456789": 1, "TESTVIN987654321": 2}
    logger.info("Using dummy VINs for testing environment")

# Tesla API settings
TESLA_WSS_URI = os.getenv("TESLA_WSS_URI", "wss://streaming.myteslamate.com/streaming/")
TESLA_WSS_TLS_ACCEPT_INVALID_CERTS = os.getenv("TESLA_WSS_TLS_ACCEPT_INVALID_CERTS", "true").lower() == "true"
TESLA_WSS_USE_VIN = os.getenv("TESLA_WSS_USE_VIN", "true").lower() == "true"

# Conversion functions
def miles_to_km(miles: Optional[Union[float, int, str]]) -> Optional[float]:
    """Convert miles to kilometers"""
    if miles is None or miles == "":
        return None
    try:
        miles_float = float(miles)
        km = miles_float * 1.60934
        return round(km, 2)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert miles to km: {miles} - {e}")
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
    
    def __init__(self, csv_file: Optional[str] = None):
        if csv_file is None:
            # Use absolute path relative to this script's location
            script_dir = os.path.dirname(os.path.abspath(__file__))
            csv_file = os.path.join(script_dir, 'fleet_streaming_fields.csv')
        self.field_mappings: Dict[str, str] = {}
        self.field_types: Dict[str, str] = {}
        self.field_categories: Dict[str, str] = {}
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
                        # Always use the field name from the CSV as the MQTT topic
                        self.field_mappings[field_name] = camel_to_snake(field_name)
                    
                    # Store the data type
                    self.field_types[field_name] = field_type
                    
                    # Store the category
                    self.field_categories[field_name] = category
                    
            logger.info(f"Successfully loaded field metadata from {csv_file}")
        except FileNotFoundError:
            logger.warning(f"CSV file {csv_file} not found, using default mappings")
            self._set_default_mappings()
        except Exception as e:
            logger.error(f"Error loading CSV {csv_file}: {e}")
            logger.info("Using default mappings instead")
            self._set_default_mappings()
    
    def _set_default_mappings(self):
        """Set up basic mappings if CSV loading fails"""
        # Setup distance field mappings
        for field in DISTANCE_FIELDS:
            self.field_mappings[field] = DISTANCE_FIELDS[field]
            self.field_types[field] = "real"
            self.field_categories[field] = "distance"
            
        # Setup speed field mappings
        for field in SPEED_FIELDS:
            self.field_mappings[field] = SPEED_FIELDS[field]
            self.field_types[field] = "real"
            self.field_categories[field] = "speed"
            
        # Setup location field mappings
        for field in LOCATION_FIELDS:
            self.field_mappings[field] = camel_to_snake(field)
            self.field_types[field] = "object"
            self.field_categories[field] = "location"
            
        # Setup temperature field mappings
        for field in TEMPERATURE_FIELDS:
            self.field_mappings[field] = camel_to_snake(field)
            self.field_types[field] = "real"  
            self.field_categories[field] = "temperature"
            
        logger.info("Default field mappings have been set up")
    
    def get_mqtt_topic(self, field_name: str) -> str:
        """Get MQTT topic for a field"""
        # Check if this is a new field we haven't seen before
        if field_name not in self.field_mappings and field_name not in discovered_fields:
            discovered_fields.add(field_name)
            mqtt_topic = camel_to_snake(field_name)
            logger.info(f"NEW SENSOR DISCOVERED: '{field_name}' -> MQTT topic: '{mqtt_topic}' - Add to your automation system")
            
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
        result: Dict[str, Any] = {
            "topic": mqtt_topic,
            "value": None,
            "formatted_value": ""
        }
        
        # Handle invalid values
        if "invalid" in value_obj and value_obj["invalid"] is True:
            logger.debug(f"Field {field_name} has invalid value: {value_obj}")
            
            # Still return empty result for MQTT (don't publish invalid data)
            return result
        
        # Extract raw value based on the type
        raw_value = None
        if "locationValue" in value_obj and field_name in LOCATION_FIELDS:
            raw_value = value_obj["locationValue"]
            result["value"] = raw_value
            result["formatted_value"] = json.dumps(raw_value)
            return result
        elif "shiftStateValue" in value_obj:  # Handle gear shift state
            # Convert ShiftStateP -> P, ShiftStateD -> D, etc.
            state_value = value_obj["shiftStateValue"]
            if state_value.startswith("ShiftState"):
                raw_value = state_value[10:]  # Extract just the P, D, R part
            else:
                raw_value = state_value
        elif "stringValue" in value_obj:
            raw_value = self.convert_value(field_name, value_obj["stringValue"])
        elif "doubleValue" in value_obj:
            raw_value = self.convert_value(field_name, value_obj["doubleValue"])
        elif "intValue" in value_obj:
            raw_value = self.convert_value(field_name, value_obj["intValue"])
        elif "boolValue" in value_obj:
            raw_value = bool(value_obj["boolValue"])
        elif "numberValue" in value_obj:
            raw_value = self.convert_value(field_name, value_obj["numberValue"])
        else:
            # Unknown value type
            logger.warning(f"Unknown value type for {field_name}: {value_obj}")
            return result
            
        # Now apply conversions
        if field_name in DISTANCE_FIELDS:
            # Convert miles to km
            result["value"] = miles_to_km(raw_value)
            result["topic"] = DISTANCE_FIELDS[field_name]
        elif field_name in SPEED_FIELDS:
            # Convert mph to km/h
            result["value"] = miles_to_km(raw_value)
            result["topic"] = SPEED_FIELDS[field_name]
        elif field_name in TEMPERATURE_FIELDS and isinstance(raw_value, (int, float)) and raw_value > 50:
            # Convert F to C
            result["value"] = fahrenheit_to_celsius(raw_value)
        else:
            result["value"] = raw_value
            
        result["formatted_value"] = self.format_value(field_name, result["value"])
        return result

# Create a class to handle MQTT operations
class MQTTHandler:
    def __init__(self, host, port, user=None, password=None, topic_prefix="myteslamate/cars"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.topic_prefix = topic_prefix
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        
        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        # Set up authentication if provided
        if self.user and self.password:
            self.client.username_pw_set(self.user, self.password)
            
        # Set reconnect parameters
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)
        self.client.enable_logger(logger)
        
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("Connected to MQTT broker successfully")
        else:
            logger.warning(f"Connected to MQTT broker with result code {rc}")
    
    def _on_disconnect(self, client, userdata, rc, packet_from_broker=None, v1_rc=None, properties=None):
        if rc == 0:
            logger.info("Disconnected from MQTT broker cleanly")
        else:
            logger.warning(f"Unexpected disconnect from MQTT broker with code {rc}")
    
    def connect(self):
        """Connect to the MQTT broker"""
        try:
            self.client.connect(self.host, self.port)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from the MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
    
    def publish(self, car_num, topic, value):
        """Publish a value to a topic for a specific car"""
        full_topic = f"{self.topic_prefix}/{car_num}/{topic}"
        self.client.publish(full_topic, value)
    
    def publish_state(self, car_num, state):
        """Publish the car state"""
        self.publish(car_num, "state", state)

# Add the missing ReconnectionManager class
class ReconnectionManager:
    """Manage reconnection attempts with exponential backoff and jitter"""
    
    def __init__(self, base_delay=5, max_delay=300, jitter=0.1):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.attempts = 0
        
    def reset(self):
        """Reset the attempt counter on successful connection"""
        self.attempts = 0
        
    def next_delay(self):
        """Calculate the next delay with jitter"""
        self.attempts += 1
        delay = min(self.base_delay * (2 ** (self.attempts - 1)), self.max_delay)
        # Add random jitter to avoid thundering herd problem
        jitter_amount = delay * self.jitter
        delay = delay + random.uniform(-jitter_amount, jitter_amount)
        return max(self.base_delay, delay)  # Ensure delay is never less than base

# Extract these functions from handle_single_vin and make them standalone
async def create_tesla_websocket(uri, ssl_context, ping_timeout, ping_interval):
    """Create and return a websocket connection to Tesla API"""
    try:
        return await websockets.connect(
            uri,
            ssl=ssl_context,
            ping_timeout=ping_timeout,
            ping_interval=ping_interval
        )
    except websockets.InvalidURI as e:
        logger.error(f"Invalid WebSocket URI: {uri} - {e}")
        raise
    except websockets.InvalidHandshake as e:
        logger.error(f"WebSocket handshake failed: {e}")
        raise
    except ssl.SSLError as e:
        logger.error(f"SSL error when connecting to {uri}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to {uri}: {e}")
        raise

async def subscribe_to_vehicle_data(websocket, id_or_vin, car_num):
    """Subscribe to all vehicle data and return success status"""
    sub_message = {
        "msg_type": "data:subscribe_all",
        "tag": id_or_vin,
        "token": TESLA_API_TOKEN  # Add your token here
    }
    
    logger.info(f"Sending subscription for car {car_num}: {sub_message}")
    await websocket.send(json.dumps(sub_message))
    
    try:
        response = await asyncio.wait_for(websocket.recv(), timeout=10)
        logger.info(f"Subscription response for car {car_num}: {response}")
        return True
    except asyncio.TimeoutError:
        logger.error(f"Timeout waiting for subscription confirmation for car {car_num}")
        return False

async def handle_single_vin(id_or_vin, car_num, mqtt_client, tesla_converter):
    """Handle connection and data streaming for a single vehicle"""
    reconnect_manager = ReconnectionManager()

    while True:
        try:
            # Use the configured endpoint
            uri = TESLA_WSS_URI
            
            logger.info(f"Connecting to {uri} for car {car_num}")
            
            # SSL context for invalid certs
            ssl_context = None
            if TESLA_WSS_TLS_ACCEPT_INVALID_CERTS:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create the websocket connection
            websocket = await create_tesla_websocket(
                uri, ssl_context, PING_TIMEOUT, PING_INTERVAL
            )
            
            try:
                # Reset reconnect attempts on successful connection
                reconnect_manager.reset()
                
                # Subscribe to vehicle data
                if await subscribe_to_vehicle_data(websocket, id_or_vin, car_num):
                    # Success - update MQTT state and listen for data
                    mqtt_client.publish_state(car_num, "online")
                    
                    # Main message processing loop
                    await handle_websocket_messages(websocket, car_num, id_or_vin, mqtt_client, tesla_converter)
            finally:
                # Ensure websocket is closed properly
                try:
                    # Simply attempt to close without checking closed attribute
                    await websocket.close()
                except Exception as e:
                    logger.debug(f"Error closing websocket for car {car_num}: {e}")
                            
        except asyncio.CancelledError:
            # Properly handle task cancellation
            logger.info(f"Task for car {car_num} was cancelled")
            mqtt_client.publish_state(car_num, "disconnected")
            # Re-raise to properly propagate the cancellation
            raise
        except Exception as e:
            # Handle reconnection with backoff
            delay = reconnect_manager.next_delay()
            
            # Log all errors except known websocket library issues
            if "has no attribute 'closed'" in str(e):
                logger.debug(f"Websocket library issue for car {car_num}: {e}")
            else:
                logger.error(f"Error for car {car_num}: {e}")
            logger.info(f"Reconnecting in {delay:.1f} seconds (attempt {reconnect_manager.attempts})")
            
            mqtt_client.publish_state(car_num, "error")
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # Handle cancellation during sleep
                logger.info(f"Reconnection for car {car_num} was cancelled")
                raise

# Add function to handle websocket messages
async def handle_websocket_messages(websocket, car_num, id_or_vin, mqtt_client, tesla_converter):
    """Handle messages from the websocket"""
    while True:
        try:
            message = await websocket.recv()
            if not await process_vehicle_message(message, car_num, id_or_vin, mqtt_client, tesla_converter, MQTT_TOPIC_PREFIX):
                return  # Exit if processing indicates we should stop
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection closed for car {car_num} with code {e.code}: {e.reason}")
            mqtt_client.publish_state(car_num, "disconnected")  # Use publish_state instead of direct publish
            return  # Exit on connection closed

async def process_vehicle_message(message, car_num, id_or_vin, mqtt_client, tesla_converter, topic_prefix):
    """Process a message from the vehicle and publish to MQTT"""
    try:
        data = json.loads(message)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON received for car {car_num}: {e}")
        return True
    
    # Log sanitized data (remove sensitive fields)
    sanitized_data = {k: v for k, v in data.items() if k not in ['token', 'auth', 'api_key']}
    logger.debug(f"RAW DATA for car {car_num}: {json.dumps(sanitized_data, indent=2)}")
    
    logger.debug(f"Received for car {car_num}: {message[:200]}...")
    
    # Handle TeslaMate-specific error responses
    if "error" in data:
        error_type = data.get("error", {}).get("type", "unknown")
        error_message = data.get("error", {}).get("message", "No details")
        
        if error_type in ["vehicle_disconnected", "vehicle_offline"]:
            logger.warning(f"Vehicle {id_or_vin} is {error_type}: {error_message}")
            mqtt_client.publish_state(car_num, error_type)
            return False
        else:
            logger.error(f"Unknown error for car {car_num}: {error_type} - {error_message}")
            return True

    # Handle control messages
    if "msg_type" in data and data["msg_type"].startswith("control:hello"):
        mqtt_client.publish_state(car_num, "online")
        return True
        
    # Handle direct JSON data format
    elif "data" in data and isinstance(data["data"], list):
        mqtt_client.publish_state(car_num, "online")
        
        # Process each field in the data
        try:
            for item in data["data"]:
                if "key" in item and "value" in item:
                    key = item["key"]
                    value_obj = item["value"]
                    
                    # Basic validation
                    if not isinstance(key, str) or not key.strip():
                        logger.debug(f"Invalid field key for car {car_num}: {key}")
                        continue
                    
                    # Process the field
                    result = tesla_converter.process_field(key, value_obj)
                    
                    # Publish to MQTT only if we have valid data
                    if result["formatted_value"] != "":
                        mqtt_client.publish(
                            car_num, 
                            result["topic"], 
                            result["formatted_value"]
                        )
            
            # Handle metadata
            if "vin" in data:
                mqtt_client.publish(car_num, "vin", data["vin"])
        except Exception as e:
            logger.error(f"Error processing data for car {car_num}: {e}")
            
        return True
    
    return True

async def main():
    # Initialize the converter
    tesla_converter = TeslaMetricConverter()
    
    # Initialize MQTT handler
    mqtt_handler = MQTTHandler(
        host=MQTT_HOST,
        port=MQTT_PORT,
        user=MQTT_USER,
        password=MQTT_PASS,
        topic_prefix=MQTT_TOPIC_PREFIX
    )
    
    # Connect to MQTT broker
    if not mqtt_handler.connect():
        logger.error("Failed to connect to MQTT broker, exiting")
        return
    
    # Get VINs from environment or use defaults
    vins = {}
    
    if TESLA_WSS_USE_VIN:
        vins = VINS
    else:
        # If not using VIN, just use car numbers directly
        vins = {str(i): i for i in range(1, len(VINS) + 1)}
    
    tasks = []
    for id_or_vin, car_num in vins.items():
        tasks.append(asyncio.create_task(handle_single_vin(id_or_vin, car_num, mqtt_handler, tesla_converter)))
    
    logger.info(f"Starting Tesla MQTT Bridge with {len(tasks)} vehicles")
    
    try:
        # Wait for all tasks to complete (they run forever or until cancelled)
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Tasks are being cancelled...")
        # Properly cancel all tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # Wait for all tasks to properly finish cancellation
        if tasks:
            try:
                # Wait with a timeout to avoid hanging indefinitely
                await asyncio.wait(tasks, timeout=5)
            except Exception as e:
                logger.debug(f"Error during task cancellation wait: {e}")
    finally:
        # Clean disconnect of MQTT
        mqtt_handler.disconnect()

# Add at the top of the file
__version__ = "0.2.0"

# Remove the unused is_connection_closed function
# def is_connection_closed(conn):
#     """Safely check if connection is closed."""
#     ...

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Tesla MQTT Bridge')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    # Setup logging with debug flag
    logger = setup_logging(args.debug)
    
    # Set up proper signal handlers
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal, terminating...")
        # Get the current event loop and create a task to cancel all running tasks
        try:
            loop = asyncio.get_running_loop()
            for task in asyncio.all_tasks(loop):
                task.cancel()
        except RuntimeError:
            # No running loop, exit normally
            sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info(f"Tesla MQTT Bridge v{__version__} starting up")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down cleanly...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
