import requests
import subprocess
import time
import uuid
import os
import logging
import random
import string

logger = logging.getLogger(__name__)

class MoreLoginMobileManager:
    BASE_URL = "http://127.0.0.1:40000"

    @classmethod
    def get_first_cloud_phone(cls) -> dict | None:
        try:
            res = requests.post(f"{cls.BASE_URL}/api/cloudphone/page", json={})
            data = res.json().get("data", {})
            phones = data.get("dataList", [])
            if phones:
                return phones[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching cloud phones: {e}")
            return None

    @classmethod
    def rotate_proxy(cls, phone: dict):
        try:
            # DataImpulse rotating proxy - append random session to username
            proxy = phone.get("proxy", {})
            if not proxy: return
            
            import json
            proxy_info_str = proxy.get("proxyInfo", "{}")
            proxy_info = json.loads(proxy_info_str)
            
            username = proxy_info.get("username", "")
            if "session-" in username:
                base_usr = username.split("session-")[0]
            else:
                base_usr = username + ("_" if username else "")
                
            new_session = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            new_username = f"{base_usr}session-{new_session}"
            
            # Send update to MoreLogin API
            requests.post(f"{cls.BASE_URL}/api/cloudphone/update", json={
                "id": phone.get("id"),
                "proxyIp": proxy.get("proxyIp"),
                "proxyPort": proxy.get("proxyPort"),
                "proxyType": proxy.get("proxyType"),
                "proxyUsername": new_username,
                "proxyPassword": proxy_info.get("password"),
            })
            logger.info("Proxy rotated via MoreLogin API.")
        except Exception as e:
            logger.error(f"Failed to rotate proxy: {e}")

    @classmethod
    def enable_adb(cls, phone_id: str):
        try:
            requests.post(f"{cls.BASE_URL}/api/cloudphone/updateAdb", json={
                "ids": [int(phone_id) if str(phone_id).isdigit() else phone_id],
                "enableAdb": "true"
            })
        except Exception as e:
            logger.error(f"Error enabling ADB: {e}")

    @classmethod
    def start_phone(cls, phone_id: str):
        try:
            logger.info(f"Starting cloud phone {phone_id}...")
            requests.post(f"{cls.BASE_URL}/api/cloudphone/start", json={
                "ids": [phone_id]
            })
        except Exception as e:
            logger.error(f"Error starting phone: {e}")

    @classmethod
    def stop_phone(cls, phone_id: str):
        try:
            logger.info(f"Stopping cloud phone {phone_id}...")
            requests.post(f"{cls.BASE_URL}/api/cloudphone/stop", json={
                "ids": [phone_id]
            })
        except Exception as e:
            logger.error(f"Error stopping phone: {e}")

    @classmethod
    def connect_adb(cls, adb_ip: str, adb_port: str, adb_pass: str) -> bool:
        addr = f"{adb_ip}:{adb_port}"
        subprocess.run(["adb", "disconnect", addr], capture_output=True)
        res = subprocess.run(["adb", "connect", addr], capture_output=True, text=True)
        if "connected" in res.stdout.lower() or "already" in res.stdout.lower():
            if adb_pass:
                subprocess.run(["adb", "-s", addr, "shell", adb_pass], capture_output=True)
            return True
        return False
        
    @classmethod
    def wipe_app(cls, addr: str, package: str = "com.volaris.app"):
        """Clears all app data (cookies, storage, cache), acting like a fresh reinstall"""
        logger.info(f"Wiping data for {package}...")
        subprocess.run(["adb", "-s", addr, "shell", "pm", "clear", package], capture_output=True)

    @classmethod
    def pull_screenshot(cls, addr: str, filename_prefix: str) -> str:
        remote_path = "/sdcard/screen.png"
        subprocess.run(["adb", "-s", addr, "shell", "screencap", "-p", remote_path], capture_output=True)
        local_path = f"boarding_passes/{filename_prefix}_{uuid.uuid4().hex[:8]}.png"
        os.makedirs("boarding_passes", exist_ok=True)
        subprocess.run(["adb", "-s", addr, "pull", remote_path, local_path], capture_output=True)
        subprocess.run(["adb", "-s", addr, "shell", "rm", remote_path], capture_output=True)
        return local_path

    @classmethod
    def wait_for_adb_details(cls, phone_id: str, timeout: int = 120) -> tuple[str, str, str]:
        start = time.time()
        while time.time() - start < timeout:
            phone = cls.get_first_cloud_phone()
            if not phone:
                time.sleep(5)
                continue
            
            # The API might store ADB info as a nested JSON string or direct fields
            adb_info_str = phone.get("adbInfo")
            if adb_info_str:
                import json
                try:
                    adb_info = json.loads(adb_info_str)
                    ip = adb_info.get("adbIp")
                    port = str(adb_info.get("adbPort", ""))
                    pwd = adb_info.get("adbPassword", "")
                    if ip and port: return ip, port, pwd
                except:
                    pass
            
            ip = phone.get("adbIp")
            port = str(phone.get("adbPort", ""))
            pwd = phone.get("adbPassword", "")
            if ip and port and ip != "None" and port != "None":
                return ip, port, pwd
                
            time.sleep(5)
            
        return "", "", ""

    @classmethod
    def get_volaris_boarding_pass(cls, pnr: str, last_name: str) -> str | None:
        phone = cls.get_first_cloud_phone()
        if not phone:
            logger.warning("No MoreLogin Cloud Phone found.")
            return None
            
        phone_id = phone.get("id")
        status = phone.get("envStatus") # 2 = stopped, 1 = running, 3 = starting
        
        # 1. Rotate Proxy if phone is stopped
        if status == 2:
            cls.rotate_proxy(phone)
        
        # 2. Enable ADB and Start
        cls.enable_adb(phone_id)
        if status != 1:
            cls.start_phone(phone_id)
            
        # 3. Wait for boot and ADB exposure
        logger.info("Waiting for Cloud Phone to boot and expose ADB port...")
        adb_ip, adb_port, adb_pass = cls.wait_for_adb_details(phone_id)
        
        if not adb_ip:
            logger.error("Timed out waiting for ADB details from Cloud Phone.")
            return None
            
        addr = f"{adb_ip}:{adb_port}"
        if not cls.connect_adb(adb_ip, adb_port, adb_pass):
            logger.error("Failed to connect via ADB.")
            return None

        # 4. Automate Volaris App
        cls.wipe_app(addr) # Wipe BEFORE starting
        
        logger.info("Opening Volaris app...")
        subprocess.run(["adb", "-s", addr, "shell", "monkey", "-p", "com.volaris.app", "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True)
        time.sleep(15) # Wait for splash screen
        
        # Note: In a production scenario, we'd use UIAutomator to tap specific fields:
        # e.g., adb shell input text PNR
        # e.g., adb shell input tap x y
        
        local_path = cls.pull_screenshot(addr, f"VOLARIS_{pnr}")
        
        cls.wipe_app(addr) # Wipe AFTER exiting
        cls.stop_phone(phone_id)
        
        return local_path
