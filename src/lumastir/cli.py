import argparse
import sys
import json
import urllib.request
import urllib.error

def send_request(endpoint, data=None, method="GET", host="http://localhost:8000"):
    url = f"{host}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    
    try:
        if data:
            data_bytes = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        else:
            req = urllib.request.Request(url, headers=headers, method=method)
            
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            print(json.dumps(result, indent=2))
            
    except urllib.error.URLError as e:
        print(f"Error communicating with Lumastir server at {host}:")
        print(f"  {e}")
        print("Is the server running? (try 'systemctl status lumastir' or 'lumastir-server')")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Lumastir CLI Control")
    parser.add_argument("--host", default="http://localhost:8000", help="Server URL (default: http://localhost:8000)")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Status
    subparsers.add_parser("status", help="Get server status")
    
    # Motor
    motor_parser = subparsers.add_parser("motor", help="Control a motor")
    motor_parser.add_argument("channel", type=int, help="Motor channel ID")
    motor_parser.add_argument("speed", type=float, help="Speed percentage (0-100)")
    
    # LED
    led_parser = subparsers.add_parser("led", help="Control an LED")
    led_parser.add_argument("pin", type=int, help="GPIO pin number")
    led_parser.add_argument("brightness", type=float, help="Brightness percentage (0-100)")
    
    args = parser.parse_args()
    
    if args.command == "status":
        send_request("/", host=args.host)
        
    elif args.command == "motor":
        send_request(
            f"/motor/{args.channel}/speed", 
            data={"speed": args.speed}, 
            method="POST", 
            host=args.host
        )
        
    elif args.command == "led":
        send_request(
            f"/led/{args.pin}/brightness", 
            data={"brightness": args.brightness}, 
            method="POST", 
            host=args.host
        )

if __name__ == "__main__":
    main()
