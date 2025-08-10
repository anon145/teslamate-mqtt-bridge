# Tesla MQTT Bridge

A Windows Service that bridges Tesla vehicle streaming data to MQTT, with automatic sensor discovery and metric conversion.

## Features

- **Windows Service**: Runs automatically on boot, restarts on crash
- **Automatic Sensor Discovery**: Logs new sensors as they appear in the stream
- **Metric Conversion**: Converts miles to km, Fahrenheit to Celsius
- **Multi-Vehicle Support**: Handles multiple Tesla vehicles simultaneously
- **MQTT Publishing**: Publishes sensor data to MQTT broker
- **Production Ready**: Includes proper logging, error handling, and reconnection logic

## Installation

### Prerequisites
- Python 3.13+ 
- Tesla streaming API access (TeslaMate or similar)
- MQTT broker

### Setup

1. **Clone the repository:**
   ```cmd
   git clone <your-repo-url>
   cd teslamate
   ```

2. **Create virtual environment:**
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   Create a `.env` file with:
   ```env
   # MQTT Configuration
   MQTT_HOST=localhost
   MQTT_PORT=1883
   MQTT_USER=your_mqtt_user
   MQTT_PASS=your_mqtt_password
   MQTT_TOPIC_PREFIX=myteslamate/cars

   # Tesla Configuration
   VIN_CAR_1=your_vin_here
   VIN_CAR_2=another_vin_here
   TESLA_API_TOKEN=your_token_here
   TESLA_WSS_URI=wss://streaming.myteslamate.com/streaming/

   # Connection Settings
   RECONNECT_DELAY=5
   PING_INTERVAL=10
   PING_TIMEOUT=30
   ```

4. **Install system dependencies:**
   ```cmd
   # As Administrator
   C:\python313\python.exe -m pip install paho-mqtt websockets python-dotenv pywin32
   ```

5. **Install Windows Service:**
   ```cmd
   # As Administrator
   C:\python313\python.exe final_service.py install
   ```

6. **Start the service:**
   ```cmd
   net start TeslaMQTTBridge
   ```

## Usage

### Service Management
- **Start**: `net start TeslaMQTTBridge`
- **Stop**: `net stop TeslaMQTTBridge` 
- **Status**: `sc query TeslaMQTTBridge`
- **Remove**: `C:\python313\python.exe final_service.py remove`

### Testing
Run the bridge directly for testing:
```cmd
venv\Scripts\activate
python tesla_mqtt_bridge.py --debug
```

### Sensor Discovery
The bridge automatically discovers new sensors and logs them:
```
INFO - NEW SENSOR DISCOVERED: 'InsideTemp' -> MQTT topic: 'inside_temp' - Add to your automation system
```

## MQTT Topics

Data is published to: `{MQTT_TOPIC_PREFIX}/{car_number}/{sensor_name}`

Example topics:
- `myteslamate/cars/1/battery_range_estimated_km`
- `myteslamate/cars/1/speed_kmh` 
- `myteslamate/cars/1/soc`
- `myteslamate/cars/1/location`

## Configuration

### Sensor Mapping
The bridge includes automatic conversion for:
- **Distance**: Miles → Kilometers
- **Speed**: MPH → KM/H  
- **Temperature**: Fahrenheit → Celsius (when > 50°)

### Field Categories
See `fleet_streaming_fields.csv` for available Tesla streaming fields.

## Troubleshooting

1. **Check service status**: `sc query TeslaMQTTBridge`
2. **View logs**: Check Windows Event Viewer
3. **Test manually**: Run `python tesla_mqtt_bridge.py --debug`
4. **Verify connectivity**: Test MQTT and Tesla endpoints

## License

MIT License - see LICENSE file for details.