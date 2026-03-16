import psutil
import os , time

while True:
    program_name = "python.exe"
    running = False

    for process in psutil.process_iter(['name']):
        if process.info['name'] == program_name:
            running = True
            break


    if running:
        print("Program is running")
    else:
        print("Program is NOT running")
        os.system("start cmd /k python main.py")
    time.sleep(5)