import requests
import json
import csv
from datetime import datetime

API_BASE_URL = os.environ.get('API_BASE_URL')

class QueueExporter:
    def __init__(self):
        self.all_queues = []
        
    def get_rems(self):
        try:
            print("📍 Завантажую РЕМи...")
            response = requests.get(f"{API_BASE_URL}api-rem.php", timeout=10)
            rems = response.json()
            print(f"✅ Завантажено {len(rems) if isinstance(rems, list) else 1} РЕМів")
            return rems if isinstance(rems, list) else [rems]
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return []
    
    def get_cities(self, rem_id):
        try:
            response = requests.get(f"{API_BASE_URL}api-city.php?rem_id={rem_id}", timeout=10)
            cities = response.json()
            return cities if isinstance(cities, list) else [cities]
        except Exception as e:
            return []
    
    def get_streets(self, city_id):
        try:
            response = requests.get(f"{API_BASE_URL}api-street.php?city_id={city_id}", timeout=10)
            streets = response.json()
            return streets if isinstance(streets, list) else [streets]
        except Exception as e:
            return []
    
    def get_addresses(self, street_id):
        try:
            response = requests.get(f"{API_BASE_URL}api-address.php?street_id={street_id}", timeout=10)
            addresses = response.json()
            return addresses if isinstance(addresses, list) else [addresses]
        except Exception as e:
            return []
    
    def export_all(self):
        print("=" * 70)
        print("🔍 ВИВАНТАЖЕННЯ ВСІХ ЧЕРГ ТА АДРЕС")
        print("=" * 70)
        
        rems = self.get_rems()
        total_addresses = 0
        
        for rem_idx, rem in enumerate(rems, 1):
            rem_id = rem.get('id', rem.get('cherga_id'))
            rem_name = rem.get('name', rem.get('title', f'РЕМ {rem_id}'))
            
            print(f"\n📌 РЕМ {rem_idx}/{len(rems)}: {rem_name} (ID: {rem_id})")
            
            cities = self.get_cities(rem_id)
            print(f"   └─ 🏙️ Міст: {len(cities)}")
            
            for city_idx, city in enumerate(cities, 1):
                city_id = city.get('id', city.get('city_id'))
                city_name = city.get('name', city.get('title', f'Місто {city_id}'))
                
                streets = self.get_streets(city_id)
                print(f"      └─ 🛣️  {city_name}: {len(streets)} вулиць")
                
                for street_idx, street in enumerate(streets, 1):
                    street_id = street.get('id', street.get('street_id'))
                    street_name = street.get('name', street.get('title', f'Вулиця {street_id}'))
                    
                    addresses = self.get_addresses(street_id)
                    
                    for addr_idx, addr in enumerate(addresses, 1):
                        queue_id = addr.get('cherga_id', addr.get('queue_id'))
                        subqueue_id = addr.get('pidcherga_id', addr.get('subqueue_id'))
                        addr_name = addr.get('name', addr.get('title', f'Адреса {addr_idx}'))
                        
                        queue_data = {
                            'rem_id': rem_id,
                            'rem_name': rem_name,
                            'city_id': city_id,
                            'city_name': city_name,
                            'street_id': street_id,
                            'street_name': street_name,
                            'address_id': addr.get('id', None),
                            'address_name': addr_name,
                            'queue_id': queue_id,
                            'subqueue_id': subqueue_id,
                            'full_address': f"{rem_name}, {city_name}, вул. {street_name}, {addr_name}"
                        }
                        
                        self.all_queues.append(queue_data)
                        total_addresses += 1
                        
                        if total_addresses % 50 == 0:
                            print(f"         ✓ Завантажено {total_addresses} адрес...")
        
        print("\n" + "=" * 70)
        print(f"✅ ЗАВЕРШЕНО! Завантажено {total_addresses} адрес")
        print("=" * 70)
        
        return self.all_queues
    
    def save_json(self, filename='all_queues.json'):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.all_queues, f, indent=2, ensure_ascii=False)
        print(f"💾 JSON збережено: {filename}")
    
    def save_csv(self, filename='all_queues.csv'):
        if not self.all_queues:
            print("❌ Немає даних для збереження")
            return
        
        keys = self.all_queues[0].keys()
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.all_queues)
        print(f"💾 CSV збережено: {filename}")
    
    def print_summary(self):
        if not self.all_queues:
            return
        
        print("\n" + "=" * 70)
        print("📊 СТАТИСТИКА")
        print("=" * 70)
        
        rems = set(q['rem_name'] for q in self.all_queues)
        cities = set(q['city_name'] for q in self.all_queues)
        streets = set(q['street_name'] for q in self.all_queues)
        
        print(f"🏘️  РЕМів: {len(rems)}")
        print(f"🏙️  Міст: {len(cities)}")
        print(f"🛣️  Вулиць: {len(streets)}")
        print(f"🏠 Адрес (черг): {len(self.all_queues)}")
        print("=" * 70)

if __name__ == '__main__':
    exporter = QueueExporter()
    queues = exporter.export_all()
    exporter.save_json('all_queues.json')
    exporter.save_csv('all_queues.csv')
    exporter.print_summary()
