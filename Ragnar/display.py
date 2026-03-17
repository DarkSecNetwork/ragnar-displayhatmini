#display.py
# Description:
# This file, display.py, is responsible for managing the e-ink display of the Ragnar project, updating it with relevant data and statuses.
# It initializes the display, manages multiple threads for updating shared data and vulnerability counts, and handles the rendering of information
# and images on the display.
#
# Key functionalities include:
# - Initializing the e-ink display (EPD) and handling any errors during initialization.
# - Creating and managing threads to periodically update shared data and vulnerability counts.
# - Rendering various statistics, status icons, and images on the e-ink display.
# - Handling updates to shared data from various sources, including CSV files and system commands.
# - Checking and displaying the status of Bluetooth, Wi-Fi, PAN, and USB connections.
# - Providing methods to update the display with comments from an AI (Commentaireia) and generating images dynamically.

import threading
import time
import os
import signal
import glob
import logging
import random
import sys
import csv
from PIL import Image, ImageDraw
from init_shared import shared_data  
from comment import Commentaireia
from logger import Logger
import subprocess  

logger = Logger(name="display.py", level=logging.DEBUG)

# Import button listener (only functional on Pi with GPIO)
try:
    from epd_button import EPDButtonListener, PAGE_MAIN, PAGE_NETWORK, PAGE_VULN, PAGE_DISCOVERED, PAGE_ADVANCED, PAGE_TRAFFIC
except ImportError:
    EPDButtonListener = None
    PAGE_MAIN, PAGE_NETWORK, PAGE_VULN, PAGE_DISCOVERED, PAGE_ADVANCED, PAGE_TRAFFIC = 0, 1, 2, 3, 4, 5

class Display:
    def __init__(self, shared_data):
        """Initialize the display and start the main image and shared data update threads."""
        self.shared_data = shared_data
        self.config = self.shared_data.config
        self.shared_data.ragnarstatustext2 = "Awakening..."
        self.commentaire_ia = Commentaireia()
        self.semaphore = threading.Semaphore(10)
        self.screen_reversed = self.shared_data.screen_reversed
        self.web_screen_reversed = self.shared_data.web_screen_reversed
        self.main_image = None  # Initialize main_image variable

        # Frise position (x=0 since frise is resized to full display width)
        self.frise_positions = {
            "default": {
                "x": 0,
                "y": 160
            }
        }

        try:
            self.epd_helper = self.shared_data.epd_helper
            self.epd_helper.init_partial_update()
            logger.info("Display initialization complete.")
        except Exception as e:
            logger.error(f"Error during display initialization: {e}")
            raise

        self.main_image_thread = threading.Thread(target=self.update_main_image)
        self.main_image_thread.daemon = True
        self.main_image_thread.start()

        self.update_shared_data_thread = threading.Thread(target=self.schedule_update_shared_data)
        self.update_shared_data_thread.daemon = True
        self.update_shared_data_thread.start()

        self.update_vuln_count_thread = threading.Thread(target=self.schedule_update_vuln_count)
        self.update_vuln_count_thread.daemon = True
        self.update_vuln_count_thread.start()

        self.scale_factor_x = self.shared_data.scale_factor_x
        self.scale_factor_y = self.shared_data.scale_factor_y

        # Wide display detection (e.g. 2.7" at 176x264 vs reference 122x250)
        self.is_wide = self.scale_factor_x > 1.2
        # y_stretch is no longer needed — scale_factor_y handles vertical spacing
        self.y_stretch = 1.0

        # Hardware button support (2.7" HAT has KEY1-KEY4)
        self.button_listener = None
        if self.is_wide and EPDButtonListener is not None:
            self.button_listener = EPDButtonListener(shared_data)
            self.button_listener.start()

    def get_frise_position(self):
        """Get the frise position based on the display type."""
        display_type = self.config.get("epd_type", "default")
        position = self.frise_positions.get(display_type, self.frise_positions["default"])
        return (
            int(position["x"] * self.scale_factor_x),
            int(position["y"] * self.scale_factor_y)
        )

    def schedule_update_shared_data(self):
        """Periodically update the shared data with the latest system information."""
        while not self.shared_data.display_should_exit:
            self.update_shared_data()
            time.sleep(5)  # Check every 5 seconds for faster WiFi/SSH status updates

    def schedule_update_vuln_count(self):
        """Periodically update the vulnerability count on the display."""
        while not self.shared_data.display_should_exit:
            self.update_vuln_count()
            time.sleep(300)

    def update_main_image(self):
        """Update the main image on the display with the latest immagegen data."""
        while not self.shared_data.display_should_exit:
            try:
                self.shared_data.update_image_randomizer()
                if self.shared_data.imagegen:
                    self.main_image = self.shared_data.imagegen
                else:
                    logger.error("No image generated for current status.")
                time.sleep(random.uniform(self.shared_data.image_display_delaymin, self.shared_data.image_display_delaymax))
            except Exception as e:
                logger.error(f"An error occurred in update_main_image: {e}")

    def get_open_files(self):
        """Get the number of open FD files on the system."""
        try:
            open_files = len(glob.glob('/proc/*/fd/*'))
            logger.debug(f"FD : {open_files}")
            return open_files
        except Exception as e:
            logger.error(f"Error getting open files: {e}")
            return None
        
    def update_vuln_count(self):
        """Update the vulnerability count on the display."""
        import pandas as pd
        with self.semaphore:
            try:
                if not os.path.exists(self.shared_data.vuln_summary_file):
                    df = pd.DataFrame(columns=["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])
                    df.to_csv(self.shared_data.vuln_summary_file, index=False)
                    self.shared_data.vulnnbr = 0
                    logger.info("Vulnerability summary file created.")
                else:
                    # Get alive hosts from SQLite database instead of CSV
                    try:
                        db_stats = self.shared_data.db.get_stats()
                        alive_hosts = self.shared_data.db.get_all_hosts()
                        alive_macs = {
                            h['mac'] for h in alive_hosts 
                            if h.get('status') == 'alive' and h.get('mac') != 'STANDALONE'
                        }
                        logger.debug(f"Loaded {len(alive_macs)} alive MACs from database")
                    except Exception as e:
                        logger.warning(f"Could not get alive MACs from database: {e}")
                        alive_macs = set()


                    try:
                        # Check if file is not empty and has content
                        if os.path.getsize(self.shared_data.vuln_summary_file) > 0:
                            with open(self.shared_data.vuln_summary_file, 'r') as file:
                                df = pd.read_csv(file)
                        else:
                            logger.debug("vuln_summary file is empty, initializing with empty DataFrame")
                            df = pd.DataFrame(columns=["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])
                    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
                        logger.warning(f"Could not parse vuln_summary file: {e}, creating new one")
                        df = pd.DataFrame(columns=["IP", "Hostname", "MAC Address", "Port", "Vulnerabilities"])
                        all_vulnerabilities = set()

                        for index, row in df.iterrows():
                            mac_address = row["MAC Address"]
                            if mac_address in alive_macs and mac_address != "STANDALONE":
                                vulnerabilities = row["Vulnerabilities"]
                                if pd.isna(vulnerabilities) or not isinstance(vulnerabilities, str):
                                    continue

                                if vulnerabilities and isinstance(vulnerabilities, str):
                                    all_vulnerabilities.update(vulnerabilities.split("; "))

                        self.shared_data.vulnnbr = len(all_vulnerabilities)
                        logger.debug(f"Updated vulnerabilities count: {self.shared_data.vulnnbr}")

                    if os.path.exists(self.shared_data.livestatusfile):
                        try:
                            # Check if file is not empty and has content
                            if os.path.getsize(self.shared_data.livestatusfile) > 0:
                                with open(self.shared_data.livestatusfile, 'r+') as livestatus_file:
                                    livestatus_df = pd.read_csv(livestatus_file)
                                    if not livestatus_df.empty:
                                        livestatus_df.loc[0, 'Vulnerabilities Count'] = self.shared_data.vulnnbr
                                        livestatus_df.to_csv(self.shared_data.livestatusfile, index=False)
                                        logger.debug(f"Updated livestatusfile with vulnerability count: {self.shared_data.vulnnbr}")
                            else:
                                logger.debug("livestatus file is empty, skipping update")
                        except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
                            logger.warning(f"Could not parse livestatus file: {e}")
                    else:
                        logger.error(f"Livestatusfile {self.shared_data.livestatusfile} does not exist.")
            except Exception as e:
                logger.error(f"An error occurred in update_vuln_count: {e}")

    def update_shared_data(self):
        """Update the shared data with the latest system information."""
        import pandas as pd
        with self.semaphore:
            try:
                # Create livestatus file if it doesn't exist
                if not os.path.exists(self.shared_data.livestatusfile):
                    logger.info(f"Creating missing livestatus file: {self.shared_data.livestatusfile}")
                    self.shared_data.create_livestatusfile()
                
                try:
                    # Check if file is not empty and has content
                    if os.path.getsize(self.shared_data.livestatusfile) > 0:
                        with open(self.shared_data.livestatusfile, 'r') as file:
                            livestatus_df = pd.read_csv(file)
                    else:
                        logger.warning("Livestatus file is empty, recreating it")
                        self.shared_data.create_livestatusfile()
                        with open(self.shared_data.livestatusfile, 'r') as file:
                            livestatus_df = pd.read_csv(file)
                except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
                    logger.warning(f"Could not parse livestatus file: {e}, recreating it")
                    self.shared_data.create_livestatusfile()
                    with open(self.shared_data.livestatusfile, 'r') as file:
                        livestatus_df = pd.read_csv(file)

                    # Check if DataFrame is empty or has the expected columns
                    if livestatus_df.empty:
                        logger.warning("Livestatus file is empty, skipping data update")
                        return

                    # Ensure required columns exist; add them with default 0 if missing
                    required_columns = ['Total Open Ports', 'Alive Hosts Count', 'All Known Hosts Count', 'Vulnerabilities Count']
                    for column in required_columns:
                        if column not in livestatus_df.columns:
                            logger.warning(f"Column '{column}' missing in livestatus file, initializing with 0")
                            livestatus_df[column] = 0

                    # Check if there's at least one row
                    if len(livestatus_df) == 0:
                        logger.warning("Livestatus file has no data rows, skipping data update")
                        return

                    def _safe_int_from_df(df, column_name):
                        try:
                            value = pd.to_numeric(df[column_name].iloc[0], errors='coerce')
                            if pd.isna(value):
                                return 0
                            return int(value)
                        except Exception as e:
                            logger.debug(f"Could not parse column '{column_name}' from livestatus file: {e}")
                            return 0

                    self.shared_data.portnbr = _safe_int_from_df(livestatus_df, 'Total Open Ports')
                    self.shared_data.targetnbr = _safe_int_from_df(livestatus_df, 'Alive Hosts Count')
                    self.shared_data.networkkbnbr = _safe_int_from_df(livestatus_df, 'All Known Hosts Count')
                    self.shared_data.vulnnbr = _safe_int_from_df(livestatus_df, 'Vulnerabilities Count')

                    # Persist any columns we added so other components stay in sync
                    try:
                        livestatus_df.to_csv(self.shared_data.livestatusfile, index=False)
                    except Exception as e:
                        logger.debug(f"Unable to persist normalized livestatus columns: {e}")

                crackedpw_files = glob.glob(f"{self.shared_data.crackedpwddir}/*.csv")

                total_passwords = 0
                for file in crackedpw_files:
                    try:
                        # Check if file is not empty and has content
                        if os.path.getsize(file) > 0:
                            with open(file, 'r') as f:
                                df = pd.read_csv(f, usecols=[0])
                                if not df.empty:
                                    total_passwords += len(df)
                        else:
                            logger.debug(f"Password file {file} is empty, skipping")
                    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
                        logger.debug(f"Could not parse password file {file}: {e}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error reading password file {file}: {e}")
                        continue

                self.shared_data.crednbr = total_passwords

                total_data = sum([len(files) for r, d, files in os.walk(self.shared_data.datastolendir)])
                self.shared_data.datanbr = total_data

                total_zombies = sum([len(files) for r, d, files in os.walk(self.shared_data.zombiesdir)])
                self.shared_data.zombiesnbr = total_zombies
                total_attacks = sum([len(files) for r, d, files in os.walk(self.shared_data.actions_dir) if not r.endswith("__pycache__")]) - 2

                self.shared_data.attacksnbr = total_attacks

                self.shared_data.update_stats()
                self.shared_data.manual_mode = self.is_manual_mode()
                if self.shared_data.manual_mode:
                    self.manual_mode_txt = "M"
                else:
                    self.manual_mode_txt = "A"
                
                # Check WiFi connectivity with detailed logging
                wifi_connected = self.is_wifi_connected()
                self.shared_data.wifi_connected = wifi_connected
                logger.info(f"[DISPLAY] WiFi status check: connected={wifi_connected}")

                signal_dbm, signal_quality = self.get_wifi_signal_strength() if wifi_connected else (None, None)
                self.shared_data.wifi_signal_dbm = signal_dbm
                self.shared_data.wifi_signal_quality = signal_quality
                if signal_dbm is not None:
                    logger.debug(f"[DISPLAY] WiFi RSSI: {signal_dbm} dBm, quality={self.shared_data.wifi_signal_quality}%")
                
                self.shared_data.ap_mode_active = self.is_ap_mode_active()
                self.shared_data.ap_client_count = self.get_ap_client_count() if self.shared_data.ap_mode_active else 0
                self.shared_data.usb_active = self.is_usb_connected()
                
                # Update Wi-Fi/AP status text for display
                wifi_status_text = self.get_wifi_status_text()
                self.shared_data.ragnarstatustext2 = wifi_status_text
                logger.info(f"[DISPLAY] WiFi status text: '{wifi_status_text}'")
                
                self.get_open_files()

            except (FileNotFoundError, pd.errors.EmptyDataError) as e:
                logger.error(f"Error: {e}")
            except Exception as e:
                logger.error(f"Error updating shared data: {e}")

    def display_comment(self, status):
        """Display the comment based on the status of the ragnarorch."""
        comment = self.commentaire_ia.get_commentaire(status)
        if comment:
            self.shared_data.ragnarsays = comment
            self.shared_data.ragnarstatustext = self.shared_data.ragnarorch_status
        else:
            pass

    # # # def is_bluetooth_connected(self):
    # # #     """
    # # #     Check if any device is connected to the Bluetooth (pan0) interface by checking the output of 'ip neigh show dev pan0'.
    # # #     """
    # # #     try:
    # # #         result = subprocess.Popen(['ip', 'neigh', 'show', 'dev', 'pan0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # # #         output, error = result.communicate()
    # # #         if result.returncode != 0:
    # # #             logger.error(f"Error executing 'ip neigh show dev pan0': {error}")
    # # #             return False
    # # #         return bool(output.strip())
    # # #     except Exception as e:
    # # #         logger.error(f"Error checking Bluetooth connection status: {e}")
    # # #         return False

    def is_wifi_connected(self):
        """Check if WiFi is connected by checking the current SSID and network connectivity."""
        try:
            # Method 1: Try iwgetid first
            result = subprocess.Popen(['iwgetid', '-r'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            ssid, error = result.communicate()
            if result.returncode == 0 and ssid.strip():
                logger.debug(f"WiFi connected via iwgetid: SSID={ssid.strip()}")
                return True
            
            # Method 2: Check if we have an active network interface with IP
            result = subprocess.Popen(['ip', 'route', 'get', '8.8.8.8'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            route_output, error = result.communicate()
            if result.returncode == 0 and 'via' in route_output:
                logger.debug(f"WiFi connected via ip route check")
                return True
            
            # Method 3: Check for wlan interface with IP
            result = subprocess.Popen(['ip', 'addr', 'show'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            addr_output, error = result.communicate()
            if result.returncode == 0:
                # Look for wlan interfaces with inet addresses
                for line in addr_output.split('\n'):
                    if ('wlan' in line and 'state UP' in line) or ('inet ' in line and 'scope global' in line and ('wlan' in addr_output)):
                        logger.debug(f"WiFi connected via interface check")
                        return True
            
            logger.debug(f"WiFi not detected by any method")
            return False
            
        except Exception as e:
            logger.error(f"Error checking WiFi status: {e}")
            return False

    def _dbm_to_quality(self, signal_dbm):
        """Convert RSSI (dBm) to an approximate 0-100 quality percentage."""
        if signal_dbm is None:
            return None

        quality = int((signal_dbm - (-90)) * 100 / (-30 - (-90)))
        return max(0, min(100, quality))

    def get_wifi_signal_strength(self):
        """Return a tuple (signal_dbm, quality_percent) if available."""
        # Primary method: use `iw dev wlan0 link`
        try:
            result = subprocess.run(['iw', 'dev', 'wlan0', 'link'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'signal:' in line:
                        try:
                            raw_value = line.split('signal:')[1].split('dBm')[0].strip()
                            signal_dbm = float(raw_value)
                            return signal_dbm, self._dbm_to_quality(signal_dbm)
                        except (ValueError, IndexError):
                            logger.debug(f"Failed to parse iw signal line: {line.strip()}")
                        break
        except FileNotFoundError:
            logger.debug("`iw` command not available for wifi strength measurement")
        except subprocess.TimeoutExpired:
            logger.debug("Timeout while fetching wifi strength via iw")
        except Exception as e:
            logger.debug(f"Unexpected error while using iw for wifi strength: {e}")

        # Fallback: use `iwconfig`
        try:
            result = subprocess.run(['iwconfig', 'wlan0'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                quality = None
                signal_dbm = None
                for line in result.stdout.split('\n'):
                    if 'Link Quality' in line:
                        try:
                            quality_part = line.split('Link Quality=')[1].split(' ')[0]
                            if '/' in quality_part:
                                numerator, denominator = quality_part.split('/')
                                quality = int(float(numerator) / float(denominator) * 100)
                        except (ValueError, IndexError):
                            logger.debug(f"Failed to parse Link Quality line: {line.strip()}")
                    if 'Signal level' in line:
                        try:
                            signal_part = line.split('Signal level=')[1].split(' ')[0]
                            if '/' in signal_part:
                                signal_part = signal_part.split('/')[0]
                            signal_dbm = float(signal_part.replace('dBm', ''))
                        except (ValueError, IndexError):
                            logger.debug(f"Failed to parse Signal level line: {line.strip()}")

                if signal_dbm is not None or quality is not None:
                    if quality is None:
                        quality = self._dbm_to_quality(signal_dbm)
                    if signal_dbm is None and quality is not None:
                        # approximate dbm from quality if needed
                        signal_dbm = (quality / 100) * (-30 - (-90)) + (-90)
                    return signal_dbm, quality
        except FileNotFoundError:
            logger.debug("`iwconfig` command not available for wifi strength measurement")
        except subprocess.TimeoutExpired:
            logger.debug("Timeout while fetching wifi strength via iwconfig")
        except Exception as e:
            logger.debug(f"Unexpected error while using iwconfig for wifi strength: {e}")

        return None, None

    def get_wifi_wave_count(self, quality):
        """Translate a 0-100 quality value into 0-4 wave arcs."""
        if quality is None:
            return 0

        thresholds = [8, 28, 52, 70]
        waves = 0
        for threshold in thresholds:
            if quality >= threshold:
                waves += 1
        return waves

    def render_wifi_wave_indicator(self, image, draw):
        """Render a live Wi-Fi indicator using wave arcs with no dBm text."""
        base_x = int(3 * self.scale_factor_x)
        base_y = int(8 * self.scale_factor_y)
        scale = min(self.scale_factor_x, self.scale_factor_y)
        signal_dbm = getattr(self.shared_data, 'wifi_signal_dbm', None)
        raw_quality = getattr(self.shared_data, 'wifi_signal_quality', None)
        effective_quality = raw_quality if raw_quality is not None else self._dbm_to_quality(signal_dbm)
        ip_last_octet = self.get_wifi_ip_last_octet()

        waves = self.get_wifi_wave_count(effective_quality)
        if waves <= 0:
            waves = 1  # Always show at least one wave when connected

        base_radius = max(2, int(1.5 * scale))
        wave_spacing = max(2, int(2.5 * scale) + 2)
        line_width = max(1, int(scale) + 1)

        center_x = base_x + base_radius + wave_spacing * 2
        center_y = base_y + base_radius + wave_spacing * 2

        # Draw expanding arcs to mimic Wi-Fi waves
        for i in range(waves):
            radius = max(2, base_radius + (i + 1) * wave_spacing - 4)
            bbox = (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius
            )
            draw.arc(bbox, start=225, end=315, fill=0, width=line_width)

        if ip_last_octet:
            text_x = center_x + wave_spacing + base_radius
            text_y = center_y - base_radius - max(1, int(6 * self.scale_factor_y))
            draw.text((text_x, text_y), ip_last_octet, font=self.shared_data.font_arial9, fill=0)

    def get_wifi_ip_last_octet(self):
        """Get the last octet of the WiFi IP address (e.g., '.211' from '192.168.1.211')."""
        try:
            # Get IP address of wlan0 interface
            result = subprocess.run(['ip', '-4', 'addr', 'show', 'wlan0'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                # Parse the output to find the IP address
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        # Extract IP address (format: "inet 192.168.1.211/24 ...")
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            ip_with_mask = parts[1]
                            ip_address = ip_with_mask.split('/')[0]
                            # Get the last octet
                            octets = ip_address.split('.')
                            if len(octets) == 4:
                                return f".{octets[3]}"
            return None
        except Exception as e:
            logger.error(f"Error getting WiFi IP address: {e}")
            return None

    def is_ap_mode_active(self):
        """Check if AP mode is currently active."""
        try:
            # Check if hostapd is running
            result = subprocess.run(['pgrep', 'hostapd'], capture_output=True, text=True)
            if result.returncode == 0:
                return True
            
            # Alternative check: see if we're listening on AP interface
            result = subprocess.run(['ip', 'addr', 'show', 'wlan0'], capture_output=True, text=True)
            if result.returncode == 0 and '192.168.4.1' in result.stdout:
                return True
                
            return False
        except Exception as e:
            logger.error(f"Error checking AP mode status: {e}")
            return False

    def get_ap_client_count(self):
        """Get the number of clients connected to AP mode."""
        try:
            # Try to get from WiFi manager first
            if (hasattr(self.shared_data, 'ragnar_instance') and 
                self.shared_data.ragnar_instance and 
                hasattr(self.shared_data.ragnar_instance, 'wifi_manager')):
                
                wifi_mgr = self.shared_data.ragnar_instance.wifi_manager
                if hasattr(wifi_mgr, 'ap_clients_count'):
                    return wifi_mgr.ap_clients_count
            
            # Fallback to hostapd_cli
            result = subprocess.run(['hostapd_cli', '-i', 'wlan0', 'list_sta'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                clients = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                return len(clients)
            
            return 0
        except Exception as e:
            logger.error(f"Error getting AP client count: {e}")
            return 0

    def get_wifi_status_text(self):
        """Get descriptive text for current Wi-Fi status."""
        try:
            # FIRST: Try system-level WiFi detection (most reliable)
            # Method 1: Try iwgetid first (get SSID if available)
            try:
                result = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    ssid = result.stdout.strip()
                    logger.debug(f"[STATUS] WiFi connected via iwgetid: SSID={ssid}")
                    return f"WiFi: {ssid}"
            except:
                pass
            
            # Method 2: Check if we have network connectivity (WiFi without SSID)
            try:
                result = subprocess.run(['ip', 'route', 'get', '8.8.8.8'], 
                                      capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and 'via' in result.stdout:
                    logger.debug(f"[STATUS] WiFi connected via ip route check")
                    return "WiFi: Connected"
            except:
                pass
            
            # Method 3: Check for wlan interface with IP
            try:
                result = subprocess.run(['ip', 'addr', 'show'], 
                                      capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    # Look for wlan interfaces with inet addresses
                    for line in result.stdout.split('\n'):
                        if ('wlan' in line and 'state UP' in line) or ('inet ' in line and 'scope global' in line and ('wlan' in result.stdout)):
                            logger.debug(f"[STATUS] WiFi connected via interface check")
                            return "WiFi: Connected"
            except:
                pass
            
            # SECONDARY: Try to get status from WiFi manager (if available in same process)
            if (hasattr(self.shared_data, 'ragnar_instance') and 
                self.shared_data.ragnar_instance and 
                hasattr(self.shared_data.ragnar_instance, 'wifi_manager')):
                
                wifi_mgr = self.shared_data.ragnar_instance.wifi_manager
                
                # Check AP mode status first
                if hasattr(wifi_mgr, 'ap_mode_active') and wifi_mgr.ap_mode_active:
                    # Try to get client count
                    client_count = 0
                    if hasattr(wifi_mgr, 'ap_clients_count'):
                        client_count = wifi_mgr.ap_clients_count
                    
                    if client_count > 0:
                        return f"AP: {client_count} client{'s' if client_count != 1 else ''}"
                    else:
                        return "AP: No clients"
                
                # Check Wi-Fi connection status
                if hasattr(wifi_mgr, 'wifi_connected') and wifi_mgr.wifi_connected:
                    if hasattr(wifi_mgr, 'current_ssid') and wifi_mgr.current_ssid:
                        return f"WiFi: {wifi_mgr.current_ssid}"
                    else:
                        return "WiFi: Connected"
                
                # Check if cycling mode is active
                if hasattr(wifi_mgr, 'cycling_mode') and wifi_mgr.cycling_mode:
                    return "WiFi: Cycling"
            
            # TERTIARY: Check if we're in AP mode at system level
            if self.is_ap_mode_active():
                # Try to get AP client count
                try:
                    result = subprocess.run(['hostapd_cli', '-i', 'wlan0', 'list_sta'], 
                                          capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        clients = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                        client_count = len(clients)
                        if client_count > 0:
                            return f"AP: {client_count} client{'s' if client_count != 1 else ''}"
                        else:
                            return "AP: No clients"
                    else:
                        return "AP: Active"
                except:
                    return "AP: Active"
            
            logger.debug(f"[STATUS] WiFi not detected by any method")
            return "WiFi: Disconnected"
            
        except Exception as e:
            logger.error(f"Error getting WiFi status text: {e}")
            return "WiFi: Unknown"

    def is_manual_mode(self):
        """Check if the ragnarorch is in manual mode."""
        return self.shared_data.manual_mode

    def is_interface_connected(self, interface):
        """Check if any device is connected to the specified interface."""
        try:
            result = subprocess.Popen(['ip', 'neigh', 'show', 'dev', interface], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output, error = result.communicate()
            if result.returncode != 0:
                logger.error(f"Error executing 'ip neigh show dev {interface}': {error}")
                return False
            return bool(output.strip())
        except Exception as e:
            logger.error(f"Error checking connection status on {interface}: {e}")
            return False

    def is_usb_connected(self):
        """Check if any device is connected to the USB interface."""
        try:
            result = subprocess.Popen(['ip', 'neigh', 'show', 'dev', 'usb0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output, error = result.communicate()
            if result.returncode != 0:
                logger.error(f"Error executing 'ip neigh show dev usb0': {error}")
                return False
            return bool(output.strip())
        except Exception as e:
            logger.error(f"Error checking USB connection status: {e}")
            return False

    def _sleep_interruptible(self, current_page):
        """Sleep for screen_delay but wake early if button changes the page."""
        if not self.button_listener:
            time.sleep(self.shared_data.screen_delay)
            return
        # Check every 0.1s if page changed, otherwise do full sleep
        steps = max(1, int(self.shared_data.screen_delay / 0.1))
        for _ in range(steps):
            if self.button_listener.current_page != current_page:
                return  # Page changed, skip remaining sleep
            time.sleep(0.1)

    def _get_cached_page_data(self, key, fetch_fn, ttl=10):
        """Get cached page data, refreshing if older than ttl seconds."""
        if not hasattr(self, '_page_cache'):
            self._page_cache = {}
        now = time.time()
        cached = self._page_cache.get(key)
        if cached and (now - cached[0]) < ttl:
            return cached[1]
        try:
            data = fetch_fn()
        except Exception as e:
            logger.debug(f"Page data fetch error ({key}): {e}")
            data = cached[1] if cached else None
        self._page_cache[key] = (now, data)
        return data

    def _draw_page_frame(self, draw, title):
        """Draw standard page frame: border, title, divider, footer."""
        w = self.shared_data.width
        h = self.shared_data.height
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        font_title = self.shared_data.font_viking
        draw.rectangle((1, 1, w - 1, h - 1), outline=0)
        draw.text((int(4 * sx), int(4 * sy)), title, font=font_title, fill=0)
        draw.line((1, int(22 * sy), w - 1, int(22 * sy)), fill=0)
        draw.line((1, h - int(18 * sy), w - 1, h - int(18 * sy)), fill=0)
        draw.text((int(4 * sx), h - int(16 * sy)), "K1:Home K2:Flip K3:Next K4:Rst", font=font, fill=0)

    def _draw_stat_rows(self, draw, y, stats):
        """Draw key-value stat rows. Returns final y position."""
        w = self.shared_data.width
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        line_h = int(14 * sy)
        pad_x = int(6 * sx)
        for label, value in stats:
            val_str = str(value)[:22]
            draw.text((pad_x, y), label, font=font, fill=0)
            draw.text((w - pad_x - font.getlength(val_str), y), val_str, font=font, fill=0)
            y += line_h
        return y

    def _fetch_network_data(self):
        """Fetch real host data from database."""
        sd = self.shared_data
        try:
            hosts = sd.db.get_all_hosts()
            alive = [h for h in hosts if h.get('status') == 'alive']
            total_ports = 0
            for h in hosts:
                ports_str = h.get('ports', '')
                if ports_str:
                    total_ports += len([p for p in str(ports_str).split(';') if p.strip()])
            return {
                'total': len(hosts),
                'alive': len(alive),
                'ports': total_ports,
                'hosts': hosts[:8],
            }
        except Exception as e:
            logger.debug(f"DB host fetch error: {e}")
            return None

    def _fetch_vuln_intel_data(self):
        """Fetch real vulnerability intelligence from scan files."""
        sd = self.shared_data
        vuln_dir = getattr(sd, 'vulnerabilities_dir', None)
        if not vuln_dir or not os.path.exists(vuln_dir):
            return None
        scans = 0
        hosts_set = set()
        services = 0
        scripts = 0
        recent_targets = []
        try:
            for fname in os.listdir(vuln_dir):
                fpath = os.path.join(vuln_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                if fname.endswith('_vuln_scan.txt'):
                    scans += 1
                    ip = fname.split('_')[0] if '_' in fname else fname
                    hosts_set.add(ip)
                    if len(recent_targets) < 5:
                        recent_targets.append(ip)
                    try:
                        with open(fpath, 'r', errors='ignore') as f:
                            content = f.read()
                        for line in content.split('\n'):
                            if '/tcp' in line or '/udp' in line:
                                services += 1
                            if '|' in line and '_' in line:
                                scripts += 1
                    except Exception:
                        pass
                elif fname.startswith('lynis_') and fname.endswith('_pentest.txt'):
                    scans += 1
                    parts = fname.replace('lynis_', '').replace('_pentest.txt', '')
                    hosts_set.add(parts)
        except Exception as e:
            logger.debug(f"Vuln intel scan error: {e}")
        return {
            'scans': scans,
            'hosts': len(hosts_set),
            'services': services,
            'scripts': scripts,
            'targets': recent_targets,
        }

    def _count_cred_file(self, filepath):
        """Count credential entries in a CSV file."""
        try:
            if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
                return 0
            with open(filepath, 'r') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                return sum(1 for row in reader if row)
        except Exception:
            return 0

    def _fetch_discovered_data(self):
        """Fetch real credentials, loot, and attack data."""
        sd = self.shared_data
        creds = {}
        for svc, attr in [('SSH', 'sshfile'), ('SMB', 'smbfile'), ('FTP', 'ftpfile'),
                          ('Telnet', 'telnetfile'), ('RDP', 'rdpfile'), ('SQL', 'sqlfile')]:
            filepath = getattr(sd, attr, '')
            creds[svc] = self._count_cred_file(filepath) if filepath else 0
        total_creds = sum(creds.values())
        loot_count = 0
        try:
            if os.path.exists(sd.datastolendir):
                for _, _, files in os.walk(sd.datastolendir):
                    loot_count += len([f for f in files if not f.endswith('.log')])
        except Exception:
            pass
        attack_count = 0
        try:
            attacks_dir = os.path.join(sd.logsdir, 'attacks')
            if os.path.exists(attacks_dir):
                import json as json_mod
                for fname in os.listdir(attacks_dir):
                    if fname.endswith('.json'):
                        try:
                            with open(os.path.join(attacks_dir, fname), 'r') as f:
                                data = json_mod.load(f)
                            if isinstance(data, list):
                                attack_count += len(data)
                        except Exception:
                            pass
        except Exception:
            pass
        return {
            'creds': creds,
            'total_creds': total_creds,
            'loot': loot_count,
            'attacks': attack_count,
            'zombies': getattr(sd, 'zombiesnbr', 0),
        }

    def _fetch_advanced_data(self):
        """Fetch real advanced vulnerability scanner data."""
        scanner = getattr(self.shared_data, '_advanced_vuln_scanner', None)
        if not scanner:
            return None
        try:
            available = scanner.get_available_scanners()
            summary = scanner.get_summary()
            active = scanner.get_active_scans_list()
            return {
                'scanners': available,
                'summary': summary,
                'active_scans': active,
            }
        except Exception as e:
            logger.debug(f"Advanced scanner data error: {e}")
            return None

    def _fetch_traffic_data(self):
        """Fetch real traffic analyzer data."""
        analyzer = getattr(self.shared_data, '_traffic_analyzer', None)
        if not analyzer:
            return None
        try:
            summary = analyzer.get_summary()
            return summary
        except Exception as e:
            logger.debug(f"Traffic analyzer data error: {e}")
            return None

    def _render_network_page(self, image, draw):
        """Render Page 2: Network Scanner - real host data from database."""
        self._draw_page_frame(draw, "NETWORK SCAN")
        w = self.shared_data.width
        h = self.shared_data.height
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        sd = self.shared_data
        y = int(28 * sy)
        line_h = int(14 * sy)
        pad_x = int(6 * sx)
        row_h = int(12 * sy)

        data = self._get_cached_page_data('network', self._fetch_network_data)

        if data:
            stats = [
                ("Hosts alive", f"{data['alive']}/{data['total']}"),
                ("Open ports", str(data['ports'])),
                ("Credentials", str(getattr(sd, 'crednbr', 0))),
                ("Status", str(getattr(sd, 'ragnarorch_status', 'IDLE'))),
            ]
            y = self._draw_stat_rows(draw, y, stats)

            # Divider before host list
            y += int(2 * sy)
            draw.line((int(4 * sx), y, w - int(4 * sx), y), fill=0)
            y += int(4 * sy)

            # List actual discovered hosts
            hosts = data.get('hosts', [])
            max_rows = (h - int(18 * sy) - y) // row_h
            for host in hosts[:max_rows]:
                ip = host.get('ip', '?')
                status = host.get('status', '?')
                ports = host.get('ports', '')
                port_count = len([p for p in str(ports).split(';') if p.strip()]) if ports else 0
                line = f"{ip}"
                extra = f"{status[:3]} p:{port_count}"
                draw.text((pad_x, y), line, font=font, fill=0)
                draw.text((w - pad_x - font.getlength(extra), y), extra, font=font, fill=0)
                y += row_h
        else:
            stats = [
                ("Hosts found", str(getattr(sd, 'targetnbr', 0))),
                ("Open ports", str(getattr(sd, 'portnbr', 0))),
                ("Credentials", str(getattr(sd, 'crednbr', 0))),
                ("Network KB", str(getattr(sd, 'networkkbnbr', 0))),
                ("Status", str(getattr(sd, 'ragnarorch_status', 'IDLE'))),
            ]
            self._draw_stat_rows(draw, y, stats)

    def _render_vuln_page(self, image, draw):
        """Render Page 3: Vulnerability Scanner - real scan intel from files."""
        self._draw_page_frame(draw, "VULN INTEL")
        w = self.shared_data.width
        h = self.shared_data.height
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        sd = self.shared_data
        y = int(28 * sy)
        row_h = int(12 * sy)
        pad_x = int(6 * sx)

        data = self._get_cached_page_data('vuln_intel', self._fetch_vuln_intel_data, ttl=30)

        if data:
            stats = [
                ("Vulns found", str(getattr(sd, 'vulnnbr', 0))),
                ("Scan reports", str(data['scans'])),
                ("Hosts scanned", str(data['hosts'])),
                ("Services", str(data['services'])),
                ("Script outputs", str(data['scripts'])),
            ]
            y = self._draw_stat_rows(draw, y, stats)

            # Show recent scan targets
            targets = data.get('targets', [])
            if targets:
                y += int(2 * sy)
                draw.line((int(4 * sx), y, w - int(4 * sx), y), fill=0)
                y += int(4 * sy)
                draw.text((pad_x, y), "Recent targets:", font=font, fill=0)
                y += row_h
                max_rows = (h - int(18 * sy) - y) // row_h
                for ip in targets[:max_rows]:
                    draw.text((int(10 * sx), y), ip, font=font, fill=0)
                    y += row_h
        else:
            stats = [
                ("Vulns found", str(getattr(sd, 'vulnnbr', 0))),
                ("Attacks avail", str(getattr(sd, 'attacksnbr', 0))),
                ("Hosts scanned", str(getattr(sd, 'targetnbr', 0))),
                ("No scan files", ""),
            ]
            self._draw_stat_rows(draw, y, stats)

    def _render_discovered_page(self, image, draw):
        """Render Page 4: Discovered - real credentials, loot, and attack data."""
        self._draw_page_frame(draw, "DISCOVERED")
        w = self.shared_data.width
        h = self.shared_data.height
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        y = int(28 * sy)

        data = self._get_cached_page_data('discovered', self._fetch_discovered_data, ttl=15)

        if data:
            creds = data['creds']
            stats = [
                ("SSH creds", str(creds.get('SSH', 0))),
                ("SMB creds", str(creds.get('SMB', 0))),
                ("FTP creds", str(creds.get('FTP', 0))),
                ("Telnet", str(creds.get('Telnet', 0))),
                ("RDP creds", str(creds.get('RDP', 0))),
                ("SQL creds", str(creds.get('SQL', 0))),
            ]
            y = self._draw_stat_rows(draw, y, stats)
            y += int(2 * sy)
            draw.line((int(4 * sx), y, w - int(4 * sx), y), fill=0)
            y += int(4 * sy)
            summary = [
                ("Data stolen", f"{data['loot']} files"),
                ("Attack logs", str(data['attacks'])),
                ("Zombies", str(data['zombies'])),
            ]
            self._draw_stat_rows(draw, y, summary)
        else:
            stats = [
                ("Credentials", str(getattr(self.shared_data, 'crednbr', 0))),
                ("Data files", str(getattr(self.shared_data, 'datanbr', 0))),
                ("Zombies", str(getattr(self.shared_data, 'zombiesnbr', 0))),
            ]
            self._draw_stat_rows(draw, y, stats)

    def _render_advanced_page(self, image, draw):
        """Render Page 5: Advanced Vuln Scanner - real scanner status and findings."""
        self._draw_page_frame(draw, "ADV SCANNER")
        w = self.shared_data.width
        h = self.shared_data.height
        sx = self.scale_factor_x
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        y = int(28 * sy)
        line_h = int(14 * sy)
        row_h = int(12 * sy)
        pad_x = int(6 * sx)

        data = self._get_cached_page_data('advanced', self._fetch_advanced_data, ttl=5)

        if data:
            scanners = data.get('scanners', {})
            summary = data.get('summary', {})
            active = data.get('active_scans', [])
            sev = summary.get('severity_counts', {})

            # Scanner availability
            scanner_items = []
            for name in ['nuclei', 'nikto', 'zap']:
                if name == 'zap':
                    running = scanners.get('zap_running', False)
                    status = "Running" if running else ("Ready" if scanners.get(name) else "N/A")
                else:
                    status = "Ready" if scanners.get(name) else "N/A"
                scanner_items.append((name.capitalize(), status))

            for label, value in scanner_items:
                draw.text((pad_x, y), label, font=font, fill=0)
                draw.text((w - pad_x - font.getlength(value), y), value, font=font, fill=0)
                y += line_h

            y += int(2 * sy)
            draw.line((int(4 * sx), y, w - int(4 * sx), y), fill=0)
            y += int(4 * sy)

            # Findings summary
            total = summary.get('total_findings', 0)
            draw.text((pad_x, y), "Findings", font=font, fill=0)
            draw.text((w - pad_x - font.getlength(str(total)), y), str(total), font=font, fill=0)
            y += line_h

            # Severity breakdown on one line each
            crit = sev.get('critical', 0)
            high = sev.get('high', 0)
            med = sev.get('medium', 0)
            low = sev.get('low', 0)
            sev_line = f"C:{crit} H:{high} M:{med} L:{low}"
            draw.text((pad_x, y), sev_line, font=font, fill=0)
            y += line_h

            # Active scans
            active_count = len([s for s in active if s.get('status') == 'running'])
            draw.text((pad_x, y), "Active scans", font=font, fill=0)
            draw.text((w - pad_x - font.getlength(str(active_count)), y), str(active_count), font=font, fill=0)
            y += line_h

            # Show running scan details
            for scan in active:
                if scan.get('status') == 'running' and y < h - int(32 * sy):
                    stype = scan.get('scan_type', '?')[:8]
                    progress = scan.get('progress_percent', 0)
                    line = f"{stype} {progress}%"
                    draw.text((int(10 * sx), y), line, font=font, fill=0)
                    y += row_h
        else:
            stats = [
                ("Scanner", "Not available"),
                ("Vulns found", str(getattr(self.shared_data, 'vulnnbr', 0))),
                ("Status", str(getattr(self.shared_data, 'ragnarstatustext', 'IDLE'))),
            ]
            self._draw_stat_rows(draw, y, stats)

    def _render_traffic_page(self, image, draw):
        """Render Page 6: Traffic Analysis - real capture data."""
        self._draw_page_frame(draw, "TRAFFIC")
        w = self.shared_data.width
        h = self.shared_data.height
        sy = self.scale_factor_y
        font = self.shared_data.font_arial9
        y = int(28 * sy)

        data = self._get_cached_page_data('traffic', self._fetch_traffic_data, ttl=3)

        if data:
            status = data.get('status', 'stopped')
            pkts_sec = data.get('packets_per_second', 0)
            throughput = data.get('throughput_mbps', 0)
            total_pkts = data.get('total_packets', 0)
            total_bytes_h = data.get('total_bytes_human', '0 B')
            unique_hosts = data.get('unique_hosts', 0)
            connections = data.get('active_connections', 0)
            alerts = data.get('total_alerts', 0)
            dns = data.get('dns_queries_captured', 0)

            status_str = status.upper()
            stats = [
                ("Capture", status_str),
                ("Pkts/sec", f"{pkts_sec:.1f}"),
                ("Throughput", f"{throughput:.2f} Mbps"),
                ("Total pkts", str(total_pkts)),
                ("Total data", str(total_bytes_h)),
                ("Hosts seen", str(unique_hosts)),
                ("Connections", str(connections)),
                ("Alerts", str(alerts)),
                ("DNS queries", str(dns)),
            ]
            self._draw_stat_rows(draw, y, stats)
        else:
            stats = [
                ("Traffic", "Not available"),
                ("WiFi", "On" if self.shared_data.wifi_connected else "Off"),
                ("Status", str(getattr(self.shared_data, 'ragnarorch_status', 'IDLE'))),
            ]
            self._draw_stat_rows(draw, y, stats)

    def run(self):
        """Main loop for updating the EPD display with shared data."""
        # Wait for deferred initialization (fonts, images) to finish
        # before attempting to render anything.
        if hasattr(self.shared_data, 'wait_for_deferred_init'):
            self.shared_data.wait_for_deferred_init(timeout=30)
        self.manual_mode_txt = ""
        while not self.shared_data.display_should_exit:
            try:
                self.epd_helper.init_partial_update()
                # Pull latest orientation settings so web toggles take effect without restarting the service.
                self.screen_reversed = self.shared_data.screen_reversed
                self.web_screen_reversed = self.shared_data.web_screen_reversed
                self.display_comment(self.shared_data.ragnarorch_status)
                image = Image.new('1', (self.shared_data.width, self.shared_data.height))
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0, self.shared_data.width, self.shared_data.height), fill=255)

                # Check if button listener wants a different page
                current_page = PAGE_MAIN
                if self.button_listener and self.button_listener.available:
                    current_page = self.button_listener.current_page

                if current_page == PAGE_NETWORK:
                    self._render_network_page(image, draw)
                elif current_page == PAGE_VULN:
                    self._render_vuln_page(image, draw)
                elif current_page == PAGE_DISCOVERED:
                    self._render_discovered_page(image, draw)
                elif current_page == PAGE_ADVANCED:
                    self._render_advanced_page(image, draw)
                elif current_page == PAGE_TRAFFIC:
                    self._render_traffic_page(image, draw)
                else:
                    pass  # Fall through to main page rendering below

                if current_page != PAGE_MAIN:
                    # Non-main pages are fully rendered above, skip to display
                    if self.screen_reversed:
                        image = image.transpose(Image.Transpose.ROTATE_180)
                    self.epd_helper.display_partial(image)
                    self.epd_helper.display_partial(image)
                    if self.web_screen_reversed:
                        image = image.transpose(Image.Transpose.ROTATE_180)
                    with open(os.path.join(self.shared_data.webdir, "screen.png"), 'wb') as img_file:
                        image.save(img_file)
                        img_file.flush()
                        os.fsync(img_file.fileno())
                    self._sleep_interruptible(current_page)
                    continue

                # === PAGE_MAIN: Default Ragnar display ===
                # Scale factors spread positions across the full physical canvas
                # (e.g. 176x264 for 2.7") while icons stay at original pixel size.
                W = self.shared_data.width   # physical width  (176 or 122)
                H = self.shared_data.height  # physical height (264 or 250)
                sx = self.scale_factor_x     # 1.44 on 2.7", 1.0 on 2.13"
                sy = self.scale_factor_y     # 1.056 on 2.7", 1.0 on 2.13"

                # Check PiSugar once per frame for title sizing + battery text
                _pisugar_available = False
                try:
                    _ri = getattr(self.shared_data, 'ragnar_instance', None)
                    _ps = getattr(_ri, 'pisugar_listener', None) if _ri else None
                    _pisugar_available = _ps and _ps.available
                except Exception:
                    pass
                if _pisugar_available:
                    draw.text((int(40 * sx), int(6 * sy)), "RAGNAR", font=self.shared_data.font_viking_sm, fill=0)
                else:
                    draw.text((int(37 * sx), int(5 * sy)), "RAGNAR", font=self.shared_data.font_viking, fill=0)
                draw.text((int(110 * sx), int(170 * sy)), self.manual_mode_txt, font=self.shared_data.font_arial14, fill=0)
                
                # Show AP status or WiFi status in the top-left corner
                if hasattr(self.shared_data, 'ap_mode_active') and self.shared_data.ap_mode_active:
                    ap_text = "AP"
                    if hasattr(self.shared_data, 'ap_client_count') and self.shared_data.ap_client_count > 0:
                        ap_text = f"AP:{self.shared_data.ap_client_count}"
                    draw.text((int(3 * sx), int(3 * sy)), ap_text, font=self.shared_data.font_arial9, fill=0)
                elif self.shared_data.wifi_connected:
                    self.render_wifi_wave_indicator(image, draw)
                if self.shared_data.pan_connected:
                    image.paste(self.shared_data.connected, (int(104 * sx), int(3 * sy)))
                if self.shared_data.usb_active:
                    image.paste(self.shared_data.usb, (int(90 * sx), int(4 * sy)))

                # Battery percentage (PiSugar) - flush right in header
                if _pisugar_available:
                    try:
                        bat_level = _ps.get_battery_level()
                        if bat_level is not None:
                            bat_level = int(round(bat_level))
                            charging = _ps.is_charging()
                            bat_text = f"{bat_level}%+" if charging else f"{bat_level}%"
                            bbox = self.shared_data.font_arial9.getbbox(bat_text)
                            text_w = bbox[2] - bbox[0]
                            tx = W - text_w - 1
                            draw.text((tx, int(10 * sy)),
                                      bat_text, font=self.shared_data.font_arial9, fill=0)
                    except Exception:
                        pass

                # Stats — positions scaled to fill the physical width/height,
                # but icon images stay at their original pixel size.
                stats = [
                    (self.shared_data.target,    (int(8 * sx),   int(22 * sy)), (int(28 * sx),  int(22 * sy)), str(self.shared_data.targetnbr)),
                    (self.shared_data.port,      (int(47 * sx),  int(22 * sy)), (int(67 * sx),  int(22 * sy)), str(self.shared_data.portnbr)),
                    (self.shared_data.vuln,      (int(86 * sx),  int(22 * sy)), (int(106 * sx), int(22 * sy)), str(self.shared_data.vulnnbr)),
                    (self.shared_data.cred,      (int(8 * sx),   int(41 * sy)), (int(28 * sx),  int(41 * sy)), str(self.shared_data.crednbr)),
                    (self.shared_data.money,     (int(3 * sx),   int(172 * sy)), (int(3 * sx),  int(192 * sy)), str(self.shared_data.coinnbr)),
                    (self.shared_data.level,     (int(2 * sx),   int(217 * sy)), (int(4 * sx),  int(237 * sy)), str(self.shared_data.levelnbr)),
                    (self.shared_data.zombie,    (int(47 * sx),  int(41 * sy)), (int(67 * sx),  int(41 * sy)), str(self.shared_data.zombiesnbr)),
                    (self.shared_data.networkkb, (int(102 * sx), int(190 * sy)), (int(102 * sx), int(208 * sy)), str(self.shared_data.networkkbnbr)),
                    (self.shared_data.data,      (int(86 * sx),  int(41 * sy)), (int(106 * sx), int(41 * sy)), str(self.shared_data.datanbr)),
                    (self.shared_data.attacks,   (int(100 * sx), int(218 * sy)), (int(102 * sx), int(237 * sy)), str(self.shared_data.attacksnbr)),
                ]

                for img, img_pos, text_pos, text in stats:
                    image.paste(img, img_pos)
                    draw.text(text_pos, text, font=self.shared_data.font_arial9, fill=0)

                self.shared_data.update_ragnarstatus()
                image.paste(self.shared_data.ragnarstatusimage, (int(3 * sx), int(60 * sy)))
                draw.text((int(35 * sx), int(65 * sy)), self.shared_data.ragnarstatustext, font=self.shared_data.font_arial9, fill=0)
                draw.text((int(35 * sx), int(75 * sy)), self.shared_data.ragnarstatustext2, font=self.shared_data.font_arial9, fill=0)

                # Frise ribbon
                if self.shared_data.frise is not None:
                    frise_img = self.shared_data.frise
                    if frise_img.width != W - 2:
                        frise_img = frise_img.resize((W - 2, frise_img.height), Image.NEAREST)
                    image.paste(frise_img, (1, int(160 * sy)))

                # Frame & dividers — span full physical width
                draw.rectangle((1, 1, W - 1, H - 1), outline=0)
                draw.line((1, int(20 * sy), W - 1, int(20 * sy)), fill=0)
                draw.line((1, int(59 * sy), W - 1, int(59 * sy)), fill=0)
                draw.line((1, int(87 * sy), W - 1, int(87 * sy)), fill=0)

                lines = self.shared_data.wrap_text(self.shared_data.ragnarsays, self.shared_data.font_arialbold, W - 4)
                y_text = int(90 * sy)

                # Character image — centred on the full canvas
                if self.main_image is not None:
                    cx = (W - self.main_image.width) // 2
                    cy = H - self.main_image.height
                    image.paste(self.main_image, (cx, cy))
                else:
                    logger.error("Main image not found in shared_data.")

                for line in lines:
                    draw.text((int(4 * sx), y_text), line, font=self.shared_data.font_arialbold, fill=0)
                    y_text += (self.shared_data.font_arialbold.getbbox(line)[3] - self.shared_data.font_arialbold.getbbox(line)[1]) + 3

                if self.screen_reversed:
                    image = image.transpose(Image.Transpose.ROTATE_180)

                self.epd_helper.display_partial(image)
                self.epd_helper.display_partial(image)

                if self.web_screen_reversed:
                    image = image.transpose(Image.Transpose.ROTATE_180)
                with open(os.path.join(self.shared_data.webdir, "screen.png"), 'wb') as img_file:
                    image.save(img_file)
                    img_file.flush()
                    os.fsync(img_file.fileno())

                self._sleep_interruptible(PAGE_MAIN)
            except Exception as e:
                logger.error(f"An error occurred: {e}")

def handle_exit_display(signum, frame, display_thread, exit_process=True):
    """Handle the exit signal and close the display."""
    global should_exit
    shared_data.display_should_exit = True
    logger.info("Exit signal received. Waiting for the main loop to finish...")
    try:
        if main_loop and hasattr(main_loop, 'epd_helper') and main_loop.epd_helper:
            main_loop.epd_helper.sleep()
    except Exception as e:
        logger.error(f"Error while closing the display: {e}")

    if display_thread and display_thread.is_alive():
        display_thread.join()

    logger.info("Main loop finished. Clean exit.")

    if exit_process:
        sys.exit(0)

# Declare main_loop globally
main_loop = None

if __name__ == "__main__":
    try:
        logger.info("Starting main loop...")
        main_loop = Display(shared_data)
        display_thread = threading.Thread(target=main_loop.run)
        display_thread.start()
        logger.info("Main loop started.")
        
        signal.signal(signal.SIGINT, lambda signum, frame: handle_exit_display(signum, frame, display_thread))
        signal.signal(signal.SIGTERM, lambda signum, frame: handle_exit_display(signum, frame, display_thread))
    except Exception as e:
        logger.error(f"An exception occurred during program execution: {e}")
        handle_exit_display(signal.SIGINT, None, display_thread)
        sys.exit(1)
