import win32serviceutil
import win32service
import win32event
import subprocess
import sys
import os

class TeslaMQTTService(win32serviceutil.ServiceFramework):
    _svc_name_ = "TeslaMQTTBridge"
    _svc_display_name_ = "Tesla MQTT Bridge"
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        # Use venv Python to run the script
        venv_python = r"C:\Users\Nebula PC\teslamate\venv\Scripts\python.exe"
        script = r"C:\Users\Nebula PC\teslamate\tesla_mqtt_bridge.py"
        
        while True:
            process = subprocess.Popen([venv_python, script])
            process.wait()
            if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                break

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(TeslaMQTTService)