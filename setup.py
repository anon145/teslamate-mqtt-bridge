from setuptools import setup, find_packages

setup(
    name="tesla-mqtt-bridge",
    version="0.2.0",
    description="Tesla MQTT Bridge Windows Service",
    author="anon145",
    packages=find_packages(),
    py_modules=['tesla_mqtt_bridge', 'final_service'],
    python_requires=">=3.9",
    install_requires=[
        "paho-mqtt>=2.0.0",
        "websockets>=11.0.0", 
        "python-dotenv>=1.0.0",
        "pywin32>=306; sys_platform == 'win32'"
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0"
        ]
    }
)