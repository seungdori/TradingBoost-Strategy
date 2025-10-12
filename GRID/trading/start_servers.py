import subprocess
import time


def start_server(port):
    # This function starts the server on the specified port
    subprocess.Popen(["python3", "main.py", "--port", str(port)])

if __name__ == "__main__":
    ports = range(8012, 8015)  # List of ports to run the servers on

    for port in ports:
        start_server(port)
        time.sleep(1)  # Small delay to avoid race conditions

    print("All servers started.")
