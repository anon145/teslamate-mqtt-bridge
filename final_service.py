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
        self.running = True
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        
        # Terminate the subprocess gracefully
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                # Wait up to 10 seconds for graceful shutdown
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop gracefully
                self.process.kill()
                self.process.wait()
        
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        import time
        
        # Use venv Python to run the script
        venv_python = r"C:\Users\Nebula PC\teslamate\venv\Scripts\python.exe"
        script = r"C:\Users\Nebula PC\teslamate\tesla_mqtt_bridge.py"
        
        while self.running:
            try:
                self.process = subprocess.Popen([venv_python, script])
                
                # Wait for process to finish or stop signal
                while self.process.poll() is None and self.running:
                    if win32event.WaitForSingleObject(self.hWaitStop, 1000) == win32event.WAIT_OBJECT_0:
                        break
                    time.sleep(0.1)
                
                if not self.running:
                    break
                    
                # Process died, wait before restart if still running
                if self.running:
                    if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                        break
                        
            except Exception as e:
                if self.running:
                    time.sleep(5)  # Wait before retry

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(TeslaMQTTService)