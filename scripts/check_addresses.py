"""
Twilio に登録されている住所を確認
"""
import os
import sys
sys.path.insert(0, "D:\\done")

from dotenv import load_dotenv
load_dotenv("D:\\done\\.env")

from twilio.rest import Client

def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    
    client = Client(account_sid, auth_token)
    
    print("=" * 60)
    print("Registered Addresses")
    print("=" * 60)
    
    try:
        addresses = client.addresses.list()
        
        if addresses:
            for addr in addresses:
                print(f"\nSID: {addr.sid}")
                print(f"  Name: {addr.customer_name}")
                print(f"  Street: {addr.street}")
                print(f"  City: {addr.city}")
                print(f"  Region: {addr.region}")
                print(f"  Postal: {addr.postal_code}")
                print(f"  Country: {addr.iso_country}")
                print(f"  Validated: {addr.validated}")
        else:
            print("No addresses registered.")
            print("\nYou need to register an address in Twilio Console:")
            print("https://console.twilio.com/us1/develop/phone-numbers/regulatory-compliance/addresses")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

