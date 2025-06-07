#!/bin/bash

# Skript zum Starten aller Programme für das Grow-Monitoring-System
# Mit Installation der benötigten Pakete aus den Kommentaren

# Farben für bessere Lesbarkeit
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

print_section() {
    echo -e "${YELLOW}### $1 ###${NC}"
}

print_success() {
    echo -e "${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}$1${NC}"
}

# Funktion, um einen Befehl in einem neuen Terminal auszuführen
run_command() {
    local title=$1
    local command=$2
    # GNOME Terminal verwenden, falls vorhanden
    if command -v gnome-terminal > /dev/null; then
        gnome-terminal --title="$title" -- bash -c "$command; exec bash"
    # Xterm als Fallback
    elif command -v xterm > /dev/null; then
        xterm -title "$title" -e "$command; exec bash" &
    # LXTerminal als weitere Option
    elif command -v lxterminal > /dev/null; then
        lxterminal --title="$title" -e "$command; exec bash" &
    else
        print_error "Kein Terminal-Emulator gefunden. Bitte installieren Sie gnome-terminal, xterm oder lxterminal."
        exit 1
    fi
    sleep 2  # Kurze Pause, um sicherzustellen, dass ein Programm startet, bevor das nächste beginnt
}

install_packages() {
    print_section "Installation der benötigten Pakete"
    
    # Überprüfen, ob apt verfügbar ist (für Raspberry Pi)
    if command -v apt > /dev/null; then
        # Kamera Pakete aus Logger.py
        echo "Installiere Kamera-Pakete..."
        sudo apt install -y python3-picamera2 python3-libcamera
        
        # Überprüfen des Erfolgs
        if [ $? -eq 0 ]; then
            print_success "Kamera-Pakete erfolgreich installiert"
        else
            print_error "Fehler bei der Installation der Kamera-Pakete"
        fi
    else
        print_error "apt nicht gefunden. Pakete müssen manuell installiert werden."
    fi
    
    # Erstelle Virtual Environments falls nötig
    
    # 1. Erstelle growmonitor-env für UI
    if [ ! -d "$HOME/growmonitor-env" ]; then
        echo "Erstelle Virtual Environment 'growmonitor-env' für das Dashboard..."
        python3 -m venv $HOME/growmonitor-env
        source $HOME/growmonitor-env/bin/activate
        # Packages aus General_UI1.py
        pip install dash dash-daq requests apscheduler RPi.GPIO
        pip install pandas dash plotly dash-core-components dash-html-components dash-table requests
        deactivate
        print_success "growmonitor-env erstellt und Pakete installiert"
    fi
    
    # 2. Erstelle env für DHT22 Sensoren
    if [ ! -d "$HOME/env" ]; then
        echo "Erstelle Virtual Environment 'env' für DHT22 Sensoren..."
        python3 -m venv $HOME/env
        source $HOME/env/bin/activate
        # Package aus humidity_logger6.py
        pip install adafruit-circuitpython-dht
        deactivate
        print_success "env erstellt und Pakete installiert"
    fi
    
    # 3. Erstelle soil_sensor_env für Bodensensoren
    if [ ! -d "$HOME/soil_sensor_env" ]; then
        echo "Erstelle Virtual Environment 'soil_sensor_env' für Bodensensoren..."
        python3 -m venv $HOME/soil_sensor_env
        source $HOME/soil_sensor_env/bin/activate
        # Package aus soil_logger.py
        pip install adafruit-circuitpython-seesaw
        deactivate
        print_success "soil_sensor_env erstellt und Pakete installiert"
    fi
}

print_section "Starte alle Programme für das Grow-Monitoring-System"

# Verzeichnisse erstellen, falls sie nicht existieren
mkdir -p ~/dht22
mkdir -p ~/soil_data
mkdir -p ~/timelapse
mkdir -p ~/ventilation_logs

# Frage, ob Pakete installiert werden sollen
read -p "Möchten Sie die benötigten Pakete installieren? (j/n): " install_choice
if [[ $install_choice =~ ^[Jj]$ ]]; then
    install_packages
fi

# 1. Relay-Controller starten (aus Kommentar: python3 ~/relay/relay_controller.py)
print_section "Starte Relay-Controller"
run_command "Relay Controller" "python3 ~/relay/relay_controller.py"

# 2. Belüftungs-API starten (aus Kommentar: python3 ~/Poti/Belüftungs_API.py)
print_section "Starte Belüftungs-API"
run_command "Belüftungs API" "python3 ~/Poti/Belüftungs_API.py"

# 3. DHT22 Sensor-Logger starten (aus Kommentar: source env/bin/activate, python3 ~/dht22/humidity_logger6.py)
print_section "Starte DHT22 Sensor-Logger"
run_command "DHT22 Logger" "source ~/env/bin/activate && python3 ~/dht22/humidity_logger6.py"

# 4. Soil-Logger starten (aus Kommentar: source ~/soil_sensor_env/bin/activate, python3 ~/soil_sensor_env/soil_logger.py)
print_section "Starte Soil-Logger"
run_command "Soil Logger" "source ~/soil_sensor_env/bin/activate && python3 ~/soil_sensor_env/soil_logger.py"

# 5. Kamera-Logger starten (aus Kommentar: python3 ~/camera_timelaps/Logger.py)
print_section "Starte Kamera-Timelapse"
run_command "Kamera Timelapse" "python3 ~/camera_timelaps/Logger.py"

# 6. Dashboard UI starten (aus Kommentar: source ~/growmonitor-env/bin/activate, python3 ~/UI/General_UI1.py)
print_section "Starte Dashboard UI"
run_command "Dashboard UI" "source ~/growmonitor-env/bin/activate && python3 ~/UI/General_UI1.py"

# Warten, damit das Dashboard Zeit hat zu starten
print_section "Warte auf Start des Dashboards"
sleep 10

# 7. Browser öffnen, um das Dashboard anzuzeigen
print_section "Öffne Browser für Dashboard-Anzeige"

# Funktion zum Öffnen des Browsers, testet verschiedene Browser-Optionen
open_browser() {
    local url="http://localhost:8050"
    
    # Prüfe und versuche verschiedene Browser
    if command -v chromium-browser > /dev/null; then
        print_success "Öffne Dashboard mit Chromium..."
        chromium-browser "$url" &
    elif command -v firefox > /dev/null; then
        print_success "Öffne Dashboard mit Firefox..."
        firefox "$url" &
    elif command -v epiphany-browser > /dev/null; then
        print_success "Öffne Dashboard mit Epiphany..."
        epiphany-browser "$url" &
    elif command -v midori > /dev/null; then
        print_success "Öffne Dashboard mit Midori..."
        midori "$url" &
    elif command -v x-www-browser > /dev/null; then
        print_success "Öffne Dashboard mit Standard-Browser..."
        x-www-browser "$url" &
    elif command -v xdg-open > /dev/null; then
        print_success "Öffne Dashboard mit xdg-open..."
        xdg-open "$url" &
    else
        print_error "Kein Browser gefunden. Bitte öffne http://localhost:8050 manuell in deinem Browser."
    fi
}

# Browser öffnen
open_browser

print_success "Alle Programme wurden gestartet!"
echo "--------------------------------"
echo "Um alle Programme zu beenden, schließen Sie die Terminal-Fenster oder führen Sie 'pkill python3' aus."
echo "Dashboard ist erreichbar unter: http://localhost:8050"
