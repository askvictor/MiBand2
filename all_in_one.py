import time
import argparse
from datetime import datetime, timedelta
from base import MiBand2
from constants import ALERT_TYPES
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import sys
import os
import json
from datetime import datetime, timedelta
from base import MiBand2
from bluepy.btle import Scanner, DefaultDelegate
from bullet import *



BANDS_INFO_FILENAME = 'bands.json'
BAND_INFO_SHEETNAME = "Band info"
STUDENT_EMAIL_SUFFIX = 'footscray.vic.edu.au'
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

if os.geteuid() != 0:
    exit("You need to have root privileges to run this script.\nPlease try again, this time using 'sudo'. Exiting.")

os.system("hciconfig hci0 down")
os.system("hciconfig hci0 up")

credentials = ServiceAccountCredentials.from_json_keyfile_name('miband-test-16d722151b76.json', scope)
gc = gspread.authorize(credentials)
#ss = gc.open("MiBand Heart Rate Class Data")
ss = gc.open("Mi Band Test")

def initialise_band(MAC):
    band = MiBand2(MAC, debug=True)
    band.setSecurityLevel(level="medium")

    if band.initialize():
        print("Init OK")
    print("setting heart monitoring to 1 minute")
    band.set_heart_monitor_measurement_interval(enabled=True, measure_minute_interval=1)
    print("Band's time is: ", band.get_current_time()['date'].strftime("%Y-%m-%d %H:%M:%S"))
    band.disconnect()


def get_student(band_id, class_sheet):
    row = None
    for match in class_sheet.findall(band_id):
        if match.col == 1:
            row = match.row
            break
    if row is None:
        return None
    row_values = class_sheet.row_values(row)
    student = {}
    student['id'] = row_values[1]
    student['name'] = f"{row_values[2]} {row_values[3]}"
    student['email'] = f"{row_values[1]}@{STUDENT_EMAIL_SUFFIX}"
    return student


mode = Bullet("Which action?", choices=[
        "Grab data from bands",
        "Initialise bands (usually only needed on first setup, or after factory reset)"
    ]).launch()


if mode == "Grab data from bands":
    teacher_email = Input("Enter your email address (for setting output sheet ownership): ")
    bands_data = ss.worksheet(BAND_INFO_SHEETNAME).get_all_records()
    bands_macs = {b["Band Number"]: b["MAC"] for b in bands_data}

    classes = [sheet.title for sheet in ss.worksheets() if sheet.title != BAND_INFO_SHEETNAME]
    class_name = Bullet("Select a Class", choices=classes).launch()
    class_sheet = ss.worksheet(class_name)
    bands = class_sheet.col_values(1)[1:]
    bands.append("Exit")
    while True:
        chosen_band = Bullet("Select a band", choices=bands).launch()
        if chosen_band == "Exit":
            exit()
        student = get_student(band, class_sheet)
        MAC = bands_macs[int(bands[chosen_band])]

        band = MiBand2(MAC, debug=True)
        band.setSecurityLevel(level="medium")

        band.authenticate()

        band._auth_previews_data_notif(True)
        start_time = datetime.now()  # strptime("12.10.2019 01:01", "%d.%m.%Y %H:%M")
        start_time -= timedelta(days=28)  # get last 28 days of data
        outfile_name = f"{MAC.replace(':', '')}-{datetime.now()}.csv"
        outfile = open(outfile_name, "w")
        outfile.write("Date,Category,Intensity,Steps,Heart Rate\n")
        band.outfile = outfile
        band.start_get_previews_data(start_time)
        while band.active:
            band.waitForNotifications(0.1)
        outfile.close()
        band.disconnect()

        student_ss = gc.create(f"Heart Rate {class_name} {student['id']} {student['name']}")  # TODO - add timestamp
        gc.import_csv(student_ss.id, open(outfile_name).read())
        print(student_ss.id)
        gc.insert_permission(student_ss.id, teacher_email, role="owner", perm_type="user", notify=False)
        gc.insert_permission(student_ss.id, student['email'], role="writer", perm_type="user", notify=True)
        exit()

        i = input("initialise watch?")

elif mode == "Initialise bands (usually only needed on first setup, or after factory reset)":
    scan_time = 2
    while True:
        os.system("hciconfig hci0 down")
        os.system("hciconfig hci0 up")
        scanner = Scanner()
        print("scanning for devices")
        devices = scanner.scan(scan_time)
        scan_time = 2

        bands_sheet = ss.worksheet(BAND_INFO_SHEETNAME)

        bands_found = []

        for dev in devices:
            band = False
            devdata = dev.getScanData()
            for (adtype, desc, value) in devdata:
                if desc == "Complete Local Name" and value == "Mi Band 3":
                    band = True
            if band:
                bands_found.append(f"{dev.addr} strength: {dev.rssi} dB")
        bands_found.append("Scan Again")
        bands_found.append("Exit")

        band = Bullet("Select the band you'd like to set up", choices=bands_found).launch()
        if band == "Exit":
            exit()
        elif band == "Scan Again":
            scan_time = 5
            continue
        else:
            MAC = band.split(' ')[0]
            print("intialising band - it should buzz and ask for a tap")
            initialise_band(MAC)
            band_id = str(Numbers("Enter the band number engraved on the back of band: ", type=int).launch())
            try:
                cell = bands_sheet.find(str(band_id))
                bands_sheet.update_cell(cell.row, cell.col+1, MAC)
            except gspread.exceptions.CellNotFound:
                bands_sheet.append_row([str(band_id), MAC])


