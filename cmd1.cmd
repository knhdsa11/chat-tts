py -m PyInstaller --onefile --clean --name chat-tts ^
--add-data "config.ini;." ^
--add-data "api.py;." ^
--hidden-import=edge_tts ^
--hidden-import=playsound3 ^
main.py