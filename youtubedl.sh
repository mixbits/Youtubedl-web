# This file can be placed within /usr/local/etc/rc.d/ directory to run on bootup
# You can manually start/stop this service with the commands below:
# sudo /usr/local/etc/rc.d/youtubedl.sh [start/stop]
# Real-time logs can be seen with the ffollowing bash command:
# tail -f /var/log/youtubedl.log
#!/bin/sh
# Service script for YouTubeDL downloader
# Configuration
USER="user"
APP_DIR="/volume/youtubedl"
VENV_PATH="$APP_DIR/venv"
PYTHON_CMD="$VENV_PATH/bin/python3"
SCRIPT_NAME="youtubedl.py"
PID_FILE="/var/run/youtubedl.pid"
LOG_FILE="/var/log/youtubedl.log"
PORT=6776
DOWNLOAD_DIR="$APP_DIR/downloads"

# Kill any existing instances using port 6776
kill_existing() {
    # Use netstat instead of lsof (which isn't available on Synology)
    echo "Checking for processes using port $PORT..."
    NETSTAT_PID=$(netstat -tunlp 2>/dev/null | grep ":$PORT" | grep -v grep | awk '{print $7}' | cut -d'/' -f1)
    
    if [ -n "$NETSTAT_PID" ]; then
        echo "Found process using port $PORT (PID: $NETSTAT_PID)"
        kill -9 $NETSTAT_PID 2>/dev/null
        sleep 2
        return 0
    fi
    
    # If netstat didn't work, try using ps and grep as a backup method
    echo "Trying alternative method to find process..."
    PS_OUTPUT=$(ps -ef | grep python | grep youtubedl | grep -v grep)
    if [ -n "$PS_OUTPUT" ]; then
        PS_PID=$(echo "$PS_OUTPUT" | awk '{print $2}')
        echo "Found Python process that might be our server (PID: $PS_PID)"
        kill -9 $PS_PID 2>/dev/null
        sleep 2
        return 0
    fi
    
    echo "No process found using port $PORT"
    return 1
}

case "$1" in
    start)
        echo "Starting YouTubeDL service..."
        
        # Kill any existing processes using the port
        kill_existing
        
        # Check if HTML file exists
        if [ ! -f "$APP_DIR/youtubedl.html" ]; then
            echo "WARNING: HTML file not found at $APP_DIR/youtubedl.html"
            echo "Listing directory contents:"
            ls -la $APP_DIR
        fi
        
        # Create necessary directories
        mkdir -p "$DOWNLOAD_DIR"
        chown -R "$USER" "$APP_DIR"
        
        # Create log file if it doesn't exist
        touch "$LOG_FILE"
        chown "$USER" "$LOG_FILE"
        
        # Ensure virtual environment exists
        if [ ! -d "$VENV_PATH" ]; then
            echo "Creating virtual environment at $VENV_PATH"
            mkdir -p "$APP_DIR"
            cd "$APP_DIR"
            su - "$USER" -c "python3 -m venv $VENV_PATH"
            su - "$USER" -c "$VENV_PATH/bin/pip install --upgrade pip"
            su - "$USER" -c "$VENV_PATH/bin/pip install flask"
        fi
        
        # Install yt-dlp
        echo "Installing/upgrading yt-dlp..."
        su - "$USER" -c "$VENV_PATH/bin/pip install --upgrade yt-dlp"
        
        # Check for FFmpeg
        if [ ! -d "$HOME/ffmpeg" ]; then
            echo "Installing FFmpeg (required for yt-dlp)..."
            # Try to install ffmpeg with package manager if available
            if command -v apk > /dev/null; then
                apk add --no-cache ffmpeg
            elif command -v apt-get > /dev/null; then
                apt-get -y install ffmpeg
            elif command -v yum > /dev/null; then
                yum -y install ffmpeg
            else
                echo "WARNING: Could not install FFmpeg automatically, yt-dlp may not work properly"
                # On Synology, user might need to install FFmpeg manually
            fi
        fi
        
        # Start the application using the virtual environment Python
        cd "$APP_DIR"
        echo "Starting application from directory: $APP_DIR"
        echo "Using Python: $PYTHON_CMD"
        echo "Running script: $APP_DIR/$SCRIPT_NAME"
        
        # Start the process and capture PID correctly
        su - "$USER" -c "cd $APP_DIR && $PYTHON_CMD $APP_DIR/$SCRIPT_NAME" >> "$LOG_FILE" 2>&1 &
        
        # Get the correct PID
        sleep 2
        SERVER_PID=$(ps -ef | grep python | grep youtubedl.py | grep -v grep | awk '{print $2}')
        
        if [ -n "$SERVER_PID" ]; then
            echo $SERVER_PID > "$PID_FILE"
            echo "YouTubeDL service started with PID: $SERVER_PID"
            
            # Verify the service is running
            sleep 3
            if ps -p $SERVER_PID > /dev/null 2>&1; then
                echo "Service is running successfully."
            else
                echo "Warning: Service may not have started correctly. Check logs at $LOG_FILE"
            fi
        else
            echo "Warning: Could not find PID for started service. Check logs at $LOG_FILE"
        fi
        ;;
        
    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            echo "Stopping YouTubeDL service (PID: $PID)..."
            kill $PID 2>/dev/null
            
            # Force kill if still running after 5 seconds
            sleep 5
            if ps -p $PID > /dev/null 2>&1; then
                echo "Service still running, force killing..."
                kill -9 $PID 2>/dev/null
            fi
            
            rm -f "$PID_FILE"
            echo "YouTubeDL service stopped."
        else
            # Try alternative methods to find and stop the process
            echo "PID file not found. Trying to find process by other means..."
            kill_existing
            echo "Any matching processes have been stopped."
        fi
        ;;
        
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
        
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p $PID > /dev/null 2>&1; then
                echo "YouTubeDL service is running (PID: $PID)"
                exit 0
            else
                echo "PID file exists but process is not running."
                rm -f "$PID_FILE"
                
                # Check if another instance is running on the port
                NETSTAT_OUTPUT=$(netstat -tunlp 2>/dev/null | grep ":$PORT")
                if [ -n "$NETSTAT_OUTPUT" ]; then
                    NETSTAT_PID=$(echo "$NETSTAT_OUTPUT" | awk '{print $7}' | cut -d'/' -f1)
                    echo "Found another process using port $PORT (PID: $NETSTAT_PID)"
                    exit 1
                else
                    exit 1
                fi
            fi
        else
            # Check if a process is using the port
            NETSTAT_OUTPUT=$(netstat -tunlp 2>/dev/null | grep ":$PORT")
            if [ -n "$NETSTAT_OUTPUT" ]; then
                NETSTAT_PID=$(echo "$NETSTAT_OUTPUT" | awk '{print $7}' | cut -d'/' -f1)
                echo "Found process using port $PORT (PID: $NETSTAT_PID) but no PID file."
                exit 1
            else
                # Try ps as a last resort
                PS_OUTPUT=$(ps -ef | grep python | grep youtubedl | grep -v grep)
                if [ -n "$PS_OUTPUT" ]; then
                    PS_PID=$(echo "$PS_OUTPUT" | awk '{print $2}')
                    echo "Found Python process that might be our server (PID: $PS_PID) but no PID file."
                    exit 1
                else
                    echo "YouTubeDL service is not running."
                    exit 1
                fi
            fi
        fi
        ;;
        
    debug)
        echo "Debug information for YouTubeDL service:"
        echo "-------------------------------------------"
        echo "Configuration:"
        echo "  User: $USER"
        echo "  App directory: $APP_DIR"
        echo "  Virtual env: $VENV_PATH"
        echo "  Python command: $PYTHON_CMD"
        echo "  Script name: $SCRIPT_NAME"
        echo "  PID file: $PID_FILE"
        echo "  Log file: $LOG_FILE"
        echo "  Download directory: $DOWNLOAD_DIR"
        echo ""
        
        echo "Directory contents:"
        ls -la $APP_DIR
        
        echo ""
        echo "HTML file exists: $([ -f "$APP_DIR/youtubedl.html" ] && echo "Yes" || echo "No")"
        echo "Python script exists: $([ -f "$APP_DIR/$SCRIPT_NAME" ] && echo "Yes" || echo "No")"
        echo "Download directory exists: $([ -d "$DOWNLOAD_DIR" ] && echo "Yes" || echo "No")"
        echo ""
        
        echo "yt-dlp check:"
        if [ -f "$VENV_PATH/bin/yt-dlp" ]; then
            echo "  yt-dlp is installed"
            echo "  Version: $($VENV_PATH/bin/yt-dlp --version 2>/dev/null || echo "Unknown")"
        else
            echo "  yt-dlp is NOT installed"
        fi
        
        echo ""
        echo "Process status:"
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            echo "  PID file exists with PID: $PID"
            if ps -p $PID > /dev/null 2>&1; then
                echo "  Process is running"
            else
                echo "  Process is NOT running"
            fi
        else
            echo "  PID file does not exist"
        fi
        
        echo ""
        echo "Port status:"
        NETSTAT_OUTPUT=$(netstat -tunlp 2>/dev/null | grep ":$PORT")
        if [ -n "$NETSTAT_OUTPUT" ]; then
            echo "  Port $PORT is in use by a process"
            echo "  $NETSTAT_OUTPUT"
        else
            echo "  Port $PORT is not in use"
        fi
        
        echo ""
        echo "Related processes:"
        ps -ef | grep python | grep -v grep
        
        echo ""
        echo "Last 10 log entries:"
        tail -n 10 $LOG_FILE
        ;;
        
    clean)
        echo "Cleaning download directory..."
        if [ -d "$DOWNLOAD_DIR" ]; then
            find "$DOWNLOAD_DIR" -type f -mtime +7 -delete
            echo "Removed files older than 7 days"
        else
            echo "Download directory does not exist"
        fi
        ;;
        
    *)
        echo "Usage: $0 {start|stop|restart|status|debug|clean}"
        exit 1
        ;;
esac

exit 0
